# Velluma - NLE-ADF 3.0 「3 字滑窗」共享判据单测（P2 治理）
# AGPL-3.0
"""B1/B3/B4 噪声匹配治理的对拍测试（2026-08-25 P2 批次）。

纪律（docs/adaptive-assist-hardening.md「执行约束」）：
- 先写「现状行为快照测试」锁住 B1（direction_weights._is_met）与
  B3（dock_generator._outline_line_written）的现有判定，跑绿后再改判据；
- 行为有意变化的断言逐条更新为新预期，并加注释
  `# 有意变化（P2 治理）：...` 说明旧行为与改动理由；
- B4（canon_watch 角色出场词边界）为新增判据，直接按新行为写。

运行：python -m pytest backend/services/adaptive/test_text_match.py -v
"""

# ============================================================
# 第一部分：现状行为快照（B1 direction_weights._is_met）
# ============================================================
# 快照纪律：以下断言在改动前先跑绿，锁定现状；判据收紧后行为有变的
# 条目按「有意变化」更新，无变的条目保持——防止柔性机制隐性转向。

from backend.services.adaptive.direction_weights import _is_met


def test_b1_snapshot_exact_verbatim_is_met():
    """整串直接命中 → 已达成（新旧一致：捷径保留）。"""
    text = "他按纸条指示，在钟楼下接头等了半个时辰。"
    assert _is_met("在钟楼下接头", text) is True


def test_b1_snapshot_paraphrased_true_beat_is_met():
    """真实已写、措辞微异（3/4 片段命中）→ 已达成（新旧一致）。"""
    text = "主角拿到了那把生锈的铜钥匙，掂了掂分量。"
    assert _is_met("主角拿到了钥匙", text) is True


def test_b1_snapshot_unrelated_text_is_unmet():
    """完全未写 → 未达成（新旧一致）。"""
    text = "码头的钟声响了三遍，海鸥掠过桅杆。"
    assert _is_met("必须毁掉航海日志", text) is False


def test_b1_snapshot_generic_trigram_pollution_currently_met():
    """通用三字组污染：item 的「他没有」散落在无关正文 → 判未达成。

    有意变化（P2 治理）：旧行为「任一 3 字片段命中全文即达成」——
    「他没有」这类常用三字组几乎必现，must_hit 被提前判达成、主线推动力
    熄火（B1 病灶）。新判据：4 个片段命中率 ≥50%（此处 1/4=25%）→ 未达成，
    must_hit 继续推动主线权重。改前快照断言为 True，跑绿后随判据收紧翻转。
    """
    text = "山道蜿蜒，他没有停下，只顾往前走。雾气越来越重了。"
    assert _is_met("他没有告诉任何人真相", text) is False


def test_b1_snapshot_no_fragment_item_is_unmet():
    """纯数字/标点条目无可判片段 → 现状判未达成（保持）。"""
    assert _is_met("1334", "那是很多年前的战争。") is False


def test_b1_snapshot_empty_item_is_met():
    """空条目 → 已达成（防御性短路，保持）。"""
    assert _is_met("", "任意正文") is True
    assert _is_met("   ", "任意正文") is True


# ============================================================
# 第二部分：现状行为快照（B3 dock_generator._outline_line_written）
# ============================================================

from backend.services.adaptive.components.dock_generator import _outline_line_written

# 事故语料形状（同 test_dock_nearby.py 的真实大纲/画布）
_OUTLINE_LINE = "林尘喜欢读书，干着活的期间想到昨天晚上读到的内容，正在发愣，突然被工头打断"
_WRITTEN_NOW = (
    "“一个人的力量是微薄的，世界的洪流不会因你而逆转；但只要你清醒地站着，"
    "你就没有被洪流淹没。”这是林尘昨晚睡前翻书时撇到的话"
)


def test_b3_snapshot_verbatim_line_is_written():
    """大纲行逐字进了正文 → 已写（新旧一致）。"""
    written_later = _WRITTEN_NOW + "\n\n" + _OUTLINE_LINE + "。"
    assert _outline_line_written(_OUTLINE_LINE, written_later) is True


def test_b3_snapshot_unwritten_line_is_not_written():
    """完全没写的拍子 → 未写（新旧一致）。"""
    assert _outline_line_written(_OUTLINE_LINE, _WRITTEN_NOW) is False


