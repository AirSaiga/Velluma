# Velluma - NLE-ADF 3.0 「作者当前段落」/「已写内容」取源
# AGPL-3.0
"""
adaptive 组件共用的画布取源口径。

两个概念、一个原则：
- 「作者当前段落」（dock_generator / canon_watch）：实时段 → 画布尾部；
- 「本章已写内容」（future_projection / intent_inference / post_process /
  direction_weights 推动力）：画布全文（剥 HTML）。

原则：画布即事实源。层 1 已写事实（layer1_facts）只是沉淀审计账，
作者删改重写后即过期，永远不得代替正文进 prompt / 审阅对象 / 已达成判定
（2026-08 事故：9 天前已删除的战斗段落被 facts[-1] 顶替「当前段落」，
挂件全部锚定不存在的文本；完稿体检也曾审阅 facts 拼接而非真实正文）。

事实活性（world_model.snapshot 消费）：派生判定，不回写——规范化文本
仍是画布全文子串 = 活，否则过期。作者把删掉的段落贴回来，事实自动复活。
"""
from __future__ import annotations

import re

# 与组件侧「正文不足」闸同阈值：不足此长度的段落不参与生发/感知
MIN_PARAGRAPH_CHARS = 30


def resolve_current_paragraph(live_recent: str, content_html: str) -> str:
    """取「作者当前段落」尾部（≤500 字）。

    优先心跳实时段（前端光标段纯文本）；不足时回退画布尾部（剥 HTML）。
    两层来源都不足 MIN_PARAGRAPH_CHARS 时返回空串，调用方按「正文不足」跳过。
    """
    live = (live_recent or "").strip()
    if len(live) >= MIN_PARAGRAPH_CHARS:
        return live[-500:]
    plain = written_text(content_html)
    if len(plain) >= MIN_PARAGRAPH_CHARS:
        return plain[-500:]
    return ""


def written_text(content_html: str) -> str:
    """「本章已写内容」唯一口径：画布全文剥 HTML（与 memory_indexing 同则）。

    段落间至多一个空行；尾部空段落（作者狂按回车的 <p></p> 汤）自然剥除。
    """
    plain = re.sub(r"<[^>]+>", "\n", content_html or "")
    return re.sub(r"\n{3,}", "\n\n", plain).strip()


def normalize_for_match(text: str) -> str:
    """活性比对用的规范化：抹掉全部空白（HTML 转纯文本的换行不干扰子串判定）。"""
    return re.sub(r"\s+", "", text or "")


# 句末终止标点（含引文/括号收尾——段尾是收尾引号几乎必是完整句）
_SENTENCE_TERMINALS = set('。！？!?…‥．。”」』）)')


def ends_mid_sentence(text: str) -> bool:
    """段落尾部句子是否未写完（挂件句子级闸门）。

    半句悬着时作者要做的是把句子写完（Space 幽灵续写的活），此时推
    新画面全是噪音。最后一个非空白字符不是句末标点即视为未完。

    空段（含纯空白）返回 False：没有悬着的句子就不是半句——写完一段
    回车进新空段正是「下一段写什么」的段界时刻，挂件应正常出件
    （锚定文本由 resolve_current_paragraph 回退画布尾）。若把空段当
    半句，段界停顿会误杀挂件（2026-08-25 审计发现，勿回退）。
    """
    t = (text or "").rstrip()
    return bool(t) and (t[-1] not in _SENTENCE_TERMINALS)
