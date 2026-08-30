# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
上下文预算动态分配单测（P5 批次 3 · A3b，docs/foundation-hardening.md §4.2）。

四件套（任务书指定）：
1. 零变化锁：默认 MODE_CONTEXT_BUDGETS（=各块 worst-case 总和）下，五模式
   render_system_blocks 输出与不接预算器（mode=""恒等路径）逐字节一致；
   满配输入的总注入 ≤ 模式预算（初值表的口径复验）；
2. 裁剪序：人为压小预算 → 软块按 echoes→author_samples→spatial→style_positive
   从尾往前收缩（先减条数、减到零整块缺席），硬块（canon/secrets/proper_nouns）
   逐字节不动；
3. 拥挤场景：满配 16 角色在场名单 + 全块注入，预算压到硬块总额时在场专名
   条目全部存活（A2 名单序=优先级信号，硬块永不裁剪）；
4. 空块不报错：全空块 / 空块列表，allocate 恒等或安全返回。

另锁：allocate 纯度（不改入参）、BlockUsage 明细正确性、预览载荷
budget_chars/trimmed 接线（monkeypatch 模式预算表走真实渲染路径）。

满配输入口径 = budget.BLOCK_CHAR_BUDGETS 注释的计算口径（条目按常量上限、
名字/标签 16 字假设额度）——初值表若与实际渲染脱钩，测试①的总额断言会红。

