# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 书级专名注入 jieba 用户词典（2026-09-17 词法精度加固）
"""
把世界实体的正名+别名注入 jieba 用户词典（高频压制默认碎切）。

动机：jieba 默认词典不认识书级专名，分词漂移会把「明姐端来」切成
「明姐端」这类伪 token——所有吃 jieba 的链路（guest 提名 posseg /
token 边界匹配 / 词法检索）精度都被拖累。注入后专名恒为单 token：

- guest 提名（dock_generator.detect_guest_names 的 posseg NR）召回更稳；
- token 边界匹配（连续 token 拼接恰为该词）对专名稳定命中；
- rag 词法检索的关键词抽取质量间接受益。

纪律：
- jieba 是进程级单例，词典全局生效（单机桌面应用，无多租户隔离需求）；
- add_word 幂等（同词重复注册仅覆盖词频），各入口在实体加载后顺手重注，
  代价可忽略；
- 只收 ≥2 字的词——1 字词注入会把一切单字切分绑死，误伤面太大；
- jieba 缺失静默返回 0（全部消费方本就有降级路径）。
"""
from __future__ import annotations

from typing import Any, Iterable

# 高频压制默认切分：足够让专名在 DAG 路径里恒胜默认碎切
_TERM_FREQ = 20000


def register_terms(terms: Iterable[str]) -> int:
    """把词表注入 jieba 用户词典，返回注入条数。jieba 缺失静默返回 0。"""
    try:
        import jieba
    except Exception:
        return 0
    n = 0
    for raw in terms or []:
        term = str(raw or "").strip()
        if len(term) < 2:
            continue
        try:
            jieba.add_word(term, freq=_TERM_FREQ)
            n += 1
        except Exception:
            pass  # 单词注册失败不阻塞其余
    return n


def register_entity_terms(entities: Iterable[Any]) -> int:
    """实体正名 + 别名全量注入（鸭子类型：读 name/aliases）。"""
    terms = []
    for e in entities or []:
        name = str(getattr(e, "name", "") or "").strip()
        if name:
            terms.append(name)
        for a in getattr(e, "aliases", None) or []:
            alias = str(a or "").strip()
            if alias:
                terms.append(alias)
    return register_terms(terms)
