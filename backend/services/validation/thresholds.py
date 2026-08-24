"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
校验阈值常量集中定义（Phase 3 CP4.3 新建）。

职责：集中放置代码级审计（CP3.1b）使用的阈值常量，便于统一调参与 A/B 校准。

业务场景：
- RhythmAuditor 读取 CV_THRESHOLD_LO / CV_THRESHOLD_HI 判定句长节奏是否健康
- 后续 Auditor 新增阈值也放此处（如 DialogueAuditor 的题材区间）

标定依据（decisions §4.2 + 蓝图 §4.8.1）：
- 初版用中文网文经验值 + RhythmAuditor docstring 锚点（<0.3 单调 / >0.7 多变）
- Phase 3 CP4.6 A/B 验收时按真实 QualityReport.metrics 数据校准
- 阈值是软指标（题材相关），不升级为 blocker（blocker 由 LLM 审计产出）
"""

# ============================================================
# 句长 CV（变异系数）健康区间（蓝图 §4.2 + decisions §4.2）
# ============================================================
# CV = stddev / mean，衡量句长分布的多样性
# - CV < LO：句长过于单调（AI 默认分布常见，等长句子堆叠）
# - CV ∈ [LO, HI]：健康区间（节奏有变化）
# - CV > HI：节奏多变（通常无问题，可能是诗意/意识流风格）
#
# 初版经验值（Phase 3 CP4.3）：
# - LO=0.35：低于此值触发 warning finding（影响 verdict，但不阻断）
# - HI=0.80：高于此值不发 finding（健康）
# - 中间区间 [0.35, 0.80]：健康，不发 finding
#
# 标定计划：CP4.6 A/B 时从 quality_reports.metrics 聚合真实 CV 分布，
#           按优质章节的 CV 中位数 ± 0.1 标定最终值。

CV_THRESHOLD_LO: float = 0.35
CV_THRESHOLD_HI: float = 0.80


# ============================================================
# 连续同长句阈值（RhythmAuditor 子指标）
# ============================================================
# 相邻句子长度差 ≤ 2 字符的连续段长度上限
# 超过此值 → 节奏单调 finding（info 级，CP3.1b 已实现）

CONSECUTIVE_SAME_LEN_THRESHOLD: int = 6


# ============================================================
# 段末升华腔命中阈值（RhythmAuditor 子指标）
# ============================================================
# 升华腔模式（如"命运的齿轮""这一刻"）命中次数 ≥ 此值 → finding

SUBLIMATION_HITS_THRESHOLD: int = 2


# ============================================================
# 词级 bigram 重复密度高阈（文风漂移轻提示用）
# ============================================================
# fingerprint.repetition.bigram_repeat_ratio ≥ 此值 → 心跳漂移提示
# 「用词重复度偏高（疑似套路化表达）」。
# ⚠ 初值 0.15 为经验猜测，待实测校准（角色名等正当重复会抬高该值）；
# 仅软提示不进门禁（判断权在作者，见 fingerprint.compute_style_drift_hint）。

NGRAM_REPEAT_RATIO_HI: float = 0.15
