# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""publish_chapter 世界书 legacy 提取止血锁（2026-09-04 审计修复）。

背景：发布链每章都向 characters/character_relationships/chapter_entities 写
AI 影子数据——读侧 world 优先看不见，migrate-legacy 时整批涌入 world_entities。
修复后世界书（world_entities 非空，与 world_bridge 兜底判据同源）必须跳过
`execute_character_extraction_workflow`。本锁用 AST 断言结构不回退：
1. 存在 `book_has_world` 门；
2. 提取工作流调用只在该门的 orelse（非世界书分支）内；
3. 判据走 WorldRepository.entities.list_by_book（同源，不许另立口径）。
"""
import ast
import unittest
from pathlib import Path

SRC = (Path(__file__).parent / "chapter_publishing.py").read_text(encoding="utf-8")


def _publish_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "publish_chapter":
            return node
    raise AssertionError("publish_chapter 不见了")


def _calls(node: ast.AST, names: set) -> list:
    """匹配 Name 与 Attribute 两种调用形态（repo.entities.list_by_book(...) 是 Attribute）。"""
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Name) and n.func.id in names:
            out.append(n)
        elif isinstance(n.func, ast.Attribute) and n.func.attr in names:
            out.append(n)
    return out


def _wrap(body: list) -> ast.Module:
    return ast.Module(body=body, type_ignores=[])


class TestWorldExtractionGate(unittest.TestCase):
    def test_book_has_world_gate_exists(self):
        fn = _publish_fn()
        gates = [
            s for s in ast.walk(fn)
            if isinstance(s, ast.If)
            and any(isinstance(n, ast.Name) and n.id == "book_has_world"
                    for n in ast.walk(s.test))
        ]
        self.assertEqual(len(gates), 1, "book_has_world 世界书门缺失或重复")

    def test_extraction_only_in_non_world_branch(self):
        fn = _publish_fn()
        gate = next(
            s for s in ast.walk(fn)
            if isinstance(s, ast.If)
            and any(isinstance(n, ast.Name) and n.id == "book_has_world"
                    for n in ast.walk(s.test))
        )
        # 世界书分支（body）内不得出现 legacy 提取调用（⚠ elif 挂在 orelse，
        # 不能 walk 整个 gate 节点，只查 body）
        self.assertEqual(
            _calls(_wrap(gate.body), {"execute_character_extraction_workflow"}), [],
            "世界书分支仍在跑 legacy 人物提取（影子数据写入旧表）",
        )
        # 非世界书分支（orelse）保留旧路径（未迁移书行为不变）
        self.assertGreaterEqual(
            len(_calls(_wrap(gate.orelse), {"execute_character_extraction_workflow"})), 1,
            "orelse 丢失 legacy 提取——未迁移书的提取能力被误删",
        )

    def test_criterion_is_world_repo_same_source(self):
        fn = _publish_fn()
        self.assertTrue(
            _calls(fn, {"list_by_book"}),
            "判据未走 WorldRepository.entities.list_by_book（与 world_bridge 兜底同源红线）",
        )
        self.assertTrue(
            _calls(fn, {"WorldRepository"}),
            "应复用 WorldRepository 构造判据，不许另立口径",
        )


if __name__ == "__main__":
    unittest.main()
