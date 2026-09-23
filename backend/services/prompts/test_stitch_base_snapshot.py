# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - stitch 基座 prompt 快照锁（哈希锁）
r"""
对拍口径（docs/next-phase/06-prompt-governance-hardening.md F1，2026-09 拍板）：

stitch 续写链的基座 prompt 措辞此前无快照锁——微调一个字不炸任何测试，
行为静默改变，只能事后翻 trace 发现。本文件对基座常量与五模式 user 模板做
SHA256 锁定（对齐质感契约先例 services/style/test_texture_contracts.py 的
5f87fd9e 锁法）。语义：**改措辞必须有意更新哈希**——测试红=「你在动 stitch
基座」的提醒，更新哈希的动作本身成为一次显式确认。不是不许改，是不许
不知不觉地改。

锁定面（17 块）：
- 基座常量 _ADAPTIVE_SYSTEM（含 {banned_words} 占位的原文——禁词表本体在
  nlg/anti_ai_rules.py，另有分层对拍 test_continuation_rules，不在此锁）；
- 续写五律 _RULE_NEW_INFO/_RULE_TEXTURE/_RULE_BREAKPOINT/_RULE_ENDING/
  _RULE_ENDING_PARA（逐条单锁，红哪条知道改了哪条）；
- 视点锁四锁 _SUBJECT_LOCK_TEXTS[prop/speaker/reply/handoff]（锁数=4 另有
  独立断言，增删锁也炸）；
- 桥接铁律块（adaptive_prompts.py :636-645 附近）：源码中是
  build_continue_prompt 的局部量 bridge_rule（无模块级常量可导入），以稳定
  邻接标记从渲染产物中切 span 锁定；FIM 后文锚块 suffix_block 同法切取
  （标记句漂移本身即措辞变更，切取失败=红）；
- 五模式 user 模板：stitch/continue/burst/outline/open 各用一组固定最小代表
  上下文渲染 user prompt 全文后整文锁定（builder 均为纯函数，零 DB/LLM 依赖）；
  另加 stitch×桥接变体（suffix_anchor 非空）锁定桥接分支的渲染面。

不锁的（及原因）：
- system 渲染面：system = _ADAPTIVE_SYSTEM + texture 契约块（唯一权威
  services/style/texture_contracts.py，已有 5f87fd9e 锁）+ budget 七块
  （块定义另有 test_budget_allocate 零变化锁管装配）——基座侧常量锁已覆盖；
- 意图反推/未来推测/dock 生发 prompt：属其他链（dock 侧管理较好，见设计稿
  §0），不在 F1 范围。

哈希更新程序（有意改措辞的正确姿势，三步）：
1. 打印当前哈希（项目根执行）：
   .venv\Scripts\python.exe -m backend.services.prompts.test_stitch_base_snapshot
2. 人工确认 diff：git diff backend/services/prompts/adaptive_prompts.py——
   是哪一块、为什么要改、预期影响哪个模式；
3. 用打印出的新哈希替换 _EXPECTED_SHA256 对应条目，跑本文件转绿——
   有意更新哈希=一次显式确认；发现顺手动了没锁的块=先补锁再改。
"""
import hashlib

import pytest

