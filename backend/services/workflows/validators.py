import re
import logging
import math
import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from backend.services.llm.embedding import get_embedding

logger = logging.getLogger(__name__)

class ValidationResult(BaseModel):
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    # CP1.1 修复：补 categories 字段（原 MicroReviewer 引用 result.categories 但 schema 缺失）
    # 携带失败类别（红线/物理幻觉/OOC/关系/文风/其他）供 _adjust_after_failure 调温使用
    categories: List[str] = []

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2: return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0 or mag2 == 0: return 0.0
    return dot_product / (mag1 * mag2)

class BaseValidator:
    """验证器基类"""
    async def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        raise NotImplementedError("Subclasses must implement validate()")

class StyleClicheValidator(BaseValidator):
    """AI 腔陈词滥调及黑名单拦截（Cliché & Blacklist Regex Filter）。

    禁忌面归一（任务包 A）：数据源改为 services/style/prohibitions.py 的
    load_prohibition_set（四源合并唯一权威）：
    1. SystemCliche 表（cliche_provider 直查，DB 失败降级种子）
    2. style_card.negative_list（context["style_negative_list"]）
    3. book.style_blacklist（context["style_blacklist"]）
    4. anti_ai_rules.DEFAULT_BAN_LIST.banned_words（静态反 AI 词，全 warning）
    本书豁免 context["cliche_exemptions"] 仅作用于系统层。

    设计：
    - 首次 validate 时异步加载（缓存到实例）
    - 后续 validate 直接用缓存
    - 可手动 reload() 刷新（SystemCliche CRUD 后）
    - validate 的软失败计数排除静态源命中（见 validate 注释）
    """
    def __init__(self, threshold: int = 2):
        self.threshold = threshold
        # 实例缓存：编译后的正则列表 + 原始 cliches 描述（用于命中后给 LLM 看替代建议）
        self._compiled_patterns: List[tuple] = []  # [(compiled_re, alternative, severity), ...]
        # 禁忌面归一新增：[(compiled, ProhibitionEntry)]——validate 按
        # entry.source 排除静态源命中；ClichéAuditor 等旧消费方仍用 _compiled_patterns
        self._compiled_entries: List[tuple] = []
        self._loaded: bool = False

    async def _ensure_loaded(self, context: Optional[Dict[str, Any]] = None) -> None:
        """首次访问时加载禁词（四源合并，prohibitions.py 唯一权威）。

        幂等：已加载则跳过。reload() 可强制刷新。
        context 契约键名不变：db / style_blacklist / style_negative_list /
        cliche_exemptions（供 ClichéAuditor / scan-negative 等调用方预填）。
        """
        if self._loaded:
            return

        from backend.services.style.prohibitions import load_prohibition_set

        ps = await load_prohibition_set(
            db=context.get("db") if context else None,
            style_blacklist=context.get("style_blacklist") if context else None,
            negative_list=context.get("style_negative_list") if context else None,
            cliche_exemptions=context.get("cliche_exemptions") if context else None,
        )
        self._compiled_patterns = ps.compiled_patterns
        self._compiled_entries = list(ps.compiled)

        self._loaded = True
        logger.info(f"[StyleClicheValidator] 已加载 {len(self._compiled_patterns)} 条禁词")

    def reload(self) -> None:
        """强制下次 validate 时重新加载（SystemCliche CRUD 后调用）。"""
        self._loaded = False
        self._compiled_patterns = []
        self._compiled_entries = []

    async def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []

        # CP2.2c：首次访问加载禁词
        await self._ensure_loaded(context)

        match_count = 0
        matched_cliches = []
        blocker_matches = []

        for compiled, entry in self._compiled_entries:
            matches = compiled.findall(text)
            if not matches:
                continue
            # 禁忌面归一：软失败计数排除静态反 AI 词（深邃/宛如等高频词
            # 在正常叙事里也会出现，计入会轻易越过 threshold=2 误伤——
            # 静态词的约束交给 ai_taste_meter 密度算法，不进 fail-fast）
            if entry.source != "anti_ai_static":
                match_count += len(matches)
                matched_cliches.extend(matches)
            # blocker 判定不变：静态源全 warning，天然不影响
            if entry.severity == "blocker":
                blocker_matches.extend(matches)

        # blocker 命中即硬失败（不受 threshold 调节）
        if blocker_matches:
            errors.append(
                f"触发硬阻断禁词（共 {len(blocker_matches)} 次）。"
                f"命中的词汇包含：{', '.join(set(blocker_matches))}。"
                f"请重写以根除这些 AI 默认腔调。"
            )
            return ValidationResult(
                is_valid=False, errors=errors, warnings=warnings, categories=["文风"]
            )

        # warning 类按 threshold 软失败
        if match_count > self.threshold:
            errors.append(
                f"检测到过多AI陈词滥调或文风黑名单词汇（共 {match_count} 次，超过阈值 {self.threshold}）。"
                f"命中的词汇包含：{', '.join(set(matched_cliches))}。请重写以降低AI味并遵循书籍文风设定。"
            )
            # CP1.1：文风类失败，供 _adjust_after_failure 升温
            return ValidationResult(
                is_valid=False, errors=errors, warnings=warnings, categories=["文风"]
            )
        elif match_count > 0:
            warnings.append(f"包含轻微AI陈词滥调或不建议词汇：{', '.join(set(matched_cliches))}")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

