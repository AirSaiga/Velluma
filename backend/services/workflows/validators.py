import re
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class ValidationResult(BaseModel):
    is_valid: bool
    errors: List[str]
    warnings: List[str]

class BaseValidator:
    """验证器基类"""
    def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        raise NotImplementedError("Subclasses must implement validate()")

class StyleClicheValidator(BaseValidator):
    """
    “AI味”陈词滥调及黑名单拦截 (Cliché & Blacklist Regex Filter)
    """
    def __init__(self, threshold: int = 2):
        self.default_cliches = [
            r"眼底闪过一丝",
            r"嘴角勾起一抹",
            r"不禁倒吸一口凉气",
            r"总而言之",
            r"不可名状的",
            r"深邃的眼眸",
            r"宛如实质般的",
            r"难以言喻的",
            r"勾起一抹冷笑",
            r"倒吸一口凉气",
        ]
        self.threshold = threshold

    def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        
        # 融合默认陈词滥调与数据库中书籍的 style_blacklist
        cliches = list(self.default_cliches)
        book_blacklist = context.get("style_blacklist")
        if book_blacklist:
            # 假设 book_blacklist 是以逗号、换行分隔的字符串，或者是一个列表
            if isinstance(book_blacklist, str):
                cliches.extend([c.strip() for c in re.split(r'[,，\n]', book_blacklist) if c.strip()])
            elif isinstance(book_blacklist, list):
                cliches.extend(book_blacklist)
                
        compiled_patterns = []
        for pattern in cliches:
            try:
                compiled_patterns.append(re.compile(pattern))
            except re.error:
                continue
        
        match_count = 0
        matched_cliches = []
        for pattern in compiled_patterns:
            matches = pattern.findall(text)
            if matches:
                match_count += len(matches)
                matched_cliches.extend(matches)
        
        if match_count > self.threshold:
            errors.append(
                f"检测到过多AI陈词滥调或文风黑名单词汇（共 {match_count} 次，超过阈值 {self.threshold}）。"
                f"命中的词汇包含：{', '.join(set(matched_cliches))}。请重写以降低AI味并遵循书籍文风设定。"
            )
        elif match_count > 0:
            warnings.append(f"包含轻微AI陈词滥调或不建议词汇：{', '.join(set(matched_cliches))}")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

class CharacterOOCValidator(BaseValidator):
    """
    人物性格防偏离验证 (Character OOC Validator)
    结合实体数据进行检查
    """
    def __init__(self):
        # 静态的常见映射字典。
        # 更好的方案是引入一个轻量级的词向量比对，这里用硬匹配作为纯代码示例
        self.forbidden_action_map = {
            "怯懦": ["咆哮", "猛击", "冷笑", "一脚踹开", "怒吼", "大声斥责", "毫不畏惧"],
            "冷静": ["气急败坏", "歇斯底里", "手足无措", "慌乱", "失去理智"],
            "高傲": ["卑躬屈膝", "连声求饶", "唯唯诺诺", "跪地"]
        }

    def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        
        # 从上下文中获取角色特征标签 (从数据库 entities 获取)
        entities = context.get("entities", [])
        if not entities:
            return ValidationResult(is_valid=True, errors=errors, warnings=warnings)
            
        for entity in entities:
            name = entity.get("name", "")
            if not name:
                continue
                
            # 我们假设 entity.get("static_prompt") 包含一些性格描述词
            # 或者有独立的 traits 字段
            traits = entity.get("traits", [])
            static_prompt = entity.get("static_prompt", "")
            
            # 如果没有 traits，尝试从 static_prompt 简单提取（启发式）
            if not traits and isinstance(static_prompt, str):
                for trait in self.forbidden_action_map.keys():
                    if trait in static_prompt:
                        traits.append(trait)
            
            # 如果文中出现了该角色
            if name in text:
                for trait in traits:
                    forbidden_words = self.forbidden_action_map.get(trait, [])
                    found_words = [word for word in forbidden_words if word in text]
                    
                    if found_words:
                        errors.append(
                            f"角色 '{name}' 具有 '{trait}' 的特征设定，但检测到了不符合性格的动作描写："
                            f"{', '.join(found_words)}。请修正以避免OOC。"
                        )
                        
        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

class PlotLogicValidator(BaseValidator):
    """
    剧情逻辑与伏笔闭合强制校验 (Plot Logic Validator)
    """
    def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
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

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

class PacingValidator(BaseValidator):
    """
    基于环境参数（节奏类型 pacing_type）验证句法结构
    """
    def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
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

    def validate_draft(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        """
        运行所有验证器，收集错误和警告。
        """
        all_errors = []
        all_warnings = []
        
        for validator in self.validators:
            result = validator.validate(text, context)
            all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)
            
        is_valid = len(all_errors) == 0
        return ValidationResult(is_valid=is_valid, errors=all_errors, warnings=all_warnings)