def test_b3_snapshot_no_fragment_line_falls_back_written():
    """纯标点行无可判片段 → 按已写跳过（防噪音兜底，保持）。

    注：B3 旧片段过滤表不过滤数字（B1 过滤），数字行不算「无可判片段」。
    """
    assert _outline_line_written("，，，。。。。。", _WRITTEN_NOW) is True


def test_b3_snapshot_generic_trigram_pollution_currently_written():
    """通用三字组污染：行内常见搭配散落正文 → 判未写。

    有意变化（P2 治理）：旧行为「3 字片段过半（1/2）命中即已写」——
    「他发现」「自己没」这类常见三字组散落正文，未写的拍子被误判已写、
    就近节拍跳到更远的拍子（B3 病灶）。新判据：命中率 ≥2/3（此处 3/6）
    → 未写，该拍继续作为就近节拍递给挂件。改前快照断言为 True，
    跑绿后随判据收紧翻转。
    """
    line = "他发现自己没有选择"
    written = "他发现天色已晚，风更大了。她自己没有察觉到袖口被划开。"
    assert _outline_line_written(line, written) is False


# ============================================================
# 第三部分：text_match 共享判据纯函数
# ============================================================

from backend.services.adaptive import text_match


def test_sliding_fragments_filters_and_dedupes():
    frags = text_match.sliding_fragments("他没有告诉任何人真相", size=3, max_fragments=4)
    assert frags == ["他没有", "没有告", "有告诉", "告诉任"]
    # 含标点/数字/空白的窗口被弃
    assert text_match.sliding_fragments("1334年之乱") == ["年之乱"]
    assert text_match.sliding_fragments("，，，。。。") == []
    # 保序去重（重复片段只算一次）
    assert text_match.sliding_fragments("啊啊啊啊啊") == ["啊啊啊"]


def test_fragment_hit_rate_math_and_none():
    text = "主角拿到了那把铜钥匙"
    # 4 片段中 3 命中
    assert text_match.fragment_hit_rate("主角拿到了钥匙", text, max_fragments=4) == 0.75
    # 无可判片段 → None（兜底语义归调用方）
    assert text_match.fragment_hit_rate("1334", text) is None


def test_fragment_hit_rate_tail_window():
    """就近窗口：只看文本尾部 N 字，命中在窗口外不算。"""
    text = "开头他发现了一件旧事。" + " filler" * 10 + " 结尾风平浪静。"
    # 全文：开头片段「他发现」命中
    assert text_match.fragment_hit_rate("他发现旧事", text, max_fragments=2) is not None
    # 只看尾部 20 字：开头命中不在窗口内，命中率归零
    rate = text_match.fragment_hit_rate("他发现旧事", text, max_fragments=2, tail_chars=20)
    assert rate == 0.0


def test_matches_threshold_and_fallbacks():
    text = "他发现天色已晚，风更大了。她自己没有察觉到袖口被划开。"
    # 阈值 2/3 + 1e-9 容差：4/6 命中判真、3/6 判假
    assert text_match.matches("他发现自己没有选择", text, threshold=2 / 3,
                              max_fragments=6, exact_shortcut=False) is False
    text2 = text + "他发现自己没有退路了。"  # 再补一个片段命中 → 4/6
    assert text_match.matches("他发现自己没有选择", text2, threshold=2 / 3,
                              max_fragments=6, exact_shortcut=False) is True
    # 整串捷径
    assert text_match.matches("风更大了", text) is True
    # 无可判片段的兜底由 no_fragments 决定
    assert text_match.matches("1334", text, no_fragments=False) is False
    assert text_match.matches("1334", text, no_fragments=True) is True


def test_matches_empty_item_is_defensive():
    """空条目防御性走 no_fragments（B1 在调用侧短路为已达成）。"""
    assert text_match.matches("", "任意", no_fragments=False) is False


# ============================================================
# 第四部分：B4 canon_watch 词边界出场判定
# ============================================================

from backend.services.adaptive.components import canon_watch


