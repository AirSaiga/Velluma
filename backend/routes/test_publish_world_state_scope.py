# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""publish_chapter 世界状态提取作用域锁（2026-09-01 审计轮）。

背景：世界终端状态提取块（150s 超时的整章 LLM 调用）曾被误缩进进
`for result in cp33_update_results:` 循环体——每有一条角色状态变更就重跑
一次整章提取（N 角色 = N 次调用），且零变更时世界快照整段跳过。该块全部
依赖都是章级变量，纯缩进事故，已修。本锁用 AST 断言结构不回退：角色状态
循环体必须只剩 append，text_to_summarize 门必须存在于函数体层级。
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


class TestWorldStateBlockScope(unittest.TestCase):
    def test_world_state_not_inside_character_updates_loop(self):
        fn = _publish_fn()
        loops = [
            n for n in fn.body
            if isinstance(n, ast.For) and isinstance(n.iter, ast.Name)
            and n.iter.id == "cp33_update_results"
        ]
        self.assertEqual(len(loops), 1)
        kinds = [type(s).__name__ for s in loops[0].body]
        self.assertEqual(
            kinds, ["Expr"],
            "世界状态提取块缩进回了角色状态循环（每角色重跑一次 LLM 提取）",
        )

    def test_chapter_level_gates_exist(self):
        fn = _publish_fn()
        gates = [
            s for s in fn.body
            if isinstance(s, ast.If) and isinstance(s.test, ast.Name)
            and s.test.id == "text_to_summarize"
        ]
        # 摘要门 + 世界状态门：至少两个章级 if text_to_summarize
        self.assertGreaterEqual(len(gates), 2, "章级 text_to_summarize 门缺失")


if __name__ == "__main__":
    unittest.main()