from backend.services.prompts.adaptive_prompts import (
    _ADAPTIVE_SYSTEM,
    _RULE_BREAKPOINT,
    _RULE_ENDING,
    _RULE_ENDING_PARA,
    _RULE_NEW_INFO,
    _RULE_TEXTURE,
    _SUBJECT_LOCK_TEXTS,
    SUBJECT_LOCK_HANDOFF,
    SUBJECT_LOCK_PROP,
    SUBJECT_LOCK_REPLY,
    SUBJECT_LOCK_SPEAKER,
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 固定代表上下文（改这些字面量=改全部渲染面哈希，同样要走哈希更新程序）----
_FRAGMENT = "他攥紧扳手的手停在半空，"
_PREFIX = "工棚里的灯忽明忽暗。"
_PARTS = ["皮带在轮槽里打着滑"]
_SUFFIX_ANCHOR = "巷子里没灯，他摸黑往前走了两步。"
_BEAT_GUIDANCE = "两人拆下发电机往高处搬"
_OUTLINE_NOTE = "两人拆发电机（约300字）"
_AFTER_TEXT = "搬到高处后雨就下来了。"
_OPEN_OUTLINE = "林尘在工地第一次顶撞工头"

# 桥接 span 的切取标记：stitch 模板「…把零件落地为具体画面。{bridge_rule}
# 零件是画面灵感…」；suffix_block 紧贴作者原句之后、零件块头之前。
# 标记句本身是模板措辞的一部分——标记漂移=切取失败=红，同样要走更新程序。
_BRIDGE_BEFORE = "把零件落地为具体画面。"
_BRIDGE_AFTER = "零件是画面灵感"
_SUFFIX_AFTER = "\n\n# 选定镜头零件（必须落地为画面）"


def _cut_between(text: str, before: str, after: str, what: str) -> str:
    i = text.find(before)
    assert i >= 0, f"{what} 定位失败：前标记漂移（stitch 模板措辞已变），先人工确认再走哈希更新程序"
    start = i + len(before)
    j = text.find(after, start)
    assert j > start, f"{what} 定位失败：后标记漂移（stitch 模板措辞已变），先人工确认再走哈希更新程序"
    return text[start:j]


# ---- 五模式 user 模板渲染（纯函数，固定最小代表上下文）----

def _render_stitch_user() -> str:
    _, user = build_continue_prompt(
        fragment=_FRAGMENT, rolling_prefix=_PREFIX, mode="stitch",
        picked_parts=list(_PARTS), target_chars=120,
    )
    return user


def _render_stitch_bridge_user() -> str:
    _, user = build_continue_prompt(
        fragment=_FRAGMENT, rolling_prefix=_PREFIX, mode="stitch",
        picked_parts=list(_PARTS), target_chars=120,
        suffix_anchor=_SUFFIX_ANCHOR,
    )
    return user


def _render_continue_user() -> str:
    _, user = build_continue_prompt(
        fragment=_FRAGMENT, rolling_prefix=_PREFIX, mode="continue",
        target_chars=200,
    )
    return user


def _render_burst_user() -> str:
    _, user = build_burst_prompt(
        fragment=_FRAGMENT, rolling_prefix=_PREFIX,
        beat_guidance=_BEAT_GUIDANCE, target_chars=700,
    )
    return user


def _render_outline_user() -> str:
    _, user = build_outline_expand_prompt(
        outline_note=_OUTLINE_NOTE, rolling_prefix=_PREFIX,
        after_text=_AFTER_TEXT, target_chars=400,
    )
    return user


def _render_open_user() -> str:
    _, user = build_opening_prompt(outline_text=_OPEN_OUTLINE, target_chars=700)
    return user


def _bridge_rule_span() -> str:
    return _cut_between(
        _render_stitch_bridge_user(), _BRIDGE_BEFORE, _BRIDGE_AFTER, "bridge_rule",
    )


def _suffix_block_span() -> str:
    return _cut_between(
        _render_stitch_bridge_user(), _FRAGMENT, _SUFFIX_AFTER, "suffix_block",
    )


# ---- 锁定面清单：名字 → 取当前文本的零参函数 ----

_SNAPSHOT_BUILDERS = {
    # 共享基座常量
    "base_system": lambda: _ADAPTIVE_SYSTEM,
    # 续写五律
    "rule_new_info": lambda: _RULE_NEW_INFO,
    "rule_texture": lambda: _RULE_TEXTURE,
    "rule_breakpoint": lambda: _RULE_BREAKPOINT,
    "rule_ending": lambda: _RULE_ENDING,
    "rule_ending_para": lambda: _RULE_ENDING_PARA,
    # 视点锁四锁
    "subject_lock_prop": lambda: _SUBJECT_LOCK_TEXTS[SUBJECT_LOCK_PROP],
    "subject_lock_speaker": lambda: _SUBJECT_LOCK_TEXTS[SUBJECT_LOCK_SPEAKER],
    "subject_lock_reply": lambda: _SUBJECT_LOCK_TEXTS[SUBJECT_LOCK_REPLY],
    "subject_lock_handoff": lambda: _SUBJECT_LOCK_TEXTS[SUBJECT_LOCK_HANDOFF],
    # 桥接铁律 / FIM 后文锚块（局部量，span 切取）
    "bridge_rule": _bridge_rule_span,
    "suffix_block": _suffix_block_span,
    # 五模式 user 模板 + 桥接变体
    "user_stitch": _render_stitch_user,
    "user_stitch_bridge": _render_stitch_bridge_user,
    "user_continue": _render_continue_user,
    "user_burst": _render_burst_user,
    "user_outline": _render_outline_user,
    "user_open": _render_open_user,
}

# 2026-09 基线快照（各条目 SHA256，更新程序见文件头）
_EXPECTED_SHA256 = {
    "base_system": "ea83b64de45cbe8ce51a15eb0b5cd3383f3e86fda26d678243667ecdcc73c408",
    "bridge_rule": "989ee70ad759cb6ca8317591097da2c8cd4d58db580cf69fea06bbbc65ecd85a",
    "rule_breakpoint": "28069bf128214a032be04ceae5b053bf15dff2f93ff954d98857918e5a55f823",
    "rule_ending": "c7497ca90a0a19b88f5f55a5f7e79d934e039fc45cd43b4bd791b07dfdd220e1",
    "rule_ending_para": "170c0200c083b85f0f300aab19bc634ba6a08a5b93a3b3a0444ccef3cf3b8e64",
    "rule_new_info": "f1aa76387c310e5051f40f87e8f0bf79771b02ffc1679552be05525f28c4bede",
    "rule_texture": "5939f482c47d5092ffc7e943a75e2edfa706f16d0723407ce8f283ff0811f268",
    "subject_lock_handoff": "eb620d8379b0455953a840ba3e4327d3722c824309518ea685b288ac2bb99679",
    "subject_lock_prop": "21e53ab27ccf4e50d8a50b2580d0fc1f2d8feb2318d20d1f951bdc3d0c82edf1",
    "subject_lock_reply": "522976d3ca079dffa509df7b0a76c3bb222965f7f9c1bba68e0bd0231ab56951",
    "subject_lock_speaker": "0e00e906655a5a6f3fa63781f2e1e0d7d0eb0bd70628f9d2519ab09b0199ab7a",
    "suffix_block": "f080635c8b1d5afc330d3fc6eacc1afc2ac8e8b97f572569cf28b245479c16c8",
    "user_burst": "a0705f705b84da07eab54a0d9cded5c20631d61dcbef7acfd3fdab88bb400e75",
    "user_continue": "958dd003fa8e40b5632cb30d4f8a930cd3b4f52663933d3af004476b5da3d848",
    "user_open": "31f0a112936482773dee39a77d7d0c4feb6f06d6054987d525d0c4ea77d1c0df",
    "user_outline": "a53a046165eb433d9e6d904a3855bcffeb4a497beee6a2212e4b33d727a61c1e",
    "user_stitch": "be209670eb3911ac49a3897852dcb3dc3037665e77877d1dc1437bab760263d1",
    "user_stitch_bridge": "c12cde6efd085a04c5647305781d5079a352b07908379632c67fd5cc33ac50a6",
}


class TestStitchBaseSnapshot:
    """stitch 基座快照锁本体：17 块逐块对哈希，红哪块=改了哪块。"""

    @pytest.mark.parametrize("name", sorted(_SNAPSHOT_BUILDERS))
    def test_locked_block_sha(self, name):
        text = _SNAPSHOT_BUILDERS[name]()
        assert text, f"{name} 锁定面为空串——切取逻辑或常量缺失，先查实现再谈更新哈希"
        assert _sha(text) == _EXPECTED_SHA256[name], (
            f"{name} 措辞与快照不符——你在动 stitch 基座 prompt。"
            "有意修改请走文件头「哈希更新程序」三步；无意改动请还原。"
        )

    def test_expected_covers_exactly_snapshot(self):
        """两侧清单对齐：加锁面必须同步登记哈希（漏一边=静默失守）。"""
        assert set(_EXPECTED_SHA256) == set(_SNAPSHOT_BUILDERS)

    def test_subject_lock_set_frozen(self):
        """视点锁锁数=4：增删锁（新键/删键）同样必须显式过快照程序。"""
        assert set(_SUBJECT_LOCK_TEXTS) == {
            SUBJECT_LOCK_PROP,
            SUBJECT_LOCK_SPEAKER,
            SUBJECT_LOCK_REPLY,
            SUBJECT_LOCK_HANDOFF,
        }


if __name__ == "__main__":
    # 哈希更新程序第 1 步：打印当前全部锁定面的哈希（可直接粘贴替换
    # _EXPECTED_SHA256；第 2/3 步——人工确认 diff、有意替换——见文件头）。
    print("_EXPECTED_SHA256 = {")
    for _name in sorted(_SNAPSHOT_BUILDERS):
        print(f'    "{_name}": "{_sha(_SNAPSHOT_BUILDERS[_name]())}",')
    print("}")
