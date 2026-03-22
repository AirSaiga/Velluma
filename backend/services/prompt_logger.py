import logging

"""
Prompt 日志记录模块。

职责：记录章节生成流程中每个阶段的 Prompt 和关键参数
"""

import json

# 配置模块级日志记录器
logger = logging.getLogger(__name__)
import os
import time
from datetime import datetime
from typing import Any, Optional
from pathlib import Path


class PromptLogger:
    """
    Prompt 日志记录器
    
    设计意图：
    - 完整记录章节生成流程中每个阶段的 Prompt 和关键参数
    - 便于调试、审计和分析生成质量
    - 支持结构化日志输出
    
    日志文件命名格式：prompt_log_{timestamp}_{chapter_id}.json
    """
    
    def __init__(self, chapter_id: str, book_id: Optional[str] = None, log_dir: str = "logs"):
        """
        初始化日志记录器
        
        Args:
            chapter_id: 章节 ID
            book_id: 书籍 ID（可选）
            log_dir: 日志目录，默认为项目根目录下的 logs
        """
        self.chapter_id = str(chapter_id) if chapter_id else "unknown"
        self.book_id = str(book_id) if book_id else None
        self.start_time = time.time()
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 确保日志目录存在
        # 从项目根目录开始查找
        project_root = self._find_project_root()
        self.log_dir = Path(project_root) / log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化日志数据结构
        self.log_data = {
            "metadata": {
                "chapter_id": self.chapter_id,
                "book_id": self.book_id,
                "start_timestamp": self.timestamp,
                "start_iso": datetime.now().isoformat(),
            },
            "context": {},  # 初始上下文信息
            "stages": [],   # 各阶段记录
            "summary": {}   # 最终统计
        }
        
        # 当前阶段索引（用于更新）
        self._current_stage_idx = -1
    
    def _find_project_root(self) -> str:
        """查找项目根目录（包含 backend 目录的父目录）"""
        current = Path(__file__).resolve()
        # 向上查找直到找到 backend 的父目录
        for parent in current.parents:
            if (parent / "backend").exists():
                return str(parent)
        # 如果没找到，使用当前文件所在目录的祖父目录
        return str(current.parent.parent)
    
    def set_context(self, 
                    chapter_info: dict,
                    book_info: Optional[dict] = None,
                    entities: Optional[list] = None,
                    relationships: Optional[list] = None,
                    request_params: Optional[dict] = None):
        """
        设置初始上下文信息
        
        Args:
            chapter_info: 章节信息（id, title, outline, chapter_number等）
            book_info: 书籍信息（id, title, genre等）
            entities: 角色实体列表
            relationships: 角色关系列表
            request_params: 请求参数（model, word_count等）
        """
        self.log_data["context"] = {
            "chapter": chapter_info,
            "book": book_info,
            "entities": self._sanitize_entities(entities) if entities else [],
            "relationships": self._sanitize_relationships(relationships) if relationships else [],
            "request_params": self._sanitize_request_params(request_params) if request_params else {}
        }
    
    def _sanitize_entities(self, entities: list) -> list:
        """清理角色实体信息，保留关键字段"""
        sanitized = []
        seen_ids = set()  # 去重
        
        for e in entities:
            char = None
            char_id = None
            
            # 处理 ChapterEntity 对象（通过 .character 属性访问）
            if hasattr(e, 'character') and e.character:
                char = e.character
                char_id = str(getattr(char, 'id', 'unknown'))
            # 处理直接的 Character 对象
            elif hasattr(e, 'id') and hasattr(e, 'name'):
                char = e
                char_id = str(getattr(e, 'id', 'unknown'))
            # 处理 dict 类型
            elif isinstance(e, dict):
                # 检查是否有嵌套的 character 字段
                if 'character' in e and e['character']:
                    char = e['character']
                    char_id = str(getattr(char, 'id', e.get('id', 'unknown')))
                else:
                    char = e
                    char_id = str(e.get('id', 'unknown'))
            
            # 去重检查
            if char_id and char_id in seen_ids:
                continue
            seen_ids.add(char_id)
            
            # 提取角色信息
            if char:
                # 注意：getattr 可能返回空字符串，空字符串是 falsy，需要显式检查
                name = getattr(char, 'name', None)
                if not name:  # 同时处理 None 和空字符串
                    name = e.get('name', 'Unknown') if isinstance(e, dict) else 'Unknown'
                importance = getattr(char, 'importance_level', 1)
                static_prompt = getattr(char, 'static_prompt', '') or ''
                
                sanitized.append({
                    "id": char_id,
                    "name": name,
                    "importance_level": importance,
                    "static_prompt_preview": self._truncate(static_prompt, 200)
                })
        
        return sanitized
    
    def _sanitize_relationships(self, relationships: list) -> list:
        """清理关系信息，保留关键字段"""
        sanitized = []
        for r in relationships:
            source_name = ""
            target_name = ""
            
            # 提取源角色名称
            if hasattr(r, 'source_character') and r.source_character:
                source_name = getattr(r.source_character, 'name', 'Unknown')
            # 处理 dict 类型
            elif isinstance(r, dict) and 'source_character' in r:
                sc = r['source_character']
                source_name = getattr(sc, 'name', 'Unknown') if hasattr(sc, 'name') else str(sc)
            
            # 提取目标角色名称
            if hasattr(r, 'target_character') and r.target_character:
                target_name = getattr(r.target_character, 'name', 'Unknown')
            # 处理 dict 类型
            elif isinstance(r, dict) and 'target_character' in r:
                tc = r['target_character']
                target_name = getattr(tc, 'name', 'Unknown') if hasattr(tc, 'name') else str(tc)
            
            # 提取其他字段
            if isinstance(r, dict):
                rel_type = r.get('relation_type', 'unknown')
                affinity = r.get('affinity_score', 0)
                interaction = r.get('interaction_prompt', '')
            else:
                rel_type = getattr(r, 'relation_type', 'unknown')
                affinity = getattr(r, 'affinity_score', 0)
                interaction = getattr(r, 'interaction_prompt', '')
            
            # 只添加有效的关系（有角色名称的）
            if source_name and target_name:
                sanitized.append({
                    "source": source_name,
                    "target": target_name,
                    "relation_type": rel_type,
                    "affinity_score": affinity,
                    "interaction_prompt_preview": self._truncate(interaction, 100)
                })
        
        return sanitized
    
    def _sanitize_request_params(self, params: dict) -> dict:
        """清理请求参数，移除敏感信息"""
        safe_params = dict(params)
        # 移除 API key 等敏感信息
        if 'api_key' in safe_params:
            safe_params['api_key'] = '***REDACTED***'
        return safe_params
    
    def _truncate(self, text: str, max_len: int) -> str:
        """截断文本"""
        if not text:
            return ""
        return text[:max_len] + "..." if len(text) > max_len else text
    
    def start_stage(self, 
                    stage_name: str, 
                    iteration: int = 1,
                    beat_index: Optional[int] = None,
                    beat_id: Optional[str] = None):
        """
        开始记录一个新阶段
        
        Args:
            stage_name: 阶段名称（PLANNING/DRAFTING/REVIEWING等）
            iteration: 迭代轮次
            beat_index: Beat 索引（如果是 Beat 级别的阶段）
            beat_id: Beat ID
        """
        stage_record = {
            "stage": stage_name,
            "iteration": iteration,
            "beat_index": beat_index,
            "beat_id": beat_id,
            "start_time": time.time(),
            "inputs": {},      # 输入参数
            "prompts": [],     # Prompt 内容列表（支持多个prompts）
            "outputs": {},     # 输出结果
            "metrics": {}      # 性能指标
        }
        self.log_data["stages"].append(stage_record)
        self._current_stage_idx = len(self.log_data["stages"]) - 1
        return self._current_stage_idx
    
    def log_inputs(self, **kwargs):
        """记录阶段输入参数"""
        if self._current_stage_idx < 0:
            return
        
        # 清理输入参数，移除大文本字段
        sanitized = {}
        for key, value in kwargs.items():
            if isinstance(value, str) and len(value) > 500:
                sanitized[key] = self._truncate(value, 500)
            else:
                sanitized[key] = value
        
        self.log_data["stages"][self._current_stage_idx]["inputs"].update(sanitized)
    
    def log_prompts(self, 
                    system_prompt: str, 
                    user_prompt: str,
                    model: Optional[str] = None,
                    temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None,
                    prompt_label: Optional[str] = None):
        """
        记录 Prompt 内容（支持同一阶段的多个 prompts）
        
        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            model: 使用的模型
            temperature: 温度参数
            max_tokens: 最大 token 数
            prompt_label: Prompt 标签（如 "SCENE_INTENT", "SUBCONSCIOUS", "PROSE" 等）
        """
        if self._current_stage_idx < 0:
            return
        
        prompt_record = {
            "label": prompt_label,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "system_prompt_length": len(system_prompt),
            "user_prompt_length": len(user_prompt),
            "total_prompt_length": len(system_prompt) + len(user_prompt),
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        self.log_data["stages"][self._current_stage_idx]["prompts"].append(prompt_record)
    
    def log_outputs(self, **kwargs):
        """记录阶段输出结果"""
        if self._current_stage_idx < 0:
            return
        
        # 清理输出结果
        sanitized = {}
        for key, value in kwargs.items():
            if isinstance(value, str):
                sanitized[key] = self._truncate(value, 1000)
            else:
                sanitized[key] = value
        
        self.log_data["stages"][self._current_stage_idx]["outputs"].update(sanitized)
    
    def log_metrics(self, 
                    elapsed_time: Optional[float] = None,
                    tokens_used: Optional[int] = None,
                    success: bool = True,
                    **kwargs):
        """记录性能指标"""
        if self._current_stage_idx < 0:
            return
        
        metrics = {
            "success": success,
            **kwargs
        }
        
        if elapsed_time is not None:
            metrics["elapsed_time_seconds"] = round(elapsed_time, 3)
        if tokens_used is not None:
            metrics["tokens_used"] = tokens_used
        
        self.log_data["stages"][self._current_stage_idx]["metrics"].update(metrics)
    
    def end_stage(self, success: bool = True):
        """结束当前阶段记录"""
        if self._current_stage_idx < 0:
            return
        
        stage = self.log_data["stages"][self._current_stage_idx]
        stage["end_time"] = time.time()
        stage["success"] = success
        
        # 计算耗时
        if "start_time" in stage:
            elapsed = stage["end_time"] - stage["start_time"]
            stage["metrics"]["elapsed_time_seconds"] = round(elapsed, 3)
    
    def finalize(self, 
                 final_text_length: int = 0,
                 total_iterations: int = 1,
                 review_passed: bool = False):
        """
        完成日志记录，保存到文件
        
        Args:
            final_text_length: 最终文本长度
            total_iterations: 总迭代次数
            review_passed: 审阅是否通过
        """
        end_time = time.time()
        total_elapsed = end_time - self.start_time
        
        self.log_data["summary"] = {
            "total_stages": len(self.log_data["stages"]),
            "total_iterations": total_iterations,
            "review_passed": review_passed,
            "final_text_length": final_text_length,
            "total_elapsed_seconds": round(total_elapsed, 3),
            "end_timestamp": datetime.now().isoformat()
        }
        
        # 计算各阶段统计
        stage_stats = {}
        for stage in self.log_data["stages"]:
            stage_name = stage["stage"]
            if stage_name not in stage_stats:
                stage_stats[stage_name] = {
                    "count": 0,
                    "total_time": 0,
                    "success_count": 0
                }
            stage_stats[stage_name]["count"] += 1
            stage_stats[stage_name]["total_time"] += stage.get("metrics", {}).get("elapsed_time_seconds", 0)
            if stage.get("success", False):
                stage_stats[stage_name]["success_count"] += 1
        
        self.log_data["summary"]["stage_statistics"] = stage_stats
        
        # 保存到文件
        self._save_log()
    
    def _save_log(self):
        """保存日志到文件"""
        filename = f"prompt_log_{self.timestamp}_{self.chapter_id[:8]}.json"
        filepath = self.log_dir / filename
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.log_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[PromptLogger] Log saved to: {filepath}")
        except Exception as e:
            logger.error(f"[PromptLogger] Failed to save log: {e}")
    
    def get_debug_history(self) -> list:
        """
        获取调试历史记录（兼容原有 debug_history 格式）
        
        Returns:
            list: 调试历史记录列表
        """
        debug_history = []
        for stage in self.log_data["stages"]:
            entry = {
                "stage": stage["stage"],
                "iteration": stage.get("iteration", 1)
            }
            
            # 添加 prompts
            prompts = stage.get("prompts", {})
            if prompts:
                entry["system_prompt"] = prompts.get("system_prompt", "")
                entry["user_prompt"] = prompts.get("user_prompt", "")
            
            # 添加 beat 信息
            if stage.get("beat_index"):
                entry["beat_index"] = stage["beat_index"]
            if stage.get("beat_id"):
                entry["beat_id"] = stage["beat_id"]
            
            debug_history.append(entry)
        
        return debug_history


# 全局日志记录器实例（用于当前请求）
_current_logger: Optional[PromptLogger] = None


def create_logger(chapter_id: str, book_id: Optional[str] = None) -> PromptLogger:
    """创建新的日志记录器"""
    global _current_logger
    _current_logger = PromptLogger(chapter_id, book_id)
    return _current_logger


def get_logger() -> Optional[PromptLogger]:
    """获取当前日志记录器"""
    return _current_logger


def clear_logger():
    """清除当前日志记录器"""
    global _current_logger
    _current_logger = None
