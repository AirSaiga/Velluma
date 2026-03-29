"""
记忆评分服务。

职责：提供记忆检索的评分计算逻辑，与数据访问层解耦。

主要功能：
- 计算记忆综合评分（语义相似度 + 时间衰减 + 伏笔权重）
- 时间衰减计算

使用场景：
- repositories/memory_repository.py: 搜索相关记忆时使用
"""

import math
from datetime import datetime, timezone


def compute_memory_score(
    cosine_similarity: float,
    delta_days: float,
    plot_weight: float,
    alpha: float = 0.6,
    beta: float = 0.2,
    gamma: float = 0.2,
    lambda_decay: float = 0.1,
) -> float:
    """
    计算记忆综合评分。

    评分公式：score = α * cosine_similarity + β * time_score + γ * plot_weight

    其中：
    - cosine_similarity: 向量余弦相似度 (0-1)
    - time_score: 时间衰减得分 = exp(-λ * delta_days)
    - plot_weight: 伏笔权重 (0-1)，有未解决伏笔时为1，否则为0

    Args:
        cosine_similarity: 余弦相似度
        delta_days: 距离当前的天数
        plot_weight: 伏笔权重
        alpha: 语义相似度权重
        beta: 时间衰减权重
        gamma: 伏笔权重
        lambda_decay: 时间衰减系数

    Returns:
        float: 综合评分 (0-1)
    """
    safe_cosine = max(0.0, min(1.0, cosine_similarity))
    safe_delta_days = max(0.0, delta_days)
    safe_plot_weight = max(0.0, min(1.0, plot_weight))
    time_score = math.exp(-lambda_decay * safe_delta_days)
    return alpha * safe_cosine + beta * time_score + gamma * safe_plot_weight


def calculate_time_decay_score(
    created_at: datetime,
    lambda_decay: float = 0.1,
    now: datetime = None,
) -> float:
    """
    计算时间衰减得分。

    Args:
        created_at: 记忆创建时间
        lambda_decay: 衰减系数
        now: 当前时间，默认为 datetime.now(timezone.utc)

    Returns:
        float: 时间衰减得分 (0-1)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    delta_days = (now - created_at).total_seconds() / 86400
    return math.exp(-lambda_decay * max(0.0, delta_days))