class CharacterOOCValidator(BaseValidator):
    """
    人物性格防偏离验证 (Character OOC Validator)
    使用嵌入词向量模型(Embedding)动态计算动作文本与角色设定的语义偏离度。
    """
    def __init__(self, similarity_threshold: float = 0.15):
        # 设定语义相似度下限阈值，如果行为与设定的余弦相似度极低，视为 OOC 嫌疑
        self.similarity_threshold = similarity_threshold

    async def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        
        # 从上下文中获取角色特征标签 (从数据库 entities 获取)
        entities = context.get("entities", [])
        if not entities:
            return ValidationResult(is_valid=True, errors=errors, warnings=warnings)
            
        # 拆分句子，用于提取包含角色名的句子
        sentences = [s.strip() for s in re.split(r'[。！？!?\n]', text) if len(s.strip()) > 2]
            
        for entity in entities:
            name = entity.get("name", "")
            if not name or name not in text:
                continue
                
            static_prompt = entity.get("static_prompt", "")
            traits = entity.get("traits", [])
            
            if not static_prompt and not traits:
                continue
                
            # 组合角色核心设定文本
            character_core_desc = f"角色名称：{name}。"
            if static_prompt:
                character_core_desc += f" 核心设定：{static_prompt}。"
            if traits:
                character_core_desc += f" 性格特征：{'、'.join(traits)}。"
                
            # 提取与该角色相关的句子作为动作文本
            character_sentences = [s for s in sentences if name in s]
            if not character_sentences:
                continue
                
            character_action_text = "。".join(character_sentences) + "。"
            
            try:
                # 并发请求词向量
                desc_emb_task = get_embedding(character_core_desc)
                action_emb_task = get_embedding(character_action_text)
                
                desc_emb, action_emb = await asyncio.gather(desc_emb_task, action_emb_task)
                
                if desc_emb and action_emb:
                    sim = cosine_similarity(desc_emb, action_emb)
                    logger.debug(f"[OOC Validator] {name} 设定与行为相似度: {sim:.3f}")
                    
                    if sim < self.similarity_threshold:
                        # 相似度过低，抛出警告要求修改
                        warnings.append(
                            f"角色 '{name}' 在本段中的行为/对白与角色设定的语义偏离度过高 "
                            f"(相似度: {sim:.2f})，可能发生了 OOC 行为，请根据角色设定进行修正。"
                        )
            except Exception as e:
                logger.error(f"[OOC Validator] 词向量计算失败，跳过 OOC 验证: {e}")
                        
        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

