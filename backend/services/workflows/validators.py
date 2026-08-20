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

    CP2.2c 改造：禁词数据源从硬编码改为三层合并：
    1. SystemCliche 表（通过 cliche_provider，带缓存）
    2. book.style_blacklist（书级，向后兼容）
    3. style_card.negative_list（书级 StyleCard，CP2.2d 接入）

    设计：
    - 首次 validate 时异步加载 cliches（缓存到实例）
    - 后续 validate 直接用缓存
    - 可手动 reload() 刷新（SystemCliche CRUD 后）
    """
    def __init__(self, threshold: int = 2):
        # CP2.2c：硬编码 default_cliches 已外迁到 services/style/default_cliches.py
        # 通过 cliche_provider 在首次 validate 时异步加载（带缓存）
        self.threshold = threshold
        # 实例缓存：编译后的正则列表 + 原始 cliches 描述（用于命中后给 LLM 看替代建议）
        self._compiled_patterns: List[tuple] = []  # [(compiled_re, alternative, severity), ...]
        self._loaded: bool = False

    async def _ensure_loaded(self, context: Optional[Dict[str, Any]] = None) -> None:
        """首次访问时加载禁词（含 SystemCliche DB 数据 + book 级 blacklist + style_card.negative_list）。

        幂等：已加载则跳过。reload() 可强制刷新。
        """
        if self._loaded:
            return

        cliches: List[tuple] = []  # [(pattern_str, is_regex, alternative, severity), ...]

        # 层 1：SystemCliche（通过 cliche_provider，DB 优先、降级到种子）
        # 本书豁免（设计稿 §6.4 三层可见性）：books.style_cliche_exemptions 里的
        # pattern 从系统层剔除（不删全局，仅本书不生效）
        exemptions = set()
        if context:
            raw_exemptions = context.get("cliche_exemptions")
            if isinstance(raw_exemptions, (list, tuple, set)):
                exemptions = {str(p) for p in raw_exemptions if p}
        try:
            from backend.services.style.cliche_provider import get_active_cliches
            # 系统层直查 DB（use_cache=False，禁词量级小，单表查询开销可忽略）：
            # 旧路径 db=None 永远只回种子降级，用户在 /system/cliches 增改的禁词
            # 从不进审计/扫描。调用方经 context["db"] 传入 AsyncSession（路由与
            # ClichéAuditor 均已接）；无 db 时维持种子降级（行为不变）。
            db_session = context.get("db") if context else None
            system_cliches = await get_active_cliches(db=db_session, use_cache=False)
            for item in system_cliches:
                if item.get("pattern", "") in exemptions:
                    continue
                cliches.append((
                    item.get("pattern", ""),
                    bool(item.get("is_regex", False)),
                    item.get("alternative"),
                    item.get("severity", "warning"),
                ))
        except Exception as e:
            logger.warning(f"[StyleClicheValidator] 加载 SystemCliche 失败，降级: {e}")
            # 兜底：直接用 default_cliches 种子
            from backend.services.style.default_cliches import get_all_seed_cliches
            for item in get_all_seed_cliches():
                if item.get("pattern", "") in exemptions:
                    continue
                cliches.append((
                    item.get("pattern", ""),
                    bool(item.get("is_regex", False)),
                    item.get("alternative"),
                    item.get("severity", "warning"),
                ))

        # 层 2：book.style_blacklist（向后兼容，CP0 字段）
        if context:
            book_blacklist = context.get("style_blacklist")
            if book_blacklist:
                items = []
                if isinstance(book_blacklist, str):
                    items = [c.strip() for c in re.split(r'[,，\n]', book_blacklist) if c.strip()]
                elif isinstance(book_blacklist, list):
                    items = book_blacklist
                for item in items:
                    if isinstance(item, str):
                        cliches.append((item, False, None, "warning"))
                    elif isinstance(item, dict):
                        word = item.get("word") or item.get("phrase") or ""
                        if word:
                            cliches.append((
                                word, False,
                                item.get("alternative"),
                                item.get("severity", "warning"),
                            ))

        # 层 3：style_card.negative_list（CP2.2d 接入，CP2.2c 预留）
        if context:
            style_negative = context.get("style_negative_list")
            if style_negative and isinstance(style_negative, list):
                for item in style_negative:
                    if isinstance(item, dict):
                        word = item.get("word") or item.get("phrase") or ""
                        if word:
                            cliches.append((
                                word, False,
                                item.get("alternative"),
                                "warning",
                            ))

        # 编译正则
        self._compiled_patterns = []
        for pattern_str, is_regex, alt, sev in cliches:
            if not pattern_str:
                continue
            try:
                flags = 0 if is_regex else 0
                # 非 regex 模式按字面匹配（转义特殊字符）
                actual_pattern = pattern_str if is_regex else re.escape(pattern_str)
                compiled = re.compile(actual_pattern, flags)
                self._compiled_patterns.append((compiled, alt or "", sev or "warning"))
            except re.error:
                continue

        self._loaded = True
        logger.info(f"[StyleClicheValidator] 已加载 {len(self._compiled_patterns)} 条禁词")

    def reload(self) -> None:
        """强制下次 validate 时重新加载（SystemCliche CRUD 后调用）。"""
        self._loaded = False
        self._compiled_patterns = []

    async def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []

        # CP2.2c：首次访问加载禁词
        await self._ensure_loaded(context)

        match_count = 0
        matched_cliches = []
        blocker_matches = []

        for compiled, alternative, severity in self._compiled_patterns:
            matches = compiled.findall(text)
            if matches:
                match_count += len(matches)
                matched_cliches.extend(matches)
                if severity == "blocker":
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
