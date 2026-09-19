# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - jieba_lexicon 词典注入单测（2026-09-17 词法精度加固）
"""
注入纪律锁：正名+别名全量注入、1 字词不注（防绑死单字切分）、幂等。
"""
from types import SimpleNamespace

import jieba

from backend.services.world.jieba_lexicon import register_entity_terms, register_terms


def _ent(name, aliases=None):
    return SimpleNamespace(name=name, aliases=aliases or [])


def test_register_entity_terms_names_and_aliases():
    n = register_entity_terms([_ent("云漪", ["阿漪"]), _ent("", ["  "]), None])
    assert n == 2
    tokens = list(jieba.cut("云漪和阿漪走进来"))
    assert "云漪" in tokens
    assert "阿漪" in tokens


def test_register_terms_skips_single_char():
    assert register_terms(["风", "", None]) == 0


def test_register_terms_idempotent():
    assert register_terms(["明姐"]) == 1
    assert register_terms(["明姐"]) == 1  # 重复注册仅覆盖词频
