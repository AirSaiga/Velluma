# Velluma - NLE-ADF 3.0 挂件功能槽位单测（2026-08-29「不知所云」重构）
# AGPL-3.0
"""provenance 贯通回归：每枚碎片必须回答「选这枚会发生什么」。

覆盖 _finalize_parts 纯函数：
1. 槽位规整：显式 slot 归位、旧契约 from_expectation→echo、缺 slot→ambient；
2. note 拼装（后端权威，模型不经手出处文本）：
   - landing 固定「接着刚才那句写」
   - toward_beat 取大纲就近节拍首条原文（「通往「…」」）
   - echo 按 echo_ref 回查期待账本/前情回响原文（「读者在等：…」「呼应前情：…」）
3. 降级纪律：槽位拿不到出处 → ambient 留白（标签必须承载真实出处，否则不标）；
4. 排序：landing 首位 → toward_beat → echo → ambient（稳定）；
5. 旧形状零件（缓存里的历史产出，无 slot 无 note）零破坏照常通过。

运行：python -m pytest backend/services/adaptive/test_dock_slots.py -v
"""

from backend.services.adaptive.components.dock_generator import _finalize_parts

OUTLINE = ["突然被工头打断，支去搬物资", "袭击废料场"]
EXPECTATIONS = [
    {"type": "mystery", "description": "那本书的来历", "tension": 7},
    {"type": "promise", "description": "工头欠他的加班费", "tension": 4},
]
ECHOES = ["【前情事件·物品】第三章：扳手砸中脚边铁屑", "【记忆】第五章：书的夹层里有照片"]


def test_slots_normalized_and_sorted_landing_first():
    raw = [
        {"slot": "ambient", "type": "scene", "text": "天窗灰光里浮着机油味的尘"},
        {"slot": "landing", "type": "action", "text": "林尘把书往工具箱深处塞了塞"},
        {"slot": "toward_beat", "type": "action", "text": "他拎起墙边最沉的备件箱"},
    ]
    parts = _finalize_parts(raw, outline_nearby=OUTLINE)
    assert [p["source"] for p in parts] == ["landing", "toward_beat", "ambient"]
    assert parts[0]["text"] == "林尘把书往工具箱深处塞了塞"   # 接着写恒居首位


def test_note_assembly_backend_authoritative():
    raw = [
        {"slot": "landing", "type": "action", "text": "林尘把书往口袋深处按了按"},
        {"slot": "toward_beat", "type": "action", "text": "他拎起墙边最沉的备件箱"},
        {"slot": "echo", "type": "action", "text": "扳手柄上有道旧划痕",
         "from_memory": True, "echo_ref": 1},
        {"slot": "echo", "type": "action", "text": "指腹蹭过书页的毛边",
         "from_expectation": True, "echo_ref": 1},
    ]
    parts = _finalize_parts(
        raw, outline_nearby=OUTLINE, reader_expectations=EXPECTATIONS, memory_echoes=ECHOES,
    )
    by_text = {p["text"]: p for p in parts}
    assert by_text["林尘把书往口袋深处按了按"]["note"] == "接着刚才那句往下写"
    assert by_text["他拎起墙边最沉的备件箱"]["note"] == "往「突然被工头打断，支去」那拍走的第一步"
    # echo·memory：素材原文清洗后进 note——机器格式【前情事件·物品】第N章：不透传
    assert by_text["扳手柄上有道旧划痕"]["note"] == "顺笔带出前情：第三章·扳手砸中脚边铁屑"
    # echo·expectation：账本 description 直取
    assert by_text["指腹蹭过书页的毛边"]["note"] == "暗示读者在等：那本书的来历"


def test_echo_ref_out_of_range_demotes_to_ambient():
    """echo_ref 越界/缺素材 → 降级 ambient 留白（不谎标出处）。"""
    raw = [
        {"slot": "echo", "text": "扳手磕在料筐沿上", "from_memory": True, "echo_ref": 9},
        {"slot": "toward_beat", "text": "他起身往货梯走"},  # 无 outline_nearby
    ]
    parts = _finalize_parts(raw)  # 不传任何素材
    assert all(p["source"] == "ambient" for p in parts)
    assert all("note" not in p for p in parts)   # 留白本身是信息


def test_landing_note_survives_without_materials():
    """landing 的 note 是固定文案——无任何素材也自解释。"""
    parts = _finalize_parts([{"slot": "landing", "text": "他把后半句咽回去"}])
    assert parts[0]["source"] == "landing"
    assert parts[0]["note"] == "接着刚才那句往下写"


def test_clean_echo_note_strips_machine_formats():
    """素材原文的账本格式不进副行（2026-08-29 二轮实测：机器格式透传=乱码）。"""
    from backend.services.adaptive.components.dock_generator import _clean_echo_note

    assert _clean_echo_note("【前情事件·物品】第三章：扳手砸中脚边铁屑") == "第三章·扳手砸中脚边铁屑"
    assert _clean_echo_note("【记忆】第五章：书的夹层里有照片") == "第五章·书的夹层里有照片"
    assert _clean_echo_note("  【前情事件】旧船台的汽笛声  ") == "旧船台的汽笛声"
    assert _clean_echo_note("没有任何格式的裸素材") == "没有任何格式的裸素材"


def test_old_shape_parts_zero_damage():
    """旧形状（缓存历史产出：无 slot 无 note）→ ambient 无注，照常通过。"""
    raw = [{"type": "line", "text": "“林尘！发什么呆！”工头的呵斥", "direction": "主线"}]
    parts = _finalize_parts(raw)
    assert len(parts) == 1
    assert parts[0]["source"] == "ambient"
    assert "note" not in parts[0]
    assert parts[0]["direction"] == "主线"      # 分析面元数据保留
    assert "origin" not in parts[0]              # 无 from_expectation 无 origin 键


def test_violates_drops_part():
    dropped = _finalize_parts(
        [
            {"slot": "landing", "text": "他攥紧了拳头"},
            {"slot": "ambient", "text": "目光失焦在铁屑上"},   # 陈词嗅探命中（调用方注入判定的场景）
        ],
        violates=lambda t: "失焦" in t,
    )
    assert [p["text"] for p in dropped] == ["他攥紧了拳头"]


def test_cap_four_after_sort():
    raw = [
        {"slot": "ambient", "text": f"氛围碎片占位第{i}号"} for i in range(5)
    ] + [{"slot": "landing", "text": "他把书按了按"}]
    parts = _finalize_parts(raw)
    assert len(parts) == 4
    assert parts[0]["source"] == "landing"
