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
CP3.2 局部缝合 + 证据驱动精修 smoke test（独立运行，不依赖 pytest）。

覆盖：
A. 局部缝合（stitch_chunks 默认路径）：
   - full_stitch=False（默认）走局部接缝重写
   - 接缝窗口正确切分（前后各 ~200 字）
   - max_tokens 显著降低（SEAM_MAX_TOKENS=1200 vs 全文 15000+）
   - 调用次数 = N-1（接缝数）
   - full_stitch=True 保留全文统稿（高档位）
   - 单 chunk 短路（直接返回）
   - 空接缝 LLM 输出兜底（原始拼接）
   - LLM 异常降级（不阻断）

B. 证据驱动精修（refine_single_beat）：
   - evidence_findings 注入 prompt（quote/detail/suggestion）
   - blocker 级证据触发第 2 轮收敛
   - max_iterations=1 不跑第 2 轮
   - 无 evidence_findings 保持原行为（向后兼容）
"""

import asyncio
import sys
from typing import List


# ============================================================
# 测试辅助：mock call_llm 与 call_llm_with_usage
# ============================================================

def install_llm_mocks():
    """替换所有消费方的 call_llm / call_llm_with_usage 为 mock。

    关键：stitching.py / refining.py 用 `from ... import call_llm` 绑定了
    自己模块命名空间的引用，必须 patch 消费方模块的符号才生效。

    返回 (mock_state, restore_fn)。
    """
    import backend.services.llm as llm_mod
    import backend.services.workflows.stitching as stitch_mod
    import backend.services.workflows.refining as refine_mod

    call_log: List[dict] = []
    responses: List[str] = []
    exceptions: List[Exception] = []

    async def mock_call_llm(system_prompt, user_prompt, **kwargs):
        call_log.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "max_tokens": kwargs.get("max_tokens"),
            "temperature": kwargs.get("temperature"),
        })
        # 优先消费 responses（按序），耗尽后再看 exceptions
        if responses:
            return responses.pop(0)
        if exceptions:
            exc = exceptions.pop(0)
            raise exc
        return "[MOCK DEFAULT OUTPUT]"

    class _MockResult:
        def __init__(self, content):
            self.content = content
            self.usage = {"prompt_tokens": 100, "completion_tokens": 50, "reasoning_tokens": 0}
            self.model_name = "mock"
            self.latency_ms = 10

    async def mock_call_llm_with_usage(system_prompt, user_prompt, **kwargs):
        call_log.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "max_tokens": kwargs.get("max_tokens"),
            "temperature": kwargs.get("temperature"),
        })
        if responses:
            return _MockResult(responses.pop(0))
        if exceptions:
            exc = exceptions.pop(0)
            raise exc
        return _MockResult("[MOCK DEFAULT OUTPUT]")

    # 备份原始符号（三个模块）
    originals = {
        "llm.call_llm": llm_mod.call_llm,
        "llm.call_llm_with_usage": llm_mod.call_llm_with_usage,
        "stitch.call_llm": stitch_mod.call_llm,
        "stitch.call_llm_with_usage": stitch_mod.call_llm_with_usage,
        "refine.call_llm": refine_mod.call_llm,
        "refine.call_llm_with_usage": refine_mod.call_llm_with_usage,
    }

    # patch 源模块 + 两个消费方模块
    llm_mod.call_llm = mock_call_llm
    llm_mod.call_llm_with_usage = mock_call_llm_with_usage
    stitch_mod.call_llm = mock_call_llm
    stitch_mod.call_llm_with_usage = mock_call_llm_with_usage
    refine_mod.call_llm = mock_call_llm
    refine_mod.call_llm_with_usage = mock_call_llm_with_usage

    def restore():
        llm_mod.call_llm = originals["llm.call_llm"]
        llm_mod.call_llm_with_usage = originals["llm.call_llm_with_usage"]
        stitch_mod.call_llm = originals["stitch.call_llm"]
        stitch_mod.call_llm_with_usage = originals["stitch.call_llm_with_usage"]
        refine_mod.call_llm = originals["refine.call_llm"]
        refine_mod.call_llm_with_usage = originals["refine.call_llm_with_usage"]

    mock_state = {
        "call_log": call_log,
        "responses": responses,        # 闭包捕获的同一 list；测试方用 .extend/.append 原地修改
        "exceptions": exceptions,      # 同上
        # 便捷 setter：原地替换（避免 reassign 新 list 导致闭包失效）
        "set_responses": lambda new: (responses.clear(), responses.extend(new)),
        "set_exceptions": lambda new: (exceptions.clear(), exceptions.extend(new)),
    }
    return mock_state, restore


def make_chapter():
    """构造一个最小 Chapter mock（含 stitching/refining 所需字段）。"""
    class _Chapter:
        def __init__(self):
            self.id = "test-chapter-id"
            self.chapter_name = "测试章节"
            self.chapter_number = 1
            self.outline_text = "测试大纲"
            self.content_text = None
            self.draft_text = None
            self.generation_run_id = "run-test"
    return _Chapter()


def make_book():
    class _Book:
        def __init__(self):
            self.id = "test-book-id"
            self.global_sys_prompt = "你是小说写作助手。"
            self.style_blacklist = []
            self.core_motifs_taboos = ""
    return _Book()


async def main() -> int:
    from backend.services.workflows.stitching import (
        stitch_chunks, SEAM_WINDOW_CHARS, SEAM_MAX_TOKENS,
    )
    from backend.services.workflows.refining import refine_single_beat
    from backend.services.prompts import build_local_seam_prompt

    failures: List[str] = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            failures.append(msg)

    # ============================================================
    # A. 局部缝合
    # ============================================================
    print("=== A1. 局部缝合：默认 full_stitch=False 走接缝重写 ===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        # 构造 3 个 chunk，每个 600 字
        chunk1 = "甲" * 600
        chunk2 = "乙" * 600
        chunk3 = "丙" * 600
        chunks = [chunk1, chunk2, chunk3]
        beats = [
            {"summary": "节拍1", "beat_id": "b1"},
            {"summary": "节拍2", "beat_id": "b2"},
            {"summary": "节拍3", "beat_id": "b3"},
        ]

        result = await stitch_chunks(
            chapter=chapter, beats=beats, chunks=chunks, word_count=1800,
        )
        # 3 chunks → 2 接缝 → 2 次 LLM 调用
        check(len(mock_state["call_log"]) == 2,
              f"3 chunks 触发 2 次接缝 LLM 调用（实际 {len(mock_state['call_log'])}）")
        # max_tokens 应为 SEAM_MAX_TOKENS（1200），远低于全文 15000+
        if mock_state["call_log"]:
            mt = mock_state["call_log"][0]["max_tokens"]
            check(mt == SEAM_MAX_TOKENS,
                  f"接缝 max_tokens = SEAM_MAX_TOKENS={SEAM_MAX_TOKENS}（实际 {mt}）")
            check(mt < 3000,
                  f"max_tokens 显著降低（< 3000，实际 {mt}）")
        # 结果非空
        check(bool(result), "局部缝合结果非空")
        # 结果应包含各 chunk 的主体（去窗口后的部分）
        check("甲" in result, "结果保留 chunk1 主体")
        check("乙" in result, "结果保留 chunk2 主体")
        check("丙" in result, "结果保留 chunk3 主体")
    finally:
        restore()

    print("\n=== A2. 单 chunk 短路 ===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        result = await stitch_chunks(
            chapter=chapter, beats=[{"summary": "b1"}],
            chunks=["唯一片段内容"], word_count=100,
        )
        check(len(mock_state["call_log"]) == 0, "单 chunk 不触发 LLM 调用")
        check(result == "唯一片段内容", "单 chunk 直接返回原文")
    finally:
        restore()

    print("\n=== A3. 空 chunks 短路 ===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        result = await stitch_chunks(
            chapter=chapter, beats=[], chunks=[], word_count=0,
        )
        check(len(mock_state["call_log"]) == 0, "空 chunks 不触发 LLM 调用")
        check(result == "", "空 chunks 返回空字符串")
    finally:
        restore()

    print("\n=== A4. 接缝 LLM 输出过短兜底（原始拼接）===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        # mock 返回极短输出（< SEAM_FALLBACK_MIN_TOKENS/2）
        mock_state["set_responses"](["x"])  # 1 字符
        result = await stitch_chunks(
            chapter=chapter,
            beats=[{"summary": "b1"}, {"summary": "b2"}],
            chunks=["前文内容" * 50, "后文内容" * 50],
            word_count=800,
        )
        # 兜底后接缝应为原始窗口拼接（含"前文"末尾 + "后文"开头）
        check("前文内容" in result, "兜底接缝保留左侧窗口")
        check("后文内容" in result, "兜底接缝保留右侧窗口")
    finally:
        restore()

    print("\n=== A5. 接缝 LLM 异常降级（不阻断）===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        mock_state["set_exceptions"]([RuntimeError("模拟 LLM 失败")])
        result = await stitch_chunks(
            chapter=chapter,
            beats=[{"summary": "b1"}, {"summary": "b2"}],
            chunks=["片段甲" * 100, "片段乙" * 100],
            word_count=1200,
        )
        # 异常降级后仍应有结果（原始拼接）
        check(bool(result), "接缝异常降级后仍有结果")
        check("片段甲" in result, "异常降级保留 chunk1")
        check("片段乙" in result, "异常降级保留 chunk2")
    finally:
        restore()

    print("\n=== A6. full_stitch=True 保留全文统稿（高档位）===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        big_chunks = ["内容" * 200, "内容" * 200, "内容" * 200]
        result = await stitch_chunks(
            chapter=chapter,
            beats=[{"summary": "b1"}, {"summary": "b2"}, {"summary": "b3"}],
            chunks=big_chunks,
            word_count=1800,
            full_stitch=True,  # 高档位
        )
        # 全文统稿只调用 1 次 LLM
        check(len(mock_state["call_log"]) == 1,
              f"full_stitch=True 触发 1 次全文 LLM 调用（实际 {len(mock_state['call_log'])}）")
        # max_tokens 应为全文公式（≥ 10000）
        if mock_state["call_log"]:
            mt = mock_state["call_log"][0]["max_tokens"]
            check(mt >= 10000,
                  f"全文统稿 max_tokens ≥ 10000（实际 {mt}，公式 max(10000, total*3)）")
    finally:
        restore()

    print("\n=== A7. build_local_seam_prompt 含黑名单 + POV + sketch ===")
    chapter = make_chapter()
    book = make_book()
    book.style_blacklist = ["与此同时", "视角回到"]
    sys_p, usr_p = build_local_seam_prompt(
        chapter=chapter,
        beats=[{"summary": "b1"}, {"summary": "b2"}],
        seam_index=0,
        total_seams=1,
        left_chunk_index=0,
        right_chunk_index=1,
        left_window="上文末尾",
        right_window="下文开头",
        anchor_pov="李雷",
        sketch_text="速写参考",
        book=book,
    )
    check("黑名单" in sys_p, "局部接缝 prompt 含黑名单段")
    check("与此同时" in sys_p, "黑名单词注入 prompt")
    check("视角收束" in sys_p, "POV 模式含视角收束约束")
    check("李雷" in sys_p, "POV 角色名注入")
    check("速写参考" in sys_p, "Sketch 参考注入")
    check("上文末尾" in usr_p, "user prompt 含左侧窗口")
    check("下文开头" in usr_p, "user prompt 含右侧窗口")
    check("接缝 1/1" in usr_p, "user prompt 含接缝序号")

    # ============================================================
    # B. 证据驱动精修
    # ============================================================
    print("\n=== B1. evidence_findings 注入精修 prompt ===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        book = make_book()
        beat = {
            "summary": "节拍摘要",
            "pov_character": "李雷",
            "entry_state": "入场状态",
            "exit_state": "退场状态",
            "red_lines": [],
        }
        evidence = [
            {
                "severity": "blocker",
                "category": "timeline",
                "quote": "昨夜大雨",
                "detail": "时间线矛盾：与上章时间不符",
                "suggestion": "改为清晨",
            },
            {
                "severity": "warning",
                "category": "style",
                "quote": "他笑了笑",
                "detail": "语气偏移",
                "suggestion": "改为冷笑",
            },
        ]
        result = await refine_single_beat(
            beat=beat,
            original_chunk="原文片段",
            revision_guide="全局修改计划",
            issue_descriptions=[],
            chapter=chapter,
            book=book,
            evidence_findings=evidence,
            max_iterations=1,  # 只跑第 1 轮（验证注入）
        )
        # 注入检查
        sys_p = mock_state["call_log"][0]["system_prompt"]
        check("证据驱动精修" in sys_p, "system prompt 含证据驱动段标题")
        check("原文引用：昨夜大雨" in sys_p, "quote 注入 prompt")
        check("时间线矛盾" in sys_p, "detail 注入 prompt")
        check("改为清晨" in sys_p, "suggestion 注入 prompt")
        check("[blocker|timeline]" in sys_p, "severity + category 标签注入")
        check("他笑了笑" in sys_p, "warning 级证据也注入")
    finally:
        restore()

    print("\n=== B2. blocker 证据 + max_iterations>=2 触发第 2 轮收敛 ===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        book = make_book()
        beat = {
            "summary": "节拍", "pov_character": "李雷",
            "entry_state": "", "exit_state": "", "red_lines": [],
        }
        evidence = [
            {
                "severity": "blocker",
                "category": "timeline",
                "quote": "昨夜",
                "detail": "时间矛盾",
                "suggestion": "改为清晨",
            },
        ]
        await refine_single_beat(
            beat=beat, original_chunk="原文", revision_guide="计划",
            issue_descriptions=[], chapter=chapter, book=book,
            evidence_findings=evidence,
            max_iterations=2,  # 允许第 2 轮
        )
        check(len(mock_state["call_log"]) == 2,
              f"blocker + max_iter=2 触发 2 轮 LLM 调用（实际 {len(mock_state['call_log'])}）")
        # 第 2 轮 system prompt 应含"第 2 轮加强修复"
        if len(mock_state["call_log"]) >= 2:
            second_sys = mock_state["call_log"][1]["system_prompt"]
            check("第 2 轮加强修复" in second_sys, "第 2 轮 system prompt 含加强修复标题")
            check("blocker 级证据" in second_sys, "第 2 轮重申 blocker 证据")
    finally:
        restore()

    print("\n=== B3. max_iterations=1 不跑第 2 轮（即使有 blocker）===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        book = make_book()
        beat = {"summary": "节拍", "pov_character": "", "entry_state": "", "exit_state": "", "red_lines": []}
        evidence = [
            {"severity": "blocker", "category": "timeline", "quote": "x", "detail": "y", "suggestion": "z"},
        ]
        await refine_single_beat(
            beat=beat, original_chunk="原文", revision_guide="",
            issue_descriptions=[], chapter=chapter, book=book,
            evidence_findings=evidence,
            max_iterations=1,  # 只 1 轮
        )
        check(len(mock_state["call_log"]) == 1,
              f"max_iterations=1 只调用 1 次（实际 {len(mock_state['call_log'])}）")
    finally:
        restore()

    print("\n=== B4. 无 evidence_findings 保持原行为（向后兼容）===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        book = make_book()
        beat = {"summary": "节拍", "pov_character": "", "entry_state": "", "exit_state": "", "red_lines": []}
        await refine_single_beat(
            beat=beat, original_chunk="原文", revision_guide="计划",
            issue_descriptions=["问题描述"], chapter=chapter, book=book,
            # evidence_findings 不传
        )
        check(len(mock_state["call_log"]) == 1, "无 evidence_findings 只调用 1 次（原行为）")
        sys_p = mock_state["call_log"][0]["system_prompt"]
        check("证据驱动精修" not in sys_p, "无 evidence_findings 时不注入证据段")
        check("问题描述" in sys_p, "issue_descriptions 仍正常注入（兼容）")
    finally:
        restore()

    print("\n=== B5. 第 2 轮异常降级（保留第 1 轮产出）===")
    mock_state, restore = install_llm_mocks()
    try:
        chapter = make_chapter()
        book = make_book()
        beat = {"summary": "节拍", "pov_character": "", "entry_state": "", "exit_state": "", "red_lines": []}
        evidence = [
            {"severity": "blocker", "category": "x", "quote": "q", "detail": "d", "suggestion": "s"},
        ]
        # 第 1 轮正常返回，第 2 轮抛异常
        mock_state["set_responses"](["第 1 轮产出"])
        mock_state["set_exceptions"]([RuntimeError("第 2 轮失败")])
        result = await refine_single_beat(
            beat=beat, original_chunk="原文", revision_guide="",
            issue_descriptions=[], chapter=chapter, book=book,
            evidence_findings=evidence, max_iterations=2,
        )
        check(result == "第 1 轮产出", "第 2 轮异常降级后保留第 1 轮产出")
    finally:
        restore()

    # ============================================================
    # 总结
    # ============================================================
    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CP3.2 SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
