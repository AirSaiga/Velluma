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
CP3.4 SSE 实时化 + 前端质量报告 smoke test（独立运行）。

覆盖：
A. StreamEventBuilder 新增事件（AUDIT_START / AUDIT_DONE / DEGRADED）
   - SSE 格式正确（data: {json}\\n\\n）
   - 字段完整（event / message / verdict / findings_count / degraded / stage / reason / action）
B. _process_result 集成（导入路径可达 + 路由数不变）
C. 端到端事件契约（前端可解析的字段都在）
"""

import asyncio
import json
import sys
from typing import List


async def main() -> int:
    from backend.routes.chapter_generation.progress_tracker import StreamEventBuilder

    failures: List[str] = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            failures.append(msg)

    def parse_sse(s: str) -> dict:
        """解析 SSE data: {...}\\n\\n 为 dict。"""
        assert s.startswith("data: "), f"SSE 必须以 'data: ' 开头，实际: {s[:20]}"
        assert s.endswith("\n\n"), f"SSE 必须以 '\\n\\n' 结尾，实际: {repr(s[-4:])}"
        return json.loads(s[len("data: "):].strip())

    print("=== A1. AUDIT_START 事件 ===")
    evt = parse_sse(StreamEventBuilder.build_audit_start())
    check(evt["event"] == "AUDIT_START", "event=AUDIT_START")
    check("message" in evt, "含 message 字段")

    print("\n=== A2. AUDIT_DONE 事件（含 verdict / findings_count / degraded）===")
    evt = parse_sse(StreamEventBuilder.build_audit_done(
        verdict="pass_with_fixes", findings_count=3, degraded=False,
    ))
    check(evt["event"] == "AUDIT_DONE", "event=AUDIT_DONE")
    check(evt["verdict"] == "pass_with_fixes", "verdict 字段正确")
    check(evt["findings_count"] == 3, "findings_count 字段正确")
    check(evt["degraded"] is False, "degraded 字段正确")

    # degraded=None 时不包含该字段
    evt2 = parse_sse(StreamEventBuilder.build_audit_done(
        verdict="pass", findings_count=0,
    ))
    check("degraded" not in evt2, "degraded=None 时字段省略")

    print("\n=== A3. DEGRADED 事件（含 stage / reason / action / detail）===")
    evt = parse_sse(StreamEventBuilder.build_degraded(
        stage="audit", reason="llm_parse_failed",
        action="mark_unaudited", detail="timeout after 30s",
    ))
    check(evt["event"] == "DEGRADED", "event=DEGRADED")
    check(evt["stage"] == "audit", "stage 字段正确")
    check(evt["reason"] == "llm_parse_failed", "reason 字段正确")
    check(evt["action"] == "mark_unaudited", "action 字段正确")
    check(evt["detail"] == "timeout after 30s", "detail 字段正确")

    # detail 省略
    evt2 = parse_sse(StreamEventBuilder.build_degraded(
        stage="stitching", reason="seam_failed", action="fallback",
    ))
    check("detail" not in evt2, "detail 省略时字段不存在")

    # detail 截断
    long_detail = "x" * 500
    evt3 = parse_sse(StreamEventBuilder.build_degraded(
        stage="x", reason="y", action="z", detail=long_detail,
    ))
    check(len(evt3["detail"]) <= 200, f"detail 截断到 ≤200 字符（实际 {len(evt3['detail'])}）")

    print("\n=== B1. _process_result 导入路径可达（_execute_dual_layer_audit）===")
    # 验证 stream_handler 能 import _execute_dual_layer_audit
    from backend.routes.chapter_generation import _execute_dual_layer_audit
    check(callable(_execute_dual_layer_audit), "_execute_dual_layer_audit 可调用")

    # 验证 stream_handler 模块本身能 import（含新增的 audit 步骤代码）
    import backend.routes.chapter_generation.stream_handler as sh_mod
    check(hasattr(sh_mod, "DualTrackStreamHandler"), "DualTrackStreamHandler 可导入")

    print("\n=== B2. 路由数不变（CP3.4 不增路由，仍是 88）===")
    import backend.main  # noqa
    from backend.main import app
    routes = [r for r in app.routes if hasattr(r, "methods")]
    api_count = sum(1 for r in routes for m in (r.methods or set()) if m in ("GET", "POST", "PUT", "DELETE", "PATCH"))
    # CP4.5 完整下线后路由数为 86（删除 -simple + preview-beats；generate-dual-track 重命名为 generate-chapter）
    check(api_count == 86, f"路由数 = {api_count}（CP4.5 完整下线后应为 86）")

    print("\n=== C1. 事件契约前端可解析（字段类型一致）===")
    # 模拟前端 useChapterGenerator 的事件分发
    for builder_fn, expected_event in [
        (StreamEventBuilder.build_audit_start, "AUDIT_START"),
        (lambda: StreamEventBuilder.build_audit_done(verdict="fail", findings_count=2, degraded=True), "AUDIT_DONE"),
        (lambda: StreamEventBuilder.build_degraded(stage="s", reason="r", action="a"), "DEGRADED"),
    ]:
        evt = parse_sse(builder_fn())
        check(evt["event"] == expected_event, f"前端可识别 {expected_event}")
        check("message" in evt, f"{expected_event} 含 message 字段（前端展示用）")

    # AUDIT_DONE 必须有 verdict + findings_count（前端徽章依赖）
    evt = parse_sse(StreamEventBuilder.build_audit_done(verdict="pass", findings_count=0))
    check(isinstance(evt["verdict"], str), "verdict 是 string")
    check(isinstance(evt["findings_count"], int), "findings_count 是 int")

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CP3.4 SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