class PlotLogicValidator(BaseValidator):
    """
    剧情逻辑与伏笔闭合强制校验 (Plot Logic Validator)
    """
    async def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        
        # 校验指定的伏笔/实体是否出现
        required_entities = context.get("required_entities", [])
        for entity in required_entities:
            if entity not in text:
                errors.append(f"剧情逻辑错误：当前节拍要求必须提及实体/伏笔 '{entity}'，但在生成的正文中未找到。")
                
        # 简单的时空物理逻辑校验 (例如不该出现的地点)
        forbidden_locations = context.get("forbidden_locations", [])
        for loc in forbidden_locations:
            if loc in text:
                errors.append(f"时空逻辑错误：检测到角色不可能出现的地点 '{loc}'。")
                
        # 检查书籍全局禁忌 (core_motifs_taboos) 以及 Beat 红线 (red_lines)
        taboos = context.get("taboos", "")
        red_lines = context.get("red_lines", [])
        
        # 将红线和禁忌中的特定实体进行硬校验（启发式提取引号内的词作为绝对禁止词）
        all_constraints = []
        if isinstance(taboos, str) and taboos:
            all_constraints.append(taboos)
        all_constraints.extend(red_lines)
        
        for constraint in all_constraints:
            forbidden_phrases = re.findall(r'["\']([^"\']+)["\']', constraint)
            for phrase in forbidden_phrases:
                if phrase and phrase in text:
                    errors.append(f"触发红线/禁忌约束！文本中出现了被绝对禁止的内容：'{phrase}' (源自设定: {constraint})")

        # CP1.1：根据 errors 来源填充 categories
        # - 红线/禁忌触发 → "红线"
        # - 物理地点矛盾 → "物理幻觉"
        # - 必须实体缺失 → "逻辑"
        cats = []
        if any("红线" in e or "禁忌" in e for e in errors):
            cats.append("红线")
        if any("时空逻辑" in e or "地点" in e for e in errors):
            cats.append("物理幻觉")
        if any("必须提及" in e or "剧情逻辑错误" in e for e in errors):
            cats.append("逻辑")
        return ValidationResult(
            is_valid=len(errors) == 0, errors=errors, warnings=warnings, categories=cats
        )

class PacingValidator(BaseValidator):
    """
    基于环境参数（节奏类型 pacing_type）验证句法结构
    """
    async def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        
        pacing = context.get("pacing_type", "medium").lower()
        
        # 简单过滤空字符串和太短的标点
        sentences = [s.strip() for s in re.split(r'[。！？!?\n]', text) if len(s.strip()) > 2]
        if not sentences:
            return ValidationResult(is_valid=True, errors=errors, warnings=warnings)
            
        avg_length = sum(len(s) for s in sentences) / len(sentences)
        
        if pacing == "fast" and avg_length > 35:
            errors.append(f"当前环境参数要求 'Fast' (快节奏)，但平均句长达到 {avg_length:.1f} 字，行文显得拖沓。请多用短句和连续动作描写。")
            # CP1.1：句长问题归入"文风"类（影响阅读节奏，升温重写）
            return ValidationResult(
                is_valid=False, errors=errors, warnings=warnings, categories=["文风"]
            )
        elif pacing == "slow" and avg_length < 10:
            warnings.append(f"当前环境参数要求 'Slow' (慢节奏)，但平均句长只有 {avg_length:.1f} 字，建议增加细节与感官描写以渲染氛围。")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

class DraftValidatorPipeline:
    """
    统一的起草验证管道
    """
    def __init__(self):
        self.validators = [
            StyleClicheValidator(),
            CharacterOOCValidator(),
            PlotLogicValidator(),
            PacingValidator()
        ]

    async def validate_draft(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        """
        运行所有验证器，收集错误和警告。
        """
        all_errors = []
        all_warnings = []
        all_categories = []  # CP1.1：合并各校验器的 categories

        # 并发执行所有验证器
        tasks = [validator.validate(text, context) for validator in self.validators]
        results = await asyncio.gather(*tasks)

        for result in results:
            all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)
            if result.categories:
                all_categories.extend(result.categories)

        is_valid = len(all_errors) == 0
        # 去重 categories，保留顺序
        unique_categories = list(dict.fromkeys(all_categories))
        return ValidationResult(
            is_valid=is_valid,
            errors=all_errors,
            warnings=all_warnings,
            categories=unique_categories,
        )
