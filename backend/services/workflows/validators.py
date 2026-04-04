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
    “AI味”陈词滥调黑名单拦截 (Cliché Regex Filter)
    """
    def __init__(self, threshold: int = 2):
        # 常见AI生成的网文陈词滥调
        self.cliches = [
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
        self.compiled_patterns = [re.compile(pattern) for pattern in self.cliches]
        self.threshold = threshold

    def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        
        match_count = 0
        matched_cliches = []
        for pattern in self.compiled_patterns:
            matches = pattern.findall(text)
            if matches:
                match_count += len(matches)
                matched_cliches.extend(matches)
        
        if match_count > self.threshold:
            errors.append(
                f"检测到过多AI陈词滥调（共 {match_count} 次，超过阈值 {self.threshold}）。"
                f"命中的词汇包含：{', '.join(set(matched_cliches))}。请重写以降低AI味。"
            )
        elif match_count > 0:
            warnings.append(f"包含轻微AI陈词滥调：{', '.join(set(matched_cliches))}")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

class CharacterOOCValidator(BaseValidator):
    """
    人物性格防偏离验证 (Character OOC Validator)
    通过动作情感词典硬性约束。
    """
    def __init__(self):
        # 简单示例：根据角色特征禁用特定词汇。
        # 理想情况下，这些规则可以从数据库动态加载。
        self.forbidden_action_map = {
            "怯懦": ["咆哮", "猛击", "冷笑", "一脚踹开", "怒吼", "大声斥责"],
            "冷静": ["气急败坏", "歇斯底里", "手足无措", "慌乱"],
            "高傲": ["卑躬屈膝", "连声求饶", "唯唯诺诺"]
        }

    def validate(self, text: str, context: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings = []
        
        # 从上下文中获取角色特征标签
        entities = context.get("entities", [])
        if not entities:
            return ValidationResult(is_valid=True, errors=errors, warnings=warnings)
            
        for entity in entities:
            name = entity.get("name", "")
            traits = entity.get("traits", []) # 比如 ["怯懦", "聪明"]
            
            # 如果文中出现了该角色
            if name in text:
                for trait in traits:
                    forbidden_words = self.forbidden_action_map.get(trait, [])
                    found_words = [word for word in forbidden_words if word in text]
                    
                    if found_words:
                        errors.append(
                            f"角色 '{name}' 具有 '{trait}' 的特征，但检测到了不符合性格的动作描写："
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

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

class DraftValidatorPipeline:
    """
    统一的起草验证管道
    """
    def __init__(self):
        self.validators = [
            StyleClicheValidator(),
            CharacterOOCValidator(),
            PlotLogicValidator()
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
