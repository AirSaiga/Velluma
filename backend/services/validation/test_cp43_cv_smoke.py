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
CP4.3 句长 CV 中文区间标定 smoke test（独立运行）。

覆盖：
- thresholds.py 常量存在且值正确
- RhythmAuditor CV < LO（0.35）→ warning finding
- RhythmAuditor CV ∈ [LO, HI] → 无 CV finding（健康）
- RhythmAuditor CV > HI（0.80）→ 无 CV finding（健康多变）
- warning finding 含 detail（CV 值）+ suggestion
- warning 不升级为 blocker（severity=warning，非 blocker）
- passed 不受 CV warning 影响（RhythmAuditor 不阻断）
"""

import asyncio
import sys
from typing import List


async def main() -> int:
    from backend.services.validation.thresholds import (
        CV_THRESHOLD_LO,
        CV_THRESHOLD_HI,
        CONSECUTIVE_SAME_LEN_THRESHOLD,
        SUBLIMATION_HITS_THRESHOLD,
    )
    from backend.services.validation.code_auditors import RhythmAuditor

    failures: List[str] = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            failures.append(msg)

    print("=== 1. 阈值常量存在且值正确 ===")
    check(CV_THRESHOLD_LO == 0.35, f"CV_THRESHOLD_LO == 0.35（实际 {CV_THRESHOLD_LO}）")
    check(CV_THRESHOLD_HI == 0.80, f"CV_THRESHOLD_HI == 0.80（实际 {CV_THRESHOLD_HI}）")
    check(CONSECUTIVE_SAME_LEN_THRESHOLD == 6, f"CONSECUTIVE_SAME_LEN_THRESHOLD == 6（实际 {CONSECUTIVE_SAME_LEN_THRESHOLD}）")
    check(SUBLIMATION_HITS_THRESHOLD == 2, f"SUBLIMATION_HITS_THRESHOLD == 2（实际 {SUBLIMATION_HITS_THRESHOLD}）")

    print("\n=== 2. CV < LO（0.35）→ warning finding ===")
    # 构造等长句：每句都是 15 字，CV ≈ 0
    # 用 6 句（避开连续同长句阈值 6 的边界，但 CV 仍极低）
    auditor = RhythmAuditor()
    monotone_text = "他慢慢地走过来看着前方。" * 5  # 5 句等长
    result = await auditor.audit(monotone_text, {})
    cv = result.metrics.get("sentence_len_cv")
    print(f"       实际 CV = {cv}")
    check(cv is not None and cv < CV_THRESHOLD_LO,
          f"CV < LO={CV_THRESHOLD_LO}（实际 {cv}）")
    cv_findings = [f for f in result.findings if "变异系数" in f.get("detail", "")]
    check(len(cv_findings) >= 1, f"CV 超标产 warning finding（{len(cv_findings)} 条）")
    if cv_findings:
        f = cv_findings[0]
        check(f["severity"] == "warning", f"CV finding severity=warning（实际 {f['severity']}）")
        check(f["severity"] != "blocker", "CV 不升级为 blocker（软指标）")
        check(f["category"] == "style", "CV finding category=style")
        check(str(cv) in f["detail"], "detail 含具体 CV 值")
        check(f.get("suggestion"), "含 suggestion")

    print("\n=== 3. CV ∈ [LO, HI]（健康区间）→ 无 CV finding ===")
    # 构造句长有变化但不极端的文本（短句 + 长句交错）
    healthy_text = (
        "他站住。"  # 短
        "风吹过远处的山岗，带来一阵若有若无的草木气息。"  # 长
        "她笑了。"  # 短
        "门口的灯笼在夜色里摇曳，投下斑驳的光影。"  # 中
        "谁？"  # 极短
        "他没有回答，只是默默地看着窗外那条空无一人的长街。"  # 长
    )
    result = await auditor.audit(healthy_text, {})
    cv = result.metrics.get("sentence_len_cv")
    print(f"       实际 CV = {cv}")
    check(cv is not None and CV_THRESHOLD_LO <= cv <= CV_THRESHOLD_HI,
          f"CV ∈ [{CV_THRESHOLD_LO}, {CV_THRESHOLD_HI}]（实际 {cv}）")
    cv_findings = [f for f in result.findings if "变异系数" in f.get("detail", "")]
    check(len(cv_findings) == 0, f"健康 CV 不产 CV finding（实际 {len(cv_findings)} 条）")

    print("\n=== 4. CV > HI（0.80，多变）→ 无 CV finding ===")
    # 构造极端长短交错（CV 很高）。注意 _split_sentences 过滤 ≤2 字片段，
    # 所以短句至少 3 字。
    varied_text = (
        "他站住了。"  # 4 字（短）
        "他猛地转过身去，看见那个穿着破旧灰袍的身影正从雨幕深处缓缓走来，手中提着一盏早已熄灭的灯笼。"  # 长
        "她走过来。"  # 5 字（短）
        "记忆像潮水一样涌回来，那年夏天渡口的蝉鸣、母亲递过来的那碗凉茶、还有那封从未寄出的信。"  # 长
        "谁在那？"  # 5 字（短）
        "门口的灯笼在夜色里摇曳，投下斑驳的光影，远处传来几声犬吠，若有若无。"  # 长
    )
    result = await auditor.audit(varied_text, {})
    cv = result.metrics.get("sentence_len_cv")
    print(f"       实际 CV = {cv}")
    check(cv is not None and cv > CV_THRESHOLD_HI,
          f"CV > HI={CV_THRESHOLD_HI}（实际 {cv}）")
    cv_findings = [f for f in result.findings if "变异系数" in f.get("detail", "")]
    check(len(cv_findings) == 0, f"多变 CV 不产 CV finding（实际 {len(cv_findings)} 条）")

    print("\n=== 5. CV warning 不影响 passed（RhythmAuditor 不阻断）===")
    # 即便 CV < LO 触发 warning，passed 仍为 True（只有 RedLine/Cliché blocker 才阻断）
    result = await auditor.audit(monotone_text, {})
    cv_findings = [f for f in result.findings if "变异系数" in f.get("detail", "")]
    check(len(cv_findings) >= 1, "CV 触发 warning")
    check(result.passed is True, "CV warning 不影响 passed（RhythmAuditor 不阻断）")

    print("\n=== 6. 空文本短路（CV=0）===")
    result = await auditor.audit("", {})
    check(result.metrics.get("sentence_len_cv") == 0.0, "空文本 CV=0")
    check(len(result.findings) == 0, "空文本无 finding")

    print("\n=== 7. CP3.1b 既有子指标仍工作（连续同长句 + 段末升华）===")
    # 这两个子指标在 CP4.3 前已实现，CP4.3 不应破坏
    text_with_both = (
        "他慢慢走过来看着前方。她轻轻走过来看着前方。"
        "他们慢慢走过来看着前方。它轻轻飞过来看着前方。"
        "我们慢慢走过来看着前方。你们轻轻走过来看着前方。"
        "命运的齿轮开始转动，一切都将改变。"
    )
    result = await auditor.audit(text_with_both, {})
    run_findings = [f for f in result.findings if "连续" in f.get("detail", "")]
    subl_findings = [f for f in result.findings if "升华腔" in f.get("detail", "")]
    check(len(run_findings) >= 1, "连续同长句子指标仍工作")
    check(len(subl_findings) >= 1, "段末升华子指标仍工作")

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CP4.3 SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
