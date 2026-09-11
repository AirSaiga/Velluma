# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""跨模块 relationship 挂接：Book/Chapter ↔ GenerationTask 的双向关联。

原单文件里的类后挂接（明确指定 foreign_keys 避免歧义）；拆包后 Book/Chapter 在
narrative、GenerationTask 在 generation，挂接收敛到本模块——由 __init__ 在全部
子模块加载后最后 import（字符串目标经 registry 惰性解析，与文件布局无关）。
"""
from sqlalchemy.orm import relationship

from .narrative import Book, Chapter

# 更新关联关系 - 明确指定 foreign_keys 避免歧义
Book.generation_tasks = relationship(
    'GenerationTask', 
    back_populates='book', 
    cascade='all, delete-orphan',
    foreign_keys='GenerationTask.book_id'
)
Chapter.generation_tasks = relationship(
    'GenerationTask', 
    back_populates='chapter', 
    cascade='all, delete-orphan',
    foreign_keys='GenerationTask.chapter_id'
)
