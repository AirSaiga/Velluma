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
CP3.1b 代码级审计层 smoke test（独立运行，不依赖 pytest）。

覆盖：
- 7 个 Auditor 类完整、含 audit 方法
- CodeAuditResult.metrics 含 5 个固定键
- ClichéAuditor：构造含禁词文本 → 命中
- RedLineAuditor：构造含红线引号词文本 → 命中 + passed=False
- EntityAuditor：participants 与正文不一致 → finding（decisions §3.3）
- RhythmAuditor：等长句 + 段末升华 → finding（CP4.3：CV < LO 发 warning）
- DialogueAuditor：对话占比区间 → finding
- ContinuityAuditor：time_gap 矛盾 → finding
- WordCountAuditor：字数远低于目标 → finding + word_achieve_rate
- Pipeline 聚合 + 零 token（无 LLM/embedding 调用）
"""

import asyncio
import sys


async def main() -> int:
    from backend.services.validation import (
        CodeAuditPipeline,
        CodeAuditResult,
        ClichéAuditor,
        RhythmAuditor,
        DialogueAuditor,
        EntityAuditor,
        RedLineAuditor,
        ContinuityAuditor,
        WordCountAuditor,
    )

    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            failures.append(msg)

    print("=== 1. Auditor 类完整性 ===")
    expected_auditors = [
        ("ClichéAuditor", ClichéAuditor, "cliche"),
        ("RhythmAuditor", RhythmAuditor, "rhythm"),
        ("DialogueAuditor", DialogueAuditor, "dialogue"),
        ("EntityAuditor", EntityAuditor, "entity"),
        ("RedLineAuditor", RedLineAuditor, "red_line"),
        ("ContinuityAuditor", ContinuityAuditor, "continuity"),
        ("WordCountAuditor", WordCountAuditor, "word_count"),
    ]
    for name, cls, expected_name in expected_auditors:
        inst = cls()
        check(hasattr(inst, "audit"), f"{name}.audit 存在")
        check(inst.auditor_name == expected_name, f"{name}.auditor_name == '{expected_name}'")

    print("\n=== 2. ClichéAuditor 命中禁词 ===")
    # 构造含多条 blocker 禁词的文本（眼底闪过一丝 / 嘴角勾起一抹）
    cliche_text = (
        "他眼底闪过一丝惊愕，嘴角勾起一抹冷笑。"
        "她也不禁倒吸一口凉气，仿佛命运的齿轮开始转动。"
        "这一刻，主角终于明白了某种意义上的真相。"
        "风吹过，落叶纷飞。他静静站着，没有说话。"
        "远处的钟声响起，回荡在空旷的街道上，余音袅袅不绝。"
    )
    cliche_ctx = {"book": {"style_blacklist": []}, "style_card": {"negative_list": []}}
    cliche_result = await ClichéAuditor().audit(cliche_text, cliche_ctx)
    check("cliche_hits_per_1k" in cliche_result.metrics, "metrics 含 cliche_hits_per_1k")
    check(cliche_result.metrics["cliche_hits_per_1k"] > 0, "禁词命中率 > 0")
    check(len(cliche_result.findings) >= 1, "产出至少 1 个 finding")
    print(f"       cliche_hits_per_1k = {cliche_result.metrics['cliche_hits_per_1k']}")

    print("\n=== 3. RedLineAuditor 红线引号词硬校验 ===")
    redline_text = "他手持禁器「血魂幡」，向敌人挥去。血魂幡发出阵阵嘶吼。"
    redline_ctx = {
        "beats": [{"red_lines": ["不得出现「血魂幡」等禁器"]}],
        "book": {"core_motifs_taboos": ""},
    }
    redline_result = await RedLineAuditor().audit(redline_text, redline_ctx)
    check("red_line_violations" in redline_result.metrics, "metrics 含 red_line_violations")
    check(redline_result.metrics["red_line_violations"] >= 2, "红线违反次数 ≥ 2（血魂幡出现 2 次）")
    check(redline_result.passed is False, "passed=False（红线硬违反）")
    check(len(redline_result.findings) >= 1, "产出 finding")
    check(all(f["severity"] != "blocker" for f in redline_result.findings), "代码级 finding 严格 warning/info（blocker 归 LLM）")
    print(f"       red_line_violations = {redline_result.metrics['red_line_violations']}")

    print("\n=== 4. EntityAuditor 在场一致性（decisions §3.3 双源对照）===")
    entity_text = "李雷看着天空。韩梅梅走过来，递给他一杯水。两人都没有说话。"
    entity_ctx = {
        "beats": [
            {"position": 1, "participants": ["李雷", "王五"]},  # 王五未出现 → missing
        ],
        "characters": [
            {"name": "李雷", "aliases": []},
            {"name": "韩梅梅", "aliases": []},  # 不在任何 participants → unexpected
        ],
    }
    entity_result = await EntityAuditor().audit(entity_text, entity_ctx)
    # 韩梅梅不在任何 beat.participants → unexpected finding
    unexpected_findings = [f for f in entity_result.findings if "未在任何 beat.participants" in f["detail"]]
    check(len(unexpected_findings) >= 1, "检测出 participants 之外的角色（韩梅梅）")
    # 王五在 beat1.participants 但正文未出现 → missing finding
    missing_findings = [f for f in entity_result.findings if "未在正文中出现" in f["detail"]]
    check(len(missing_findings) >= 1, "检测出预期在场但正文未出现的角色（王五）")

    print("\n=== 5. RhythmAuditor 句长 CV + 段末升华（CP4.3：CV 区间标定后发 warning）===")
    # 构造连续等长句 + 段末升华
    rhythm_text = (
        "他慢慢地走过去，看着前方。她轻轻地走过来，看着前方。"
        "他们慢慢地走过去，看着前方。它轻轻地飞过来，看着前方。"
        "我们慢慢地走过去，看着前方。你们轻轻地走过来，看着前方。"
        "命运的齿轮开始转动，一切都将改变。"
    )
    rhythm_result = await RhythmAuditor().audit(rhythm_text, {})
    check("sentence_len_cv" in rhythm_result.metrics, "metrics 含 sentence_len_cv")
    print(f"       sentence_len_cv = {rhythm_result.metrics['sentence_len_cv']}")
    run_findings = [f for f in rhythm_result.findings if "连续" in f["detail"]]
    check(len(run_findings) >= 1, "检测出连续同长句")
    subl_findings = [f for f in rhythm_result.findings if "升华腔" in f["detail"]]
    check(len(subl_findings) >= 1, "检测出段末升华腔")
    # CV 不阻断
    check(rhythm_result.passed is True, "RhythmAuditor warning 不阻断 passed=True（CV 是软指标）")

    print("\n=== 6. DialogueAuditor 对话占比 ===")
    dialogue_text = "他说：“你好。”她说：“你好吗？”他说：“我很好。”她说：“那太好了。”"
    dialogue_result = await DialogueAuditor().audit(dialogue_text, {})
    check("dialogue_ratio" in dialogue_result.metrics, "metrics 含 dialogue_ratio")
    print(f"       dialogue_ratio = {dialogue_result.metrics['dialogue_ratio']}")
    # 无 StyleCard 目标时默认区间 [0.2, 0.5]，此处对话占比极高
    check(len(dialogue_result.findings) >= 1, "高对话占比产出 finding")

    print("\n=== 7. ContinuityAuditor 时间线矛盾 ===")
    cont_text = "当夜的月光很亮。李雷站在窗前，回忆着往事。一切都很安静。"
    cont_ctx = {
        "chapter_card": {"continuity": {"time_gap": "次日", "location": "渡口"}},
        "prev_chapter_summary": "李雷在客栈拿到了一张渡口票据。",
    }
    cont_result = await ContinuityAuditor().audit(cont_text, cont_ctx)
    # time_gap=次日 但首段出现"当夜" → 矛盾
    timeline_findings = [f for f in cont_result.findings if f["category"] == "timeline"]
    check(len(timeline_findings) >= 1, "检测出时间线矛盾（次日 vs 当夜）")
    # location=渡口 但首段无 → 地点衔接 finding
    location_findings = [f for f in cont_result.findings if "location" in f["detail"]]
    check(len(location_findings) >= 1, "检测出地点衔接缺失（渡口）")

    print("\n=== 8. WordCountAuditor 字数达标率 ===")
    wc_text = "他走进房间，关上门。"  # 很短
    wc_ctx = {"chapter_card": {"word_target": 3000}, "beats": []}
    wc_result = await WordCountAuditor().audit(wc_text, wc_ctx)
    check("word_achieve_rate" in wc_result.metrics, "metrics 含 word_achieve_rate")
    check(wc_result.metrics["word_achieve_rate"] < 0.1, "达标率 < 0.1（字数远低于目标）")
    check(len(wc_result.findings) >= 1, "字数不足产出 finding")
    print(f"       word_achieve_rate = {wc_result.metrics['word_achieve_rate']}")

    print("\n=== 9. Pipeline 聚合 ===")
    pipeline = CodeAuditPipeline()
    check(len(pipeline.auditors) == 7, "Pipeline 默认含 7 个 Auditor")
    full_text = cliche_text + "\n" + redline_text
    full_ctx = {
        "book": {"style_blacklist": [], "core_motifs_taboos": ""},
        "style_card": {"negative_list": []},
        "beats": [{"position": 1, "red_lines": ["不得出现「血魂幡」等禁器"], "participants": [], "word_count_target": 5000}],
        "characters": [],
        "chapter_card": {"word_target": 5000, "continuity": {}},
    }
    agg = await pipeline.run(full_text, full_ctx)
    expected_metric_keys = {
        "cliche_hits_per_1k", "sentence_len_cv", "dialogue_ratio",
        "word_achieve_rate", "red_line_violations",
    }
    missing_keys = expected_metric_keys - set(agg.metrics.keys())
    check(not missing_keys, f"Pipeline metrics 含全部 5 个固定键（缺失: {missing_keys or '无'}）")
    check(agg.passed is False, "Pipeline passed=False（含红线违反）")
    print(f"       aggregated metrics keys = {sorted(agg.metrics.keys())}")
    print(f"       aggregated findings count = {len(agg.findings)}")

    print("\n=== 10. 零 token 验证（无 LLM/embedding 调用）===")
    # 监测 openai / dashscope client 调用
    import backend.services.llm.client as llm_client_mod
    original_chat = getattr(llm_client_mod, "call_llm", None)
    called: list[str] = []
    if original_chat:
        async def _spy_chat(*a, **k):
            called.append("call_llm")
            return await original_chat(*a, **k)
        llm_client_mod.call_llm = _spy_chat  # type: ignore
    # 运行一次完整 pipeline
    await pipeline.run(full_text, full_ctx)
    check(len(called) == 0, "Pipeline 未触发任何 call_llm（零 token）")
    # 还原
    if original_chat:
        llm_client_mod.call_llm = original_chat  # type: ignore

    # 异常隔离验证：注入一个会抛错的 Auditor，确认其他 Auditor 不受影响
    print("\n=== 11. Auditor 异常隔离 ===")
    class BoomAuditor(ClichéAuditor):
        auditor_name = "boom"
        async def _audit(self, text, context):
            raise RuntimeError("故意抛错")
    boom_pipeline = CodeAuditPipeline(auditors=[BoomAuditor(), WordCountAuditor()])
    boom_result = await boom_pipeline.run(full_text, full_ctx)
    check(boom_result.metrics.get("word_achieve_rate") is not None, "异常 Auditor 不影响其他 Auditor（word_achieve_rate 仍计算）")

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CP3.1b SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
