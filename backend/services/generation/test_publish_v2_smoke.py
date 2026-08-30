# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
CP3.3 状态回写强化 smoke test（独立运行，不依赖 pytest）。

覆盖：
A. extract_character_relevant_segments（修 P0-5：不再逐角色重发全文）
   - 角色名 + 别名匹配
   - 窗口合并（重叠区间）
   - max_segments 截断
   - 无匹配返回空

B. update_character_states_incremental（蓝图 §4.10 第 3 步）
   - 增量片段输入（不重发全文）
   - evidence_quote 注入
   - 无 evidence → 跳过入库（SCORE 原则）
   - 无相关片段 → skipped
   - LLM 异常降级

C. activate_plot_ledgers（decisions §3.5）
   - foreshadow_ops 关键词预筛
   - executed 需 evidence（无 evidence 降级 skipped）
   - LLM 异常 → 全部 skipped
   - 无 ops → 空返回

D. update_rolling_summary（蓝图 §4.10 第 2 步）
   - 合并旧摘要 + 本章摘要
   - 写回 Book.rolling_summary
   - 本章无摘要 → 跳过
   - LLM 异常 → 保留旧摘要
"""

import asyncio
import json
import sys
import uuid
from typing import List


def install_llm_mock():
    """patch publish_v2 模块的 call_llm。

    返回 (mock_state, restore)。mock_state 提供：
    - call_log: list
    - set_responses(list): 原地设置响应队列
    - set_exceptions(list): 原地设置异常队列
    """
    import backend.services.generation.publish_v2 as pv2_mod

    call_log: List[dict] = []
    responses: List[str] = []
    exceptions: List[Exception] = []

    async def mock_call_llm(system_prompt, user_prompt, **kwargs):
        call_log.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "max_tokens": kwargs.get("max_tokens"),
            "model_type": kwargs.get("model_type"),
        })
        if responses:
            return responses.pop(0)
        if exceptions:
            exc = exceptions.pop(0)
            raise exc
        return '{"new_dynamic_state": "默认状态", "evidence_quote": "默认证据"}'

    original = pv2_mod.call_llm
    pv2_mod.call_llm = mock_call_llm

    def restore():
        pv2_mod.call_llm = original

    return {
        "call_log": call_log,
        "set_responses": lambda new: (responses.clear(), responses.extend(new)),
        "set_exceptions": lambda new: (exceptions.clear(), exceptions.extend(new)),
    }, restore


# ============================================================
# Mock 对象
# ============================================================

class MockCharacter:
    def __init__(self, name, aliases=None, static_prompt="设定", dynamic_state="旧状态"):
        self.id = uuid.uuid4()
        self.name = name
        self.aliases = aliases or []
        self.static_prompt = static_prompt
        self.dynamic_state = dynamic_state
        self.dynamic_state_history = []


class MockCharRepo:
    """记录 commit_and_refresh 调用。"""
    def __init__(self):
        self.commits = []
    async def commit_and_refresh(self, character):
        self.commits.append(character.name)


class MockPlotLedger:
    def __init__(self, ledger_key, status="open"):
        self.id = uuid.uuid4()
        self.ledger_key = ledger_key
        self.status = status
        self.resolved_in_chapter_id = None
        self.meta = {}


class MockPlotLedgerRepo:
    """find_one 按 ledger_key 返回 mock 记录。"""
    def __init__(self, records):
        self.records = {r.ledger_key: r for r in records}
        self.committed = False
    async def find_one(self, *, conditions=None, **kwargs):
        # conditions 是 list，含 PlotLedger.ledger_key == X
        # 简化：从 conditions 提取 ledger_key 值
        target_key = None
        if conditions:
            for cond in conditions:
                # SQLAlchemy BinaryExpression，无法直接解；用 mock 简化
                try:
                    # cond.right.value 是值（SQLAlchemy 1.x/2.x 兼容尝试）
                    target_key = cond.right.value if hasattr(cond, 'right') else None
                except Exception:
                    pass
        return self.records.get(target_key)
    async def commit(self):
        self.committed = True


class MockBook:
    def __init__(self, rolling_summary=None):
        self.id = uuid.uuid4()
        self.rolling_summary = rolling_summary


class MockBookRepo:
    def __init__(self, book):
        self.book = book
        self.commits = 0
    async def get_by_id(self, book_id):
        return self.book
    async def commit_and_refresh(self, book):
        self.commits += 1


async def main() -> int:
    from backend.services.generation.publish_v2 import (
        extract_character_relevant_segments,
        update_character_states_incremental,
        activate_plot_ledgers,
        update_rolling_summary,
    )

    failures: List[str] = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            failures.append(msg)

    # ============================================================
    # A. extract_character_relevant_segments
    # ============================================================
    print("=== A1. 角色名 + 别名匹配 ===")
    text = "开头。" + ("A" * 100) + "。李雷走进房间。" + ("B" * 100) + "。韩梅梅跟进来。" + ("C" * 100) + "。小李笑了。" + ("D" * 100)
    seg = extract_character_relevant_segments(text, "李雷", aliases=["小李"], window_chars=100)
    check("李雷" in seg or "小李" in seg, "返回的片段含角色名或别名")
    check(len(seg) < len(text), f"片段短于全文（修 P0-5）：片段 {len(seg)} < 全文 {len(text)}")
    check("[...]" in seg or seg.count("李雷") + seg.count("小李") >= 1, "多窗口用 [...] 分隔或合并")

    print("\n=== A2. 无匹配返回空 ===")
    seg2 = extract_character_relevant_segments(text, "不存在角色", aliases=[], window_chars=100)
    check(seg2 == "", "无匹配返回空字符串")

    print("\n=== A3. max_segments 截断 ===")
    # 构造 20 次出现的角色
    long_text = "。".join(["李雷说话"] * 20) + "结尾"
    seg3 = extract_character_relevant_segments(long_text, "李雷", window_chars=60, max_segments=3)
    # 截断后片段数受限（[...] 分隔的段数 ≤ 3）
    segment_count = len([s for s in seg3.split("\n[...]\n") if s.strip()])
    check(segment_count <= 3, f"max_segments=3 截断（实际 {segment_count}）")

    # ============================================================
    # B. update_character_states_incremental
    # ============================================================
    print("\n=== B1. 增量片段输入（不重发全文）+ evidence_quote ===")
    mock_state, restore = install_llm_mock()
    try:
        char = MockCharacter(name="李雷", aliases=[], dynamic_state="旧状态")
        char_repo = MockCharRepo()
        # 构造长正文：角色只在中间出现 1 次，前后有大量无关内容（远超 window）
        # 全文约 5000 字，李雷在中段，window 默认 400 → 片段约 400 字（裁剪 92%）
        chapter_text = ("无关内容XYZ" * 200) + "李雷走进房间，看着窗外。" + ("无关内容XYZ" * 200)
        class _Ch:
            content_text = chapter_text; draft_text=None; title="t"; outline_text="o"; chapter_number=1
        results = await update_character_states_incremental(
            character_list=[char], chapter=_Ch(),
            character_repository=char_repo, chapter_text=chapter_text,
        )
        check(len(mock_state["call_log"]) == 1, "有相关片段 → 调用 1 次 LLM")
        # 核心断言：传给 LLM 的"角色相关片段"段（user_prompt 中【角色相关片段】之后的部分）
        # 显著短于全文（修 P0-5 的本质）
        sent_user = mock_state["call_log"][0]["user_prompt"]
        check("李雷" in sent_user, "user_prompt 含角色相关片段")
        # 验证无关内容被显著裁剪：全文 200 次"无关内容XYZ"在 prompt 中应远少于 200
        irrelevant_count = sent_user.count("无关内容XYZ")
        check(irrelevant_count < 200,
              f"无关内容被裁剪（全文 200 次 → prompt 中 {irrelevant_count} 次）")
        check(len(results) == 1, "返回 1 个结果")
        check(results[0].evidence_quote == "默认证据", "evidence_quote 注入")
        check(len(char_repo.commits) == 1, "有 evidence → 入库 commit")
    finally:
        restore()

    print("\n=== B2. 无 evidence → 跳过入库（SCORE 原则）===")
    mock_state, restore = install_llm_mock()
    try:
        char = MockCharacter(name="李雷", dynamic_state="旧状态")
        char_repo = MockCharRepo()
        mock_state["set_responses"]([json.dumps({"new_dynamic_state": "新状态", "evidence_quote": ""})])
        class _Ch2:
            content_text = "李雷来了"; draft_text=None; title="t"; outline_text="o"; chapter_number=1
        results = await update_character_states_incremental(
            character_list=[char], chapter=_Ch2(),
            character_repository=char_repo, chapter_text="李雷来了",
        )
        check(len(char_repo.commits) == 0, "无 evidence → 不入库（SCORE 原则）")
        check(results[0].skipped is True, "无 evidence 标记 skipped")
        check(results[0].new_state == "旧状态", "无 evidence 保留 old_state")
    finally:
        restore()

    print("\n=== B3. 无相关片段 → skipped（不浪费 LLM 调用）===")
    mock_state, restore = install_llm_mock()
    try:
        char = MockCharacter(name="不出现的角色", dynamic_state="旧状态")
        char_repo = MockCharRepo()
        class _Ch3:
            content_text = "李雷来了"; draft_text=None; title="t"; outline_text="o"; chapter_number=1
        results = await update_character_states_incremental(
            character_list=[char], chapter=_Ch3(),
            character_repository=char_repo, chapter_text="李雷来了",
        )
        check(len(mock_state["call_log"]) == 0, "无相关片段 → 不调用 LLM（节省 token）")
        check(results[0].skipped is True, "无相关片段标记 skipped")
        check(len(char_repo.commits) == 0, "无相关片段不入库")
    finally:
        restore()

    print("\n=== B4. LLM 异常降级 ===")
    mock_state, restore = install_llm_mock()
    try:
        char = MockCharacter(name="李雷", dynamic_state="旧状态")
        char_repo = MockCharRepo()
        mock_state["set_exceptions"]([RuntimeError("模拟 LLM 失败")])
        class _Ch4:
            content_text = "李雷来了"; draft_text=None; title="t"; outline_text="o"; chapter_number=1
        results = await update_character_states_incremental(
            character_list=[char], chapter=_Ch4(),
            character_repository=char_repo, chapter_text="李雷来了",
        )
        check(results[0].success is False, "LLM 异常 → success=False")
        check(results[0].new_state == "旧状态", "异常保留 old_state")
        check(len(char_repo.commits) == 0, "异常不入库")
    finally:
        restore()

    # ============================================================
    # C. activate_plot_ledgers
    # ============================================================
    print("\n=== C1. foreshadow_ops 关键词预筛 + executed 需 evidence ===")
    mock_state, restore = install_llm_mock()
    try:
        foreshadow_ops = [
            {"ledger_id": "hk-001", "action": "plant", "note": "渡口票据首次出现"},
            {"ledger_id": "hk-002", "action": "advance", "note": "古剑出鞘"},
        ]
        chapter_text = "渡口票据被风吹走。" + "无关" * 30 + "古剑出鞘，寒光闪闪。"
        # mock 返回 hk-001 executed with evidence, hk-002 executed without evidence
        mock_state["set_responses"]([json.dumps({
            "statuses": [
                {"ledger_id": "hk-001", "status": "executed", "evidence_quote": "渡口票据被风吹走", "note": "落地"},
                {"ledger_id": "hk-002", "status": "executed", "evidence_quote": "", "note": "无证据"},
            ]
        })])
        records = [MockPlotLedger("hk-001"), MockPlotLedger("hk-002")]
        repo = MockPlotLedgerRepo(records)
        statuses = await activate_plot_ledgers(
            foreshadow_ops=foreshadow_ops,
            chapter_text=chapter_text,
            plot_ledger_repository=repo,
            chapter_id=uuid.uuid4(),
            chapter_number=1,
        )
        check(len(statuses) == 2, "返回 2 个 status")
        check(statuses[0].status == "executed", "hk-001 executed（有 evidence）")
        check(statuses[0].evidence_quote == "渡口票据被风吹走", "hk-001 evidence 保留")
        # hk-002 executed 但无 evidence → 降级 skipped
        check(statuses[1].status == "skipped", "hk-002 无 evidence → 降级 skipped（SCORE）")
        # DB 更新：hk-001 → closed，hk-002 保留 open
        check(records[0].status == "closed", "hk-001 executed → PlotLedger.status=closed")
        check(records[1].status == "open", "hk-002 skipped → PlotLedger.status 保留 open")
    finally:
        restore()

    print("\n=== C2. LLM 异常 → 全部 skipped ===")
    mock_state, restore = install_llm_mock()
    try:
        foreshadow_ops = [{"ledger_id": "hk-001", "action": "plant", "note": "渡口票据"}]
        mock_state["set_exceptions"]([RuntimeError("LLM 失败")])
        repo = MockPlotLedgerRepo([MockPlotLedger("hk-001")])
        statuses = await activate_plot_ledgers(
            foreshadow_ops=foreshadow_ops,
            chapter_text="渡口票据。",
            plot_ledger_repository=repo,
            chapter_id=uuid.uuid4(),
            chapter_number=1,
        )
        check(len(statuses) == 1, "返回 1 个 status")
        check(statuses[0].status == "skipped", "LLM 异常 → 全部 skipped")
    finally:
        restore()

    print("\n=== C3. 无 foreshadow_ops → 空返回 ===")
    statuses = await activate_plot_ledgers(
        foreshadow_ops=[],
        chapter_text="正文",
        plot_ledger_repository=MockPlotLedgerRepo([]),
        chapter_id=uuid.uuid4(),
    )
    check(len(statuses) == 0, "无 foreshadow_ops → 空返回")

    print("\n=== C4. 无相关段落（预筛后空）→ 全部 skipped ===")
    mock_state, restore = install_llm_mock()
    try:
        foreshadow_ops = [{"ledger_id": "hk-001", "action": "plant", "note": "渡口票据"}]
        # 正文完全不含"渡口票据"或其关键词
        statuses = await activate_plot_ledgers(
            foreshadow_ops=foreshadow_ops,
            chapter_text="完全不相关的内容。" * 10,
            plot_ledger_repository=MockPlotLedgerRepo([]),
            chapter_id=uuid.uuid4(),
            chapter_number=1,
        )
        check(len(mock_state["call_log"]) == 0, "预筛空 → 不调用 LLM")
        check(statuses[0].status == "skipped", "预筛空 → skipped")
        check("prefilter" in (statuses[0].note or ""), "note 标注 prefilter 原因")
    finally:
        restore()

    # ============================================================
    # D. update_rolling_summary
    # ============================================================
    print("\n=== D1. 合并旧摘要 + 本章摘要 → 写回 Book ===")
    mock_state, restore = install_llm_mock()
    try:
        book = MockBook(rolling_summary="第1章：李雷到达渡口。")
        book_repo = MockBookRepo(book)
        mock_state["set_responses"]([json.dumps({"rolling_summary": "第1章：李雷到达渡口。第2章：韩梅梅加入。"})])
        result = await update_rolling_summary(
            book_repository=book_repo,
            book_id=book.id,
            chapter_summary="韩梅梅加入队伍。",
            chapter_number=2,
        )
        check(result == "第1章：李雷到达渡口。第2章：韩梅梅加入。", "返回新滚动摘要")
        check(book.rolling_summary == "第1章：李雷到达渡口。第2章：韩梅梅加入。", "写回 Book.rolling_summary")
        check(book_repo.commits == 1, "提交 1 次")
        check(mock_state["call_log"][0]["model_type"] == "light", "用 light 槽")
    finally:
        restore()

    print("\n=== D2. 本章无摘要 → 跳过 ===")
    mock_state, restore = install_llm_mock()
    try:
        book = MockBook(rolling_summary="旧摘要")
        book_repo = MockBookRepo(book)
        result = await update_rolling_summary(
            book_repository=book_repo,
            book_id=book.id,
            chapter_summary="",  # 无摘要
            chapter_number=2,
        )
        check(len(mock_state["call_log"]) == 0, "无摘要 → 不调用 LLM")
        check(result == "旧摘要", "返回旧摘要")
        check(book_repo.commits == 0, "无摘要不提交")
    finally:
        restore()

    print("\n=== D3. LLM 异常 → 保留旧摘要 ===")
    mock_state, restore = install_llm_mock()
    try:
        book = MockBook(rolling_summary="旧摘要")
        book_repo = MockBookRepo(book)
        mock_state["set_exceptions"]([RuntimeError("LLM 失败")])
        result = await update_rolling_summary(
            book_repository=book_repo,
            book_id=book.id,
            chapter_summary="新摘要",
            chapter_number=2,
        )
        check(result == "旧摘要", "LLM 异常 → 返回旧摘要")
        check(book.rolling_summary == "旧摘要", "Book.rolling_summary 不变")
        check(book_repo.commits == 0, "异常不提交")
    finally:
        restore()

    print("\n=== D4. 首章（无旧摘要）+ 有本章摘要 ===")
    mock_state, restore = install_llm_mock()
    try:
        book = MockBook(rolling_summary=None)  # 首章
        book_repo = MockBookRepo(book)
        mock_state["set_responses"]([json.dumps({"rolling_summary": "第1章：故事开始。"})])
        result = await update_rolling_summary(
            book_repository=book_repo,
            book_id=book.id,
            chapter_summary="故事开始。",
            chapter_number=1,
        )
        check(result == "第1章：故事开始。", "首章建立滚动摘要")
        check(book.rolling_summary == "第1章：故事开始。", "首章写回 Book")
    finally:
        restore()

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CP3.3 SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
