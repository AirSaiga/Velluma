import { shallowRef } from 'vue'
import type { Editor } from '@tiptap/vue-3'

/**
 * 章节编辑器实例的全局句柄（单编辑器桌面应用）。
 *
 * 存在原因：生成会话层（useGenerationSession）的幽灵草稿/Spark Dock 控制器
 * 需要直接操作 TipTap 文档，而编辑器实例藏在
 * WorkspaceView → ChapterEditor → ChapterEditorContainer → ChapterEditorView
 * → RichTextEditor 四层之下，prop 钻取会把生成逻辑泄漏进通用组件。
 * 本模块以单例句柄解耦：RichTextEditor 挂载时注册、卸载时清空。
 *
 * 约束：全应用同时只有一个章节编辑器（桌面单窗单文档成立）。
 */
export const chapterEditorHandle = shallowRef<Editor | null>(null)

export function registerChapterEditor(editor: Editor | null): void {
  chapterEditorHandle.value = editor
}
