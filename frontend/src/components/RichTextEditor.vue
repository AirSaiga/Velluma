<script setup>
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import TextAlign from '@tiptap/extension-text-align'
import Underline from '@tiptap/extension-underline'
import Strike from '@tiptap/extension-strike'
import { Color, BackgroundColor } from '@tiptap/extension-text-style'
import Highlight from '@tiptap/extension-highlight'
import Subscript from '@tiptap/extension-subscript'
import Superscript from '@tiptap/extension-superscript'
import { watch, onBeforeUnmount, ref, nextTick } from 'vue'
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

// Extension to fake selection highlighting when editor loses focus
const SelectionHighlighter = Extension.create({
  name: 'selectionHighlighter',

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey('selectionHighlighter'),
        props: {
          decorations(state) {
            const { selection } = state
            // Get current plugin state
            const isHighlightEnabled = this.getState(state)
            
            if (isHighlightEnabled && !selection.empty) {
                return DecorationSet.create(state.doc, [
                    Decoration.inline(selection.from, selection.to, {
                        class: 'fake-selection-highlight',
                    }),
                ])
            }
            return DecorationSet.empty
          },
        },
        state: {
            init() { return false },
            apply(tr, value) {
                const meta = tr.getMeta('setFakeSelection')
                if (meta !== undefined) {
                    return meta
                }
                return value
            }
        }
      }),
    ]
  },
  
  addCommands() {
      return {
          setFakeSelection: (enabled) => ({ tr, dispatch }) => {
              if (dispatch) {
                  tr.setMeta('setFakeSelection', enabled)
              }
              return true
          }
      }
  }
})

