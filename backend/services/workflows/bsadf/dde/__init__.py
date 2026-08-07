"""
DDE（Director Decision Engine，导演决策引擎）—— 章节级剧情分叉控制器。

职责：在 Phase 4b（槽位扩写）之后，对全章做一次"剧情走向级真实岔路"判断，
     产出 ChapterDecisionSet；作者选定（或 Track A 静默默认）的分支走向经
     SlotMutator 写入 BeatSlotCard.branch_directive，注入渲染 prompt 的
     "本段剧情走向约束"强约束区。

模块组织：
- types.py                  数据结构（ChapterDecisionSet / StoryBranch / BranchOption）
- decision_card_generator.py 章节分叉判断（全章 1×creative LLM + 代码闸门）
- slot_mutator.py           SlotMutator 纯函数（branch_choices → branch_directive 突变）
- prompts/dde_prompts.py    DDE Prompt 模板（位于 services/prompts/）

业务场景：enable_dde=True（默认）时 Track A/B 都生效；无岔路自动放行是常态。
"""
# Velluma - DDE (Director Decision Engine) package
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