def test_b4_gaoshan_vs_gaoshanshang_pair():
    """「高山」/「高山上」对拍（真实 jieba，B4 病灶案例）。"""
    text = "他站在高山上眺望远方。"
    spans = canon_watch._token_spans(text)
    assert spans is not None
    # 「高山上」读作山不是人：角色名「高山」不算出场
    assert canon_watch._name_in_text("高山", text, spans) is False
    # 三字名「高山上」对齐完整 token 边界（高山|上）→ 出场
    assert canon_watch._name_in_text("高山上", text, spans) is True
    # 人名后是普通词（眺望/说话）→ 出场（各自配套自己的分词）
    text2 = "高山望着山下的云海。"
    spans2 = canon_watch._token_spans(text2)
    assert canon_watch._name_in_text("高山", text2, spans2) is True


def test_b4_real_name_mention_and_straddle():
    spans = canon_watch._token_spans("林尘喜欢读书，明月高悬，山风呼啸。")
    # 生造人名（不在 jieba 词典）：无论切成 [林尘] 还是 [林,尘]，对齐即出场
    assert canon_watch._name_in_text("林尘", "林尘喜欢读书，明月高悬，山风呼啸。", spans) is True
    # 跨词误中：「月高」骑在 明月|高悬 边界上 → 不算
    assert canon_watch._name_in_text("月高", "林尘喜欢读书，明月高悬，山风呼啸。", spans) is False
    # 更长名字被整体盖住：「欧阳明」≠「欧阳明亮」→ 不算（换语料验证）
    spans2 = canon_watch._token_spans("欧阳明亮走了进来。")
    assert canon_watch._name_in_text("欧阳明", "欧阳明亮走了进来。", spans2) is False
    assert canon_watch._name_in_text("欧阳明亮", "欧阳明亮走了进来。", spans2) is True


def test_b4_locative_guard_semantics():
    """方位粘连排除只对人名；「的」所有格不排除。"""
    spans = canon_watch._token_spans("高山的剑压在桌角，玉佩上的裂纹又深了。")
    text = "高山的剑压在桌角，玉佩上的裂纹又深了。"
    # 「高山的剑」= 所有格，是角色被提及的高频句式 → 出场
    assert canon_watch._name_in_text("高山", text, spans) is True
    # 伏笔标签（物件）：「玉佩上」是物确实在场，locative_guard=False → 出场
    assert canon_watch._name_in_text("玉佩", text, spans, locative_guard=False) is True
    # 同一句给人名语义就不同：「玉佩上」的山不是人 → 不出场
    assert canon_watch._name_in_text("玉佩", text, spans, locative_guard=True) is False


def test_b4_jieba_failure_falls_back_to_substring(monkeypatch):
    """jieba 异常回退旧子串行为（柔性红线：感知带宁旧勿炸）。"""
    import sys
    import types

    broken = types.ModuleType("jieba")

    def _boom(text):
        raise RuntimeError("dict corrupted")

    broken.lcut = _boom
    monkeypatch.setitem(sys.modules, "jieba", broken)

    text = "他站在高山上眺望远方。"
    assert canon_watch._token_spans(text) is None
    # spans=None → 回退裸子串（旧行为：误中也误中，宁旧勿炸）
    assert canon_watch._name_in_text("高山", text, None) is True


def test_b4_rule_locked_with_stub_tokenizer(monkeypatch):
    """固定分词锁定词边界规则（不依赖 jieba 词典版本，规则层对拍）。"""
    import sys
    import types

    stub = types.ModuleType("jieba")
    stub.lcut = lambda text: ["他", "站在", "高山", "上", "眺望"]
    monkeypatch.setitem(sys.modules, "jieba", stub)

    spans = canon_watch._token_spans("他站在高山上眺望")
    assert spans == [(0, 1, "他"), (1, 3, "站在"), (3, 5, "高山"),
                     (5, 6, "上"), (6, 8, "眺望")]
    assert canon_watch._name_in_text("高山", "他站在高山上眺望", spans) is False
    assert canon_watch._name_in_text("山上", "他站在高山上眺望", spans) is False
    assert canon_watch._name_in_text("高山上", "他站在高山上眺望", spans) is True
    # spans=None 回退子串：山上 裸命中
    assert canon_watch._name_in_text("山上", "他站在高山上眺望", None) is True