const props = defineProps({
  modelValue: {
    type: String,
    default: '',
  },
  placeholder: {
    type: String,
    default: '开始写作...',
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  id: {
    type: [String, Number],
    default: null,
  },
  isFormatting: {
    type: Boolean,
    default: false,
  }
})

const emit = defineEmits(['update:modelValue', 'request-format', 'request-partial-optimize'])

const textColor = ref('#000000')
const highlightColor = ref('#FFFF00')
const editorContainerRef = ref(null)
const showSelectionMenu = ref(false)
const selectionMenuPos = ref({ top: 0, left: 0 })
const optimizationInstruction = ref('')
const currentSelection = ref(null)
const optimizationState = ref('idle') // 'idle' | 'input' | 'processing' | 'reviewing'
const tempOptimizationData = ref(null)

const editor = useEditor({
  content: props.modelValue,
  editable: !props.disabled,
  extensions: [
    StarterKit,
    Placeholder.configure({
      placeholder: props.placeholder,
    }),
    TextAlign.configure({
      types: ['heading', 'paragraph'],
    }),
    Underline,
    Strike,
    Color,
    BackgroundColor,
    Highlight.configure({
      multicolor: true,
    }),
    Subscript,
    Superscript,
    SelectionHighlighter,
  ],
  editorProps: {
    attributes: {
      class: 'prose prose-lg max-w-none mx-auto focus:outline-none min-h-[560px] px-10 py-8 text-[var(--text-primary)]',
    },
  },
  onUpdate: ({ editor }) => {
    emit('update:modelValue', editor.getHTML())
  },
  onSelectionUpdate: ({ editor }) => {
    // 使用 setTimeout 让选择状态稳定
    setTimeout(() => {
      if (!editorContainerRef.value) return

      // 如果正在处理或审核优化，不要更新选区菜单状态（保持菜单显示）
      if (optimizationState.value !== 'idle' && optimizationState.value !== 'input') {
        return
      }

      const { from, to, empty } = editor.state.selection
      
      // 如果没有选择文本，隐藏菜单
      if (empty) {
        showSelectionMenu.value = false
        optimizationState.value = 'idle'
        return
      }

      // 获取选区坐标
      const startCoords = editor.view.coordsAtPos(from)
      const containerRect = editorContainerRef.value.getBoundingClientRect()
      
      // 计算相对坐标
      // 默认显示在选区上方
      let top = startCoords.top - containerRect.top - 50
      let left = startCoords.left - containerRect.left
      
      // 边界检查：防止超出顶部
      if (top < 0) {
        // 如果上方空间不足，显示在下方
        top = startCoords.bottom - containerRect.top + 10
      }
      
      // 边界检查：防止超出左侧
      if (left < 0) left = 0
      // 防止超出右侧 (假设菜单宽度约 300px)
      if (left + 300 > containerRect.width) {
        left = containerRect.width - 300
      }

      selectionMenuPos.value = { top, left }
      
      // 记录当前选区信息
      currentSelection.value = {
        from,
        to,
        text: editor.state.doc.textBetween(from, to),
        contextBefore: editor.state.doc.textBetween(Math.max(0, from - 1000), from),
        contextAfter: editor.state.doc.textBetween(to, Math.min(editor.state.doc.content.size, to + 1000))
      }
      
      showSelectionMenu.value = true
      optimizationState.value = 'input'
    }, 50)
  }
})

watch(() => props.disabled, (val) => {
  editor.value?.setEditable(!val)
})

watch(() => [props.modelValue, props.id], ([newValue, newId], [oldValue, oldId]) => {
  // 1. 如果 ID 变了（切换章节），强制更新内容
  if (newId !== oldId) {
    editor.value.commands.setContent(newValue, false)
    return
  }

  // 2. 如果内容完全一致，不需要更新
  const isSame = editor.value.getHTML() === newValue
  if (isSame) {
    return
  }

  // 3. 如果 ID 没变且内容不一致：
  //    - 如果编辑器有焦点，说明可能是用户正在输入触发的回流，或者是中文输入法中间态
  //      此时不应该更新，否则会打断输入法并重置光标
  //    - 如果编辑器没焦点，说明是外部更新（如自动生成、协同编辑），应该更新
  if (editor.value.isFocused) {
    return
  }

  editor.value.commands.setContent(newValue, false)
})

onBeforeUnmount(() => {
  editor.value.destroy()
})

const toggleBold = () => editor.value.chain().focus().toggleBold().run()
const toggleItalic = () => editor.value.chain().focus().toggleItalic().run()
const toggleUnderline = () => editor.value.chain().focus().toggleUnderline().run()
const toggleStrike = () => editor.value.chain().focus().toggleStrike().run()
const toggleHeading = (level) => editor.value.chain().focus().toggleHeading({ level }).run()

const setTextAlign = (align) => editor.value.chain().focus().setTextAlign(align).run()
const setTextColor = (color) => editor.value.chain().focus().setColor(color).run()
const setHighlightColor = (color) => editor.value.chain().focus().toggleHighlight({ color }).run()
const toggleSubscript = () => editor.value.chain().focus().toggleSubscript().run()
const toggleSuperscript = () => editor.value.chain().focus().toggleSuperscript().run()

let contentBuffer = ''

const insertContent = (content) => {
  if (editor.value) {
    // 1. 标准化换行符：统一将 \r\n 转换为 \n
    let normalizedContent = content.replace(/\r\n/g, '\n')
    
    // 2. 将内容追加到缓冲区
    contentBuffer += normalizedContent
    
    // 3. 处理缓冲区：寻找确定的段落结束标记（双换行）
    if (contentBuffer.includes('\n\n')) {
      // 找到最后一个双换行的位置
      const lastSplitIndex = contentBuffer.lastIndexOf('\n\n')
      
      // 提取可以渲染的完整段落部分
      const toRender = contentBuffer.substring(0, lastSplitIndex)
      
      // 更新缓冲区，只保留剩余部分（跳过那个 \n\n）
      contentBuffer = contentBuffer.substring(lastSplitIndex + 2)
      
      if (toRender) {
        // 分割段落
        const paragraphs = toRender.split(/\n\n+/)
        
        // 生成 HTML：
        // 1. 过滤空段落
        // 2. 移除段落内部的单个换行符 \n（这是关键：避免段落内断行）
        const htmlContent = paragraphs
          .filter(p => p.trim())
          .map(p => `<p>${p.replace(/\n/g, '')}</p>`)
          .join('')
          
        if (htmlContent) {
          editor.value.commands.insertContent(htmlContent)
        }
      }
    }
  }
}

const formatContent = () => {
  if (!editor.value || props.isFormatting) return
  
  // 获取纯文本内容
  const text = editor.value.getText()
  if (!text.trim()) return

  emit('request-format', text)
}

const flushBuffer = () => {
  if (contentBuffer && editor.value) {
    const buffer = contentBuffer.trim()
    if (buffer) {
      if (buffer.includes('<')) {
        // 如果包含 HTML 标签，直接插入
        editor.value.commands.insertContent(buffer)
      } else {
        // 按双换行分割
        const paragraphs = buffer.split(/\n\n+/)
        const htmlContent = paragraphs
          .map(p => `<p>${p.replace(/\n/g, '')}</p>`)
          .join('')
        editor.value.commands.insertContent(htmlContent)
      }
    }
    contentBuffer = ''
  }
}

const clearContent = () => {
  if (editor.value) {
    contentBuffer = ''
    editor.value.commands.clearContent()
  }
}

const handleInputFocus = () => {
  if (editor.value && showSelectionMenu.value && optimizationState.value === 'input') {
    editor.value.commands.setFakeSelection(true)
  }
}

const handleInputBlur = () => {
  if (editor.value && optimizationState.value === 'input') {
    editor.value.commands.setFakeSelection(false)
  }
}

const handleOptimizeSelection = () => {
  if (!currentSelection.value || !optimizationInstruction.value.trim()) return
  
  optimizationState.value = 'processing'
  
  emit('request-partial-optimize', {
    selection: currentSelection.value,
    instruction: optimizationInstruction.value
  })
  
  // 不要清空 instruction，也不要关闭菜单
  // optimizationInstruction.value = '' 
  // showSelectionMenu.value = false
}

const applyOptimizationDiff = (optimizedText) => {
  if (!editor.value || !currentSelection.value) return

  optimizationState.value = 'reviewing'
  editor.value.commands.setFakeSelection(false) // 移除伪造的高亮

  const { from, to } = currentSelection.value
  
  // 1. 标记原文 (Strike + Red Highlight)
  editor.value.chain()
    .setTextSelection({ from, to })
    .setStrike()
    .setHighlight({ color: '#ffcccc' })
    .run()

  // 2. 插入新文 (Green Highlight)
  // 注意：插入后位置会变，需要计算
  const insertPos = to
  editor.value.chain()
    .insertContentAt(insertPos, optimizedText)
    .setTextSelection({ from: insertPos, to: insertPos + optimizedText.length })
    .unsetStrike()
    .setHighlight({ color: '#ccffcc' })
    .run()

  // 记录临时数据以便确认/取消
  tempOptimizationData.value = {
    originalFrom: from,
    originalTo: to,
    newFrom: to, // 原文之后
    newTo: to + optimizedText.length
  }
}

const confirmOptimization = () => {
  if (!editor.value || !tempOptimizationData.value) return

  const { originalFrom, originalTo, newFrom, newTo } = tempOptimizationData.value

  // 1. 清除新文的高亮
  editor.value.chain()
    .setTextSelection({ from: newFrom, to: newTo })
    .unsetHighlight()
    .run()

  // 2. 删除原文
  editor.value.chain()
    .deleteRange({ from: originalFrom, to: originalTo })
    .run()

  resetOptimization()
}

const rejectOptimization = () => {
  if (!editor.value || !tempOptimizationData.value) return

  const { originalFrom, originalTo, newFrom, newTo } = tempOptimizationData.value

  // 1. 删除新文
  editor.value.chain()
    .deleteRange({ from: newFrom, to: newTo })
    .run()

  // 2. 恢复原文样式 (移除 Strike 和 Highlight)
  editor.value.chain()
    .setTextSelection({ from: originalFrom, to: originalTo })
    .unsetStrike()
    .unsetHighlight()
    .run()

  resetOptimization()
}

const resetOptimization = () => {
  optimizationState.value = 'idle'
  showSelectionMenu.value = false
  optimizationInstruction.value = ''
  currentSelection.value = null
  tempOptimizationData.value = null
  if (editor.value) {
    editor.value.commands.setFakeSelection(false)
  }
}

defineExpose({
  insertContent,
  clearContent,
  flushBuffer,
  editor,
  applyOptimizationDiff,
  resetOptimization
})
</script>

<template>
  <div ref="editorContainerRef" class="rich-text-editor bg-white overflow-hidden flex flex-col h-full relative" :class="{ 'opacity-60': disabled }">
    <div v-if="editor && !disabled" class="toolbar flex items-center gap-0.5 px-3 py-1.5 bg-white border-b border-[var(--border-color)] overflow-x-auto whitespace-nowrap flex-shrink-0">
      <button 
        @click="toggleBold" 
        :class="{ 'is-active': editor.isActive('bold') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="加粗"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h8a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path><path d="M6 12h9a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path></svg>
      </button>
      <button 
        @click="toggleItalic" 
        :class="{ 'is-active': editor.isActive('italic') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="斜体"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="4" x2="10" y2="4"></line><line x1="14" y1="20" x2="5" y2="20"></line><line x1="15" y1="4" x2="9" y2="20"></line></svg>
      </button>
      <button 
        @click="toggleUnderline" 
        :class="{ 'is-active': editor.isActive('underline') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="下划线"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3v7a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3"></path><line x1="4" y1="21" x2="20" y2="21"></line></svg>
      </button>
      <button 
        @click="toggleStrike" 
        :class="{ 'is-active': editor.isActive('strike') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="删除线"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.3 4.9c-2.3-.6-4.4-1-6.2-.9-2.7 0-5.3.7-5.3 3.6 0 1.5 1.8 3.3 3.6 3.9h.2"></path><path d="M8.7 19.1c2.3.6 4.4 1 6.2.9 2.7 0 5.3-.7 5.3-3.6 0-1.5-1.8-3.3-3.6-3.9h-.2"></path><line x1="3" y1="12" x2="21" y2="12"></line></svg>
      </button>
      <button 
        @click="formatContent" 
        :class="{ 'opacity-50 cursor-not-allowed': isFormatting }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors relative"
        title="智能格式整理（AI分段、标点修正）"
      >
        <svg v-if="!isFormatting" xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/><path d="M5 3v4"/><path d="M9 3v4"/><path d="M3 5h4"/><path d="M3 9h4"/></svg>
        <svg v-else class="animate-spin" xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <label class="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-[var(--hover-bg)] transition-colors cursor-pointer" title="文字颜色">
        <input
          type="color"
          v-model="textColor"
          @input="setTextColor($event.target.value)"
          class="w-4 h-4 p-0 border-0 bg-transparent cursor-pointer"
        />
      </label>
      <label class="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-[var(--hover-bg)] transition-colors cursor-pointer" title="背景高亮">
        <input
          type="color"
          v-model="highlightColor"
          @input="setHighlightColor($event.target.value)"
          class="w-4 h-4 p-0 border-0 bg-transparent cursor-pointer"
        />
      </label>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="setTextAlign('left')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'left' }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="左对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="9" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('center')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'center' }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="居中"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="18" y1="12" x2="6" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('right')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'right' }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="右对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="15" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('justify')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'justify' }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="两端对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="3" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line><line x1="21" y1="6" x2="21" y2="18"></line></svg>
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="toggleSuperscript" 
        :class="{ 'is-active': editor.isActive('superscript') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="上标"
      >
        X<sup>2</sup>
      </button>
      <button 
        @click="toggleSubscript" 
        :class="{ 'is-active': editor.isActive('subscript') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="下标"
      >
        X<sub>2</sub>
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="toggleHeading(1)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 1 }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 1"
      >
        H1
      </button>
      <button 
        @click="toggleHeading(2)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 2 }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 2"
      >
        H2
      </button>
      <button 
        @click="toggleHeading(3)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 3 }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 3"
      >
        H3
      </button>
    </div>
    
    <editor-content :editor="editor" class="flex-1 overflow-y-auto custom-scrollbar" />

    <!-- Selection Optimization Menu -->
    <div 
      v-if="showSelectionMenu"
      :style="{ top: selectionMenuPos.top + 'px', left: selectionMenuPos.left + 'px' }"
      class="absolute z-50 bg-white shadow-lg border border-[var(--border-color)] rounded-lg p-2 flex items-center gap-2"
      @mousedown.stop
    >
      <template v-if="optimizationState === 'input'">
        <input 
          v-model="optimizationInstruction"
          @focus="handleInputFocus"
          @blur="handleInputBlur"
          @keydown.enter="handleOptimizeSelection"
          placeholder="输入优化建议..."
          class="text-sm border border-[var(--border-color)] rounded px-2 py-1 outline-none focus:border-[var(--accent-600)] w-64 text-[var(--text-primary)] bg-white"
        />
        <button 
          @click="handleOptimizeSelection" 
          class="text-[var(--accent-600)] hover:text-[var(--accent-700)] p-1 rounded hover:bg-[var(--hover-bg)] transition-colors"
          title="执行优化"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
        </button>
      </template>

      <template v-else-if="optimizationState === 'processing'">
        <div class="flex items-center gap-2 px-2 text-sm text-[var(--text-muted)]">
          <svg class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <span>优化生成中...</span>
        </div>
      </template>

      <template v-else-if="optimizationState === 'reviewing'">
        <button 
          @click="confirmOptimization"
          class="px-3 py-1 text-xs bg-emerald-50 text-emerald-600 hover:bg-emerald-100 rounded border border-emerald-200 transition-colors"
        >
          使用新版
        </button>
        <button 
          @click="rejectOptimization"
          class="px-3 py-1 text-xs bg-slate-50 text-slate-600 hover:bg-slate-100 rounded border border-slate-200 transition-colors"
        >
          保留原版
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.rich-text-editor .is-active {
  background-color: rgba(99, 102, 241, 0.12);
  color: var(--accent-600);
}

/* Custom Scrollbar for Editor Content */
  .custom-scrollbar::-webkit-scrollbar {
    width: 6px;
  }
  .custom-scrollbar::-webkit-scrollbar-track {
    background: transparent;
  }
  .custom-scrollbar::-webkit-scrollbar-thumb {
    background-color: var(--border-color);
    border-radius: 3px;
  }
  .custom-scrollbar::-webkit-scrollbar-thumb:hover {
    background-color: var(--text-muted);
  }
  
  /* Tiptap Prose Customization */
  :deep(.ProseMirror) {
    height: 100%;
    outline: none;
    font-family: 'Songti SC', 'STSong', 'Noto Serif SC', 'Source Han Serif SC', Georgia, serif;
    font-size: 1.15rem;
    line-height: 1.95;
    /* Move padding to ProseMirror for internal scrolling if needed, but here we rely on parent's overflow */
  }
:deep(.ProseMirror p.is-editor-empty:first-child::before) {
  color: var(--text-muted);
  content: attr(data-placeholder);
  float: left;
  height: 0;
  pointer-events: none;
}
:deep(.fake-selection-highlight) {
  background-color: #b4d5fe;
}
</style>
