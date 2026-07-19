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
观测层（Observability）模块。

职责：
- 记录单次 LLM 调用到 generation_runs 表（RunRecorder）
- 提供 degraded 事件的轻量记录接口（record_degraded）
- 为 Phase 0 T1（usage 采集）与 T5（降级显式化）提供物理载体

业务场景：
- 生成主链路各阶段（planning/drafting/stitching/reviewing/refining/publish.*）
  通过 RunRecorder 包装 call_llm_with_usage，自动落库调用计量
- 降级点（Sketch 解析失败、校对异常等）通过 record_degraded 写入 degraded 字段
"""