运行：python -m pytest backend/services/context/test_budget_allocate.py -v
"""

from backend.services.context.budget import (
    AUTHOR_SAMPLES_C3_TOPUP,
    BLOCK_CHAR_BUDGETS,
    MODE_BLOCK_BUDGET_OVERRIDES,
    MODE_CONTEXT_BUDGETS,
    AllocationResult,
    BudgetBlock,
    allocate,
)
from backend.services.context.settings_bundle import SettingsBundle
from backend.services.context.stitch_context import StitchContext, build_context_preview
from backend.services.prompts.adaptive_prompts import (
    _base_system,
    _canon_block_def,
    _echoes_block_def,
    _nouns_block_def,
    _samples_block_def,
    _secrets_block_def,
    _spatial_block_def,
    _style_block_def,
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
    render_system_blocks,
    render_system_blocks_with_usage,
)

MODES = ("continue", "stitch", "burst", "outline", "open")
N16 = "名" * 16  # 名字/标签类字段假设额度（budget._NAME_ALLOWANCE_CHARS）


# ============================================================
# 满配（worst-case）输入：口径与 BLOCK_CHAR_BUDGETS 注释一致
# ============================================================

def fat_kwargs() -> dict:
    """七块全满配：条目数/条目长度全部顶到 budget 常量上限。"""
    canon_parts = ["## 作者脑中的真相 [private] ★ 绝不许在正文直接写出"]
    for _ in range(10):
        line = f"- {N16}：{'真' * 150}（揭示计划：{'计' * 80}）"
        canon_parts.append(line)
        canon_parts.append("  → 写作时可作为角色隐藏动机，但绝不能用对话/叙述/心理独白直接说出")
    canon_parts.append("\n## 必须遵守的已建立事实 [public]")
    canon_parts.extend(f"- {N16}：{'事' * 120}" for _ in range(10))
    canon_parts.append("\n## 活跃伏笔 [hook]（本章可推进/回收）")
    canon_parts.extend(f"- [{N16}] 强度=999：{'伏' * 100}" for _ in range(8))
    return dict(
        style_positive="\n".join(f"- {N16}：{'值' * 120}" for _ in range(14)),
        author_samples=["样" * 1200, "本" * 1200],
        proper_nouns=[N16] * 20,
        canon_context="\n".join(canon_parts),
        character_secrets=[{"name": N16, "text": "密" * 150} for _ in range(8)],
        memory_echoes=["回" * 160] * 3,
        spatial_brief="距" * 300,
    )


def fat_defs() -> list:
    """满配 BudgetBlock 列表（注入序）。"""
    kw = fat_kwargs()
    return [
        _style_block_def(kw["style_positive"]),
        _samples_block_def(kw["author_samples"]),
        _nouns_block_def(kw["proper_nouns"]),
        _canon_block_def(kw["canon_context"]),
        _secrets_block_def(kw["character_secrets"]),
        _echoes_block_def(kw["memory_echoes"]),
        _spatial_block_def(kw["spatial_brief"]),
    ]


def usage_by_key(result: AllocationResult) -> dict:
    return {u.key: u for u in result.usages}


# ============================================================
# 1. 零变化锁：默认预算 = 恒等
# ============================================================

class TestZeroChangeUnderDefaultBudgets:
    def test_default_budgets_identity_for_all_modes(self):
        """默认预算下不触发裁剪：burst/outline/open 与恒等路径（mode=""）逐字节
        一致；continue/stitch 因 C3 画像压缩只在 style_positive 块有别（压缩后
        条目数=关键行数），其余六块逐字节一致且不裁剪（生效断言见
        test_c3_mode_differential）。"""
        kw = fat_kwargs()
        baseline = render_system_blocks(**kw)  # mode="" → 不过 allocate、不压缩
        for mode in ("burst", "outline", "open"):
            assert render_system_blocks(**kw, mode=mode) == baseline, f"{mode} 默认预算下发生裁剪"
        for mode in ("continue", "stitch"):
            blocks = dict(render_system_blocks(**kw, mode=mode))
            base = dict(baseline)
            assert set(blocks) == set(base)
            for key in blocks:
                if key == "style_positive":
                    continue  # C3 轻档压缩（关键行），另行单测
                assert blocks[key] == base[key], f"{mode}.{key} 默认预算下发生裁剪"
            _blocks, usages = render_system_blocks_with_usage(**kw, mode=mode)
            assert all(not u.trimmed for u in usages), f"{mode} 默认预算不应裁剪"

    def test_fat_total_within_mode_budget(self):
        """满配（worst-case 口径）总注入 ≤ 模式预算——初值表的口径复验。"""
        total = sum(len(b.render()) for b in fat_defs())
        assert total <= MODE_CONTEXT_BUDGETS["stitch"], (
            f"满配总额 {total} 超过预算 {MODE_CONTEXT_BUDGETS['stitch']}——"
            "BLOCK_CHAR_BUDGETS/MODE_CONTEXT_BUDGETS 与实际渲染脱钩"
        )
        assert all(total <= v for v in MODE_CONTEXT_BUDGETS.values())

    def test_allocate_identity_no_trim_flag(self):
        result = allocate(fat_defs(), MODE_CONTEXT_BUDGETS["continue"])
        assert result.trimmed_any is False
        assert all(not u.trimmed for u in result.usages)
        assert all(u.entries_kept == u.entries_total for u in result.usages)

    def test_mode_budgets_after_c3(self):
        """模式预算表（C3 后）：continue/stitch/outline/open = Σ BLOCK_CHAR_
        BUDGETS（默认零变化）；burst = 基数 + AUTHOR_SAMPLES_C3_TOPUP
        （样本加量 k=3，满配不裁剪）。"""
        base = sum(BLOCK_CHAR_BUDGETS.values())
        assert set(MODE_CONTEXT_BUDGETS) == set(MODES)
        for mode in ("continue", "stitch", "outline", "open"):
            assert MODE_CONTEXT_BUDGETS[mode] == base, f"{mode} 应维持基数"
        assert MODE_CONTEXT_BUDGETS["burst"] == base + AUTHOR_SAMPLES_C3_TOPUP

    def test_burst_fat_k3_samples_no_trim(self):
        """C3 burst 样本加量：k=3 满配（3×1200 样本 + 全块顶格）不触发
        allocate 裁剪；author_samples 块配额按 burst 档覆盖（预算条不显
        假超支），其余模式配额不受影响（k=2 基表口径）。"""
        kw = fat_kwargs()
        kw["author_samples"] = ["样" * 1200, "本" * 1200, "条" * 1200]
        _blocks, usages = render_system_blocks_with_usage(**kw, mode="burst")
        u = {x.key: x for x in usages}
        assert all(not x.trimmed for x in usages)          # 满配不裁
        assert u["author_samples"].entries_total == 3
        assert u["author_samples"].entries_kept == 3
        assert u["author_samples"].budget_chars == (
            BLOCK_CHAR_BUDGETS["author_samples"] + AUTHOR_SAMPLES_C3_TOPUP
        )
        # 覆盖只作用于 burst 档：continue 的样本配额仍是基表口径
        _b2, usages2 = render_system_blocks_with_usage(**fat_kwargs(), mode="continue")
        u2 = {x.key: x for x in usages2}
        assert u2["author_samples"].budget_chars == BLOCK_CHAR_BUDGETS["author_samples"]
        assert MODE_BLOCK_BUDGET_OVERRIDES.keys() == {"burst"}

    def test_builders_prompt_unchanged_with_mode(self):
        """四 builder 的 system prompt = 基座 + 各自真实注入档的块渲染
        （逐字节；C3 起模式间注入可差异化——builder 内部传的 mode 即档位）。"""
        kw = fat_kwargs()
        cases = [
            (build_continue_prompt(
                fragment="他攥紧扳手", rolling_prefix="灯下。", mode="stitch", **kw,
            )[0], "stitch"),
            (build_burst_prompt(fragment="风更大了。", rolling_prefix="退潮。", **kw)[0], "burst"),
            (build_outline_expand_prompt(
                outline_note="约300字：阿晚说出真相", rolling_prefix="灯下。", **kw,
            )[0], "outline"),
            (build_opening_prompt(outline_text="第一章：暴风雨夜。", **kw)[0], "open"),
        ]
        for sys_prompt, mode in cases:
            block_text = "".join(c for _k, c in render_system_blocks(**kw, mode=mode))
            assert sys_prompt == _base_system() + block_text, f"{mode} 与真实注入不同源"

    def test_unknown_mode_skips_allocator(self):
        """mode 无预算档 → 不过 allocate（旁路调用方零变化），usages=None。"""
        kw = fat_kwargs()
        blocks, usages = render_system_blocks_with_usage(**kw, mode="not-a-mode")
        assert blocks == render_system_blocks(**kw)
        assert usages is None


# ============================================================
# 2. 裁剪序：软块 echoes→samples→spatial→style 从尾收缩，硬块不动
# ============================================================

class TestTrimOrder:
    def test_small_deficit_trims_echo_tail_only(self):
        """缺口 1 字 → 只弃 echoes 尾条（1 条），其余块原样。"""
        defs = fat_defs()
        total = sum(len(b.render()) for b in defs)
        result = allocate(defs, total - 1)
        u = usage_by_key(result)
        assert result.trimmed_any is True
        assert u["echoes"].entries_kept == 2 and u["echoes"].entries_total == 3
        assert u["echoes"].trimmed_entries == 1
        # 其余软硬块均未动
        for key in ("author_samples", "spatial", "style_positive", "canon", "secrets", "proper_nouns"):
            assert u[key].trimmed is False, f"{key} 不应被裁"
        assert result.total_chars <= total - 1

    def test_echoes_goes_before_samples(self):
        """预算刚好吞掉整块 echoes：echoes 缺席、样本/空间/画像原样。"""
        defs = fat_defs()
        sizes = {b.key: len(b.render()) for b in defs}
        total = sum(sizes.values())
        result = allocate(defs, total - sizes["echoes"])
        u = usage_by_key(result)
        by_key = {b.key: b for b in result.blocks}
        assert by_key["echoes"].render() == ""          # 整块缺席
        assert u["author_samples"].trimmed is False      # 更靠后的软块未动
        assert u["spatial"].trimmed is False
        assert u["style_positive"].trimmed is False
        assert result.total_chars == total - sizes["echoes"]

    def test_echoes_then_samples_then_spatial_then_style(self):
        """逐级压缩：echoes 全缺 → 样本减条 → 样本全缺 → 空间缺席 → 画像殿后。"""
        defs = fat_defs()
        total = sum(len(b.render()) for b in defs)
        sizes = {b.key: len(b.render()) for b in defs}
        one_sample = len(_samples_block_def(["样" * 1200]).render())

        # 吞掉 echoes 全部 + samples 末条：样本 2→1
        budget = total - sizes["echoes"] - (sizes["author_samples"] - one_sample)
        result = allocate(defs, budget)
        u = usage_by_key(result)
        by_key = {b.key: b for b in result.blocks}
        assert by_key["echoes"].render() == ""
        assert u["author_samples"].entries_kept == 1 and u["author_samples"].trimmed_entries == 1
        assert "【示范 1】" in by_key["author_samples"].render()
        assert "【示范 2】" not in by_key["author_samples"].render()
        assert u["spatial"].trimmed is False
        assert u["style_positive"].trimmed is False

        # 再吞掉剩余样本 + 整块空间：spatial 缺席、画像原样
        budget2 = budget - one_sample - sizes["spatial"]
        result2 = allocate(fat_defs(), budget2)
        u2 = usage_by_key(result2)
        by_key2 = {b.key: b for b in result2.blocks}
        assert by_key2["author_samples"].render() == ""
        assert by_key2["spatial"].render() == ""
        assert u2["style_positive"].entries_kept == 14   # 画像最后才动

    def test_hard_blocks_survive_full_squeeze(self):
        """软块全部让空仍超支 → 硬块逐字节不动（宁可超支不丢强约束）。"""
        defs = fat_defs()
        hard_total = sum(len(b.render()) for b in defs if b.hard)
        result = allocate(defs, hard_total)
        u = usage_by_key(result)
        by_key = {b.key: b for b in result.blocks}
        assert by_key["style_positive"].render() == ""
        assert by_key["author_samples"].render() == ""
        assert by_key["echoes"].render() == ""
        assert by_key["spatial"].render() == ""
        # 硬块完整存活且逐字节等于满配渲染
        original = {b.key: b.render() for b in fat_defs()}
        for key in ("canon", "secrets", "proper_nouns"):
            assert by_key[key].render() == original[key]
            assert u[key].trimmed is False
        assert result.total_chars == hard_total

    def test_allocate_is_pure(self):
        """allocate 不改入参：块列表与条目列表原样（重复调用同结果）。"""
        defs = fat_defs()
        snapshot = [(b.key, list(b.entries)) for b in defs]
        total = sum(len(b.render()) for b in defs)
        allocate(defs, total // 2)
        for (key, entries), blk in zip(snapshot, defs):
            assert blk.key == key and blk.entries == entries, "allocate 污染了入参"
        # 同输入同输出
        r1 = allocate(fat_defs(), total // 2)
        r2 = allocate(fat_defs(), total // 2)
        assert [b.render() for b in r1.blocks] == [b.render() for b in r2.blocks]


# ============================================================
# 3. 拥挤场景：满配 16 角色在场名单，裁剪后在场条目仍存活
# ============================================================

class TestCrowdedBookPresenceSurvives:
    def test_16_inscene_names_survive_squeeze(self):
        """16 角色（A2 在场名单满配）+ 全块注入，压到硬块总额后专名全员存活。"""
        kw = fat_kwargs()
        names = [f"在场角色{i:02d}号" for i in range(16)]  # 16 名在场角色
        kw["proper_nouns"] = names + ["在场资产甲", "在场资产乙", "北岸要塞", "灯塔"]
        defs = [
            _style_block_def(kw["style_positive"]),
            _samples_block_def(kw["author_samples"]),
            _nouns_block_def(kw["proper_nouns"]),
            _canon_block_def(kw["canon_context"]),
            _secrets_block_def(kw["character_secrets"]),
            _echoes_block_def(kw["memory_echoes"]),
            _spatial_block_def(kw["spatial_brief"]),
        ]
        hard_total = sum(len(b.render()) for b in defs if b.hard)
        result = allocate(defs, hard_total)
        nouns_render = next(b for b in result.blocks if b.key == "proper_nouns").render()
        for name in names:
            assert name in nouns_render, f"在场角色 {name} 被预算挤出"

    def test_through_real_render_path_with_patched_budget(self, monkeypatch):
        """经 render_system_blocks 真实路径（monkeypatch 模式预算表）复验：
        软块收缩、硬块与在场专名原样、usages 明细可用。"""
        monkeypatch.setattr(
            "backend.services.prompts.adaptive_prompts.MODE_CONTEXT_BUDGETS",
            {"stitch": 3000},
        )
        kw = fat_kwargs()
        names = [f"在场角色{i:02d}号" for i in range(16)]
        kw["proper_nouns"] = names
        blocks, usages = render_system_blocks_with_usage(**kw, mode="stitch")
        by_key = dict(blocks)
        u = {x.key: x for x in usages}
        assert by_key["echoes"] == ""                      # 最可让，先缺席
        assert u["author_samples"].trimmed                 # 其次减条
        assert u["spatial"].trimmed
        assert not u["proper_nouns"].trimmed               # 硬块全员存活
        for name in names:
            assert name in by_key["proper_nouns"]

    def test_preview_payload_carries_budget_and_trim(self, monkeypatch):
        """预览载荷接线：budget_chars=块配额、trimmed 人话文案随裁剪出现。

        C3 后 continue/stitch 档画像压缩（fat 画像压缩为空），此处的满配
        裁剪算术改挂 outline 档（完整画像、无块配额覆盖干扰）。
        """
        kw0 = fat_kwargs()
        defs0 = [
            _style_block_def(kw0["style_positive"]),
            _samples_block_def(kw0["author_samples"]),
            _nouns_block_def(kw0["proper_nouns"]),
            _canon_block_def(kw0["canon_context"]),
            _secrets_block_def(kw0["character_secrets"]),
            _echoes_block_def(kw0["memory_echoes"]),
            _spatial_block_def(kw0["spatial_brief"]),
        ]
        # 预算 = 硬块总额 + 单条样本 + 空间 + 画像 → echoes 让位、样本 2→1
        #（减条不缺席）、空间与画像原样
        sizes = {b.key: len(b.render()) for b in defs0}
        one_sample = len(_samples_block_def(["样" * 1200]).render())
        monkeypatch.setattr(
            "backend.services.prompts.adaptive_prompts.MODE_CONTEXT_BUDGETS",
            {"outline": (
                sizes["canon"] + sizes["secrets"] + sizes["proper_nouns"]
                + one_sample + sizes["spatial"] + sizes["style_positive"]
            )},
        )
        kw = fat_kwargs()
        ctx = StitchContext(
            bundle=SettingsBundle(
                canon_context=kw["canon_context"], spatial_brief=kw["spatial_brief"],
                character_secrets=kw["character_secrets"],
            ),
            proper_nouns=kw["proper_nouns"],
            memory_echoes=kw["memory_echoes"],
            style_positive=kw["style_positive"],
            author_samples=kw["author_samples"],
            mode="outline",
        )
        payload = build_context_preview(ctx, "outline")
        by_key = {b["key"]: b for b in payload["blocks"]}
        # 每块带配额（=BLOCK_CHAR_BUDGETS），未裁块无 trimmed 键
        assert by_key["canon"]["budget_chars"] == BLOCK_CHAR_BUDGETS["canon"]
        assert by_key["proper_nouns"]["budget_chars"] == BLOCK_CHAR_BUDGETS["proper_nouns"]
        assert "trimmed" not in by_key["canon"]
        assert "trimmed" not in by_key["proper_nouns"]
        # 被裁块带人话文案
        assert by_key["echoes"]["trimmed"] == "预算超支，整块缺席（原 3 条）"
        assert "→" in by_key["author_samples"]["trimmed"]
        # 预览内容与注入同源：content 即该次渲染的块文本
        assert by_key["echoes"]["content"] == ""
        assert by_key["canon"]["content"].startswith("\n\n# 作者脑中世界图谱（Canon）\n")


# ============================================================
# 4. 空块不报错
# ============================================================

class TestEmptyBlocksSafe:
    def test_all_blocks_empty_with_mode(self):
        """全空块 + 模式预算：全块空串、恒等、不抛错（B6 起 13 键：知识平面 6 块 + 旧 7 块）。"""
        blocks, usages = render_system_blocks_with_usage(mode="stitch")
        assert len(blocks) == 13
        assert all(content == "" for _k, content in blocks)
        assert all(u.chars == 0 and not u.trimmed for u in usages)

    def test_empty_block_list(self):
        """空块列表：零总额、恒等、usages 空。"""
        result = allocate([], 0)
        assert result.total_chars == 0
        assert result.trimmed_any is False
        assert result.usages == []

    def test_budgetBlock_render_empty_entries(self):
        """BudgetBlock 空条目 → 空串（整块缺席，prompt 零残留）。"""
        blk = BudgetBlock(key="x", header="H", entries=[])
        assert blk.render() == ""
        assert BudgetBlock(key="x", header="H", entries=["a"], footer="F").render() == "HaF"
