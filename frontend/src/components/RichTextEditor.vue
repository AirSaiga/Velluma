<script setup>
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import BubbleMenuExtension from '@tiptap/extension-bubble-menu'
import Placeholder from '@tiptap/extension-placeholder'
  import TextAlign from '@tiptap/extension-text-align'
  import Underline from '@tiptap/extension-underline'
  import Strike from '@tiptap/extension-strike'
  import TextStyle from '@tiptap/extension-text-style'
  import Color from '@tiptap/extension-color'
  import Highlight from '@tiptap/extension-highlight'
  import Subscript from '@tiptap/extension-subscript'
  import Superscript from '@tiptap/extension-superscript'
  import { AuditHighlightMark } from '../extensions/AuditHighlightMark'
  import { watch, onBeforeUnmount, onMounted, ref, nextTick, computed } from 'vue'
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { bookApi } from '../services/api/domain'
import Icon from './Icon.vue'
import { useToast } from '../composables/useToast'

const { showToast } = useToast()

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
  },
  bookId: {
    type: String,
    default: null,
  }
})

const emit = defineEmits(['update:modelValue', 'request-format', 'request-partial-optimize', 'entity-focus-change'])

const textColor = ref('#000000')
const highlightColor = ref('#FFFF00')
const AI_INTENT_MODE_STORAGE_KEY = 'velluma_ai_intent_mode'
const editorContainerRef = ref(null)
const selectionMenuRef = ref(null)
const showSelectionMenu = ref(false)
const selectionMenuPos = ref({ top: 0, left: 0 })
const optimizationInstruction = ref('')
const currentSelection = ref(null)
const optimizationState = ref('idle') // 'idle' | 'toolbar' | 'input' | 'processing' | 'reviewing'
const tempOptimizationData = ref(null)
const aiInstructionInputRef = ref(null)
// CP4.1 选区级改写（蓝图 §4.9）：5 种模式
// FE 内部用 'polish'（向后兼容 localStorage），映射到 BE mode='rewrite'
// 其他 4 种 FE/BE 一致：describe / expand / compress / tone_shift
const readStoredAiIntentMode = () => {
  try {
    const raw = localStorage.getItem(AI_INTENT_MODE_STORAGE_KEY)
    if (raw === 'polish' || raw === 'expand' || raw === 'compress' || raw === 'describe' || raw === 'tone_shift') {
      return { mode: raw, fromStorage: true }
    }
  } catch {}
  return { mode: 'polish', fromStorage: false }
}

const storedAiIntentMode = readStoredAiIntentMode()
const aiIntentMode = ref(storedAiIntentMode.mode)
const hasStoredAiIntentMode = ref(storedAiIntentMode.fromStorage)
// CP4.1：tone_shift 模式的目标语气（如 冷峻 / 诙谐 / 抒情）
const aiToneInput = ref('')
const showUndoHint = ref(false)
const lastAppliedOptimization = ref(null)
let undoHintTimer = null
let selectionDebounceTimer = null
const pendingExternalUpdate = ref(null)

const hasSelection = computed(() => {
  if (!editor.value) return false
  const { from, to } = editor.value.state.selection
  return from !== to
})

const getSelectedText = () => {
  if (!editor.value) return ''
  const { from, to } = editor.value.state.selection
  if (from === to) return ''
  return editor.value.state.doc.textBetween(from, to, ' ')
}

async function addToGoldenSnippets() {
  const selectedText = getSelectedText()
  if (!selectedText) {
    showToast('请先选中要添加的文本', 'warning')
    return
  }
  if (!props.bookId) {
    showToast('需要先打开书籍', 'warning')
    return
  }
  try {
    const currentBook = await bookApi.get(props.bookId)
    const currentSnippets = currentBook.golden_snippets || []
    currentSnippets.push(selectedText)
    await bookApi.update(props.bookId, { golden_snippets: currentSnippets })
    showToast('已添加到黄金锚点', 'success')
  } catch (e) {
    console.error('添加黄金片段失败:', e)
    showToast('添加失败: ' + (e.message || '未知错误'), 'error')
  }
}

async function addToBlacklist() {
  const selectedText = getSelectedText()
  if (!selectedText) {
    showToast('请先选中要添加的文本', 'warning')
    return
  }
  if (!props.bookId) {
    showToast('需要先打开书籍', 'warning')
    return
  }
  try {
    const currentBook = await bookApi.get(props.bookId)
    const currentBlacklist = currentBook.style_blacklist || []
    currentBlacklist.push(selectedText)
    await bookApi.update(props.bookId, { style_blacklist: currentBlacklist })
    showToast('已添加到黑名单', 'success')
  } catch (e) {
    console.error('添加黑名单失败:', e)
    showToast('添加失败: ' + (e.message || '未知错误'), 'error')
  }
}

const SELECTION_DEBOUNCE_MS = 600
const UNDO_HINT_DURATION_MS = 4500

const detectEntityAroundCursor = (editor, from) => {
  const start = Math.max(0, from - 24)
  const end = Math.min(editor.state.doc.content.size, from + 24)
  const before = editor.state.doc.textBetween(start, from)
  const after = editor.state.doc.textBetween(from, end)
  const merged = `${before}${after}`
  const cursorIndex = before.length
  const matcher = /[\u4e00-\u9fa5A-Za-z0-9_]{2,}/g
  let picked = ''
  let bestDistance = Number.POSITIVE_INFINITY
  let token
  while ((token = matcher.exec(merged)) !== null) {
    const tokenStart = token.index
    const tokenEnd = token.index + token[0].length
    const distance = tokenStart <= cursorIndex && cursorIndex <= tokenEnd
      ? 0
      : Math.min(Math.abs(cursorIndex - tokenStart), Math.abs(cursorIndex - tokenEnd))
    if (distance < bestDistance) {
      bestDistance = distance
      picked = token[0]
    }
  }
  return picked
}

const emitEntityFocus = (keyword = '') => {
  const normalized = (keyword || '').trim()
  emit('entity-focus-change', normalized)
}

const handleSelectionMenuOutsidePress = (event) => {
  if (!showSelectionMenu.value) return
  const target = event.target
  const menuEl = selectionMenuRef.value
  const containerEl = editorContainerRef.value
  
  // 如果点击的是菜单本身，不做处理
  if (menuEl && menuEl.contains(target)) return
  
  // 如果点击的是编辑器内部
  if (containerEl && containerEl.contains(target)) {
    // 如果处于审核状态，点击编辑器内部视为放弃优化（恢复原文）
    if (optimizationState.value === 'reviewing') {
      rejectOptimization()
      return
    }
    // 其他状态（toolbar/input）保持菜单显示
    return
  }
  
  // 点击编辑器外部 -> 执行退出逻辑
  handleEscapeShortcut()
}

const clearUndoHint = () => {
  if (undoHintTimer) {
    clearTimeout(undoHintTimer)
    undoHintTimer = null
  }
  showUndoHint.value = false
}

const inferAiIntentMode = () => {
  const selectedText = (currentSelection.value?.text || '').trim()
  const length = selectedText.length
  if (!selectedText) return 'polish'
  if (length < 36) return 'expand'
  if (length > 180) return 'compress'
  if (/[“”'「」『』]/.test(selectedText)) return 'polish'
  return 'polish'
}

// CP4.1：FE 内部 mode → BE mode 映射（polish → rewrite，其余一致）
const feToBeMode = (feMode) => {
  if (feMode === 'polish') return 'rewrite'
  return feMode  // describe / expand / compress / tone_shift 直传
}

const getAiIntentLabel = (mode = aiIntentMode.value) => {
  if (mode === 'expand') return '扩写'
  if (mode === 'compress') return '压缩'
  if (mode === 'describe') return '描写'
  if (mode === 'tone_shift') return '换语气'
  return '润色'  // polish
}

const getDynamicInstructionPlaceholder = () => {
  if (aiIntentMode.value === 'expand') {
    return '扩写方向：补充细节、情绪与动作（Enter 执行）'
  }
  if (aiIntentMode.value === 'compress') {
    return '压缩方向：保留关键信息并提升节奏（Enter 执行）'
  }
  if (aiIntentMode.value === 'describe') {
    return '描写方向：扩充感官细节（视/听/嗅/触），不推进情节（Enter 执行）'
  }
  if (aiIntentMode.value === 'tone_shift') {
    return '换语气：在上方输入目标语气（如 冷峻/诙谐/抒情），此处可补充细节（Enter 执行）'
  }
  return '润色方向：优化语气、描写和句式（Enter 执行）'
}

/**
 * 纯文本 → 段落 HTML 归一化（V3.1 格式修复）。
 *
 * 生成管线产出的是带 \n\n 的纯文本；TipTap setContent 按 HTML 解析时换行会被
 * 折叠为空格，导致全文粘连。注入编辑器前统一转换：
 * - 已是 HTML（含块级标签）→ 原样返回（编辑器保存的 getHTML、历史章节）
 * - 纯文本 → 按 \n\n 切段包 <p>（段内单 \n 去除，与 insertContent 既有逻辑一致）
 */
function normalizeToHtml(value) {
  if (!value || typeof value !== 'string') return value
  if (/<\s*(p|h[1-6]|div|ul|ol|li|blockquote|table|hr)\b/i.test(value)) return value
  if (!value.includes('\n')) return value
  return value
    .split(/\n\n+/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => `<p>${p.replace(/\n/g, '')}</p>`)
    .join('')
}

const editor = useEditor({
  content: normalizeToHtml(props.modelValue),
  editable: !props.disabled,
  extensions: [
    StarterKit.configure({
      history: false,
    }),
    BubbleMenuExtension.configure({
      pluginKey: 'bubbleMenu',
    }),
    Placeholder.configure({
      placeholder: props.placeholder,
    }),
    TextAlign.configure({
      types: ['heading', 'paragraph'],
    }),
    Underline,
    Strike,
    TextStyle,
    Color,
    Highlight.configure({
      multicolor: true,
    }),
    Subscript,
    Superscript,
    SelectionHighlighter,
    AuditHighlightMark,
  ],
  editorProps: {
    attributes: {
      class: 'prose prose-lg max-w-3xl mx-auto focus:outline-none min-h-[560px] px-12 py-10 text-[var(--text-primary)] leading-[2.0]',
    },
  },
  onUpdate: ({ editor }) => {
    emit('update:modelValue', editor.getHTML())
  },
  onBlur: ({ editor }) => {
    applyPendingExternalUpdate()
  },
  onSelectionUpdate: ({ editor }) => {
    // 如果正在处理或审核优化，不要更新选区菜单状态
    if (['processing', 'reviewing'].includes(optimizationState.value)) {
      return
    }

    // 清除上一次的防抖计时器
    if (selectionDebounceTimer) {
      clearTimeout(selectionDebounceTimer)
      selectionDebounceTimer = null
    }

    const { from, to, empty } = editor.state.selection
    
    // 如果没有选择文本，隐藏菜单
    if (empty) {
      showSelectionMenu.value = false
      optimizationState.value = 'idle'
      emitEntityFocus(detectEntityAroundCursor(editor, from))
      return
    }

    // 选中文本后，使用防抖逻辑延迟显示菜单
    selectionDebounceTimer = setTimeout(() => {
      // 再次检查编辑器状态
      if (!editorContainerRef.value || !editor.isEditable) return
      
      // 如果状态变了，不再处理
      if (['processing', 'reviewing'].includes(optimizationState.value)) return
      
      const current = editor.state.selection
      
      // 1. 如果现在变成空选区了，不显示
      if (current.empty) {
        showSelectionMenu.value = false
        optimizationState.value = 'idle'
        return
      }
      
      // 3. 执行显示逻辑
      const startCoords = editor.view.coordsAtPos(current.from)
      const containerRect = editorContainerRef.value.getBoundingClientRect()
      
      let top = startCoords.top - containerRect.top - 50
      let left = startCoords.left - containerRect.left
      
      if (top < 0) top = startCoords.bottom - containerRect.top + 10
      if (left < 0) left = 0
      if (left + 300 > containerRect.width) left = containerRect.width - 300

      selectionMenuPos.value = { top, left }
      
      currentSelection.value = {
          from: current.from,
          to: current.to,
          text: editor.state.doc.textBetween(current.from, current.to),
          contextBefore: editor.state.doc.textBetween(Math.max(0, current.from - 1000), current.from),
          contextAfter: editor.state.doc.textBetween(current.to, Math.min(editor.state.doc.content.size, current.to + 1000))
      }
      
      showSelectionMenu.value = true
      optimizationState.value = 'toolbar'
      emitEntityFocus(currentSelection.value.text)
    }, SELECTION_DEBOUNCE_MS) // 延迟以确保选区稳定
  }
})

watch(() => props.disabled, (val) => {
  editor.value?.setEditable(!val)
})

watch(aiIntentMode, (mode) => {
  hasStoredAiIntentMode.value = true
  try {
    localStorage.setItem(AI_INTENT_MODE_STORAGE_KEY, mode)
  } catch {}
})

watch(() => [props.modelValue, props.id], ([newValue, newId], [oldValue, oldId]) => {
  // 统一先归一化：生成文本（纯文本 \n\n）→ 段落 HTML；已是 HTML 则原样
  const normalizedValue = normalizeToHtml(newValue)

  // 1. 如果 ID 变了（切换章节），强制更新内容
  if (newId !== oldId) {
    editor.value.commands.setContent(normalizedValue, false)
    pendingExternalUpdate.value = null
    return
  }

  // 2. 如果内容完全一致，不需要更新
  const isSame = editor.value.getHTML() === normalizedValue
  if (isSame) {
    pendingExternalUpdate.value = null
    return
  }

  // 3. 如果 ID 没变且内容不一致：
  //    - 如果编辑器有焦点，说明可能是用户正在输入触发的回流，或者是中文输入法中间态
  //      此时不应该更新，否则会打断输入法并重置光标
  //    - 如果编辑器没焦点，说明是外部更新（如自动生成、协同编辑），应该更新
  if (editor.value.isFocused) {
    pendingExternalUpdate.value = normalizedValue
    return
  }

  editor.value.commands.setContent(normalizedValue, false)
  pendingExternalUpdate.value = null
})

const applyPendingExternalUpdate = () => {
  if (pendingExternalUpdate.value && !editor.value?.isFocused) {
    editor.value?.commands.setContent(normalizeToHtml(pendingExternalUpdate.value), false)
    pendingExternalUpdate.value = null
  }
}

onBeforeUnmount(() => {
  clearUndoHint()
  document.removeEventListener('mousedown', handleSelectionMenuOutsidePress)
  document.removeEventListener('keydown', handleGlobalKeydown)
  editor.value.destroy()
})

onMounted(() => {
  document.addEventListener('mousedown', handleSelectionMenuOutsidePress)
  document.addEventListener('keydown', handleGlobalKeydown)
})

const toggleBold = () => editor.value.chain().focus().toggleBold().run()
const toggleItalic = () => editor.value.chain().focus().toggleItalic().run()
const toggleUnderline = () => editor.value.chain().focus().toggleUnderline().run()
const toggleStrike = () => editor.value.chain().focus().toggleStrike().run()
const toggleHeading = (level) => editor.value.chain().focus().toggleHeading({ level }).run()
const setParagraph = () => editor.value.chain().focus().setParagraph().run()
const toggleCodeBlock = () => editor.value.chain().focus().toggleCodeBlock().run()
const toggleBlockquote = () => editor.value.chain().focus().toggleBlockquote().run()
const toggleBulletList = () => editor.value.chain().focus().toggleBulletList().run()
const toggleOrderedList = () => editor.value.chain().focus().toggleOrderedList().run()

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
  
  // 检查是否有选中的文本
  if (currentSelection.value && currentSelection.value.text) {
    const selectedText = currentSelection.value.text.trim()
    if (selectedText) {
      emit('request-format', {
        text: selectedText,
        selection: {
          from: currentSelection.value.from,
          to: currentSelection.value.to
        }
      })
      return
    }
  }
  
  // 没有选中文本，格式化全文
  const text = editor.value.getText()
  if (!text.trim()) return

  emit('request-format', { text })
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
  const intentLabel = getAiIntentLabel()
  const mergedInstruction = `[${intentLabel}] ${optimizationInstruction.value.trim()}`

  // CP4.1：携带结构化 mode + tone（蓝图 §4.9）
  // mode 由 FE 内部枚举映射到 BE mode（polish → rewrite）
  emit('request-partial-optimize', {
    selection: currentSelection.value,
    instruction: mergedInstruction,
    mode: feToBeMode(aiIntentMode.value),
    tone: aiIntentMode.value === 'tone_shift' ? (aiToneInput.value.trim() || null) : null,
  })

  // 不要清空 instruction，也不要关闭菜单
  // optimizationInstruction.value = ''
  // showSelectionMenu.value = false
}

const openAiRewrite = async () => {
  if (!hasStoredAiIntentMode.value) {
    aiIntentMode.value = inferAiIntentMode()
  }
  optimizationState.value = 'input'
  if (editor.value) {
    editor.value.commands.setFakeSelection(true)
  }
  await nextTick()
  aiInstructionInputRef.value?.focus()
}

const setAiIntentMode = (mode) => {
  aiIntentMode.value = mode
  nextTick(() => aiInstructionInputRef.value?.focus())
}

const backToToolbar = () => {
  optimizationState.value = 'toolbar'
  if (editor.value) {
    editor.value.commands.setFakeSelection(false)
  }
}

const handleInstructionKeydown = (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    event.preventDefault()
    handleOptimizeSelection()
    return
  }
  if (event.key === 'Enter') {
    event.preventDefault()
    handleOptimizeSelection()
  }
}

const handleEscapeShortcut = () => {
  // 如果正在处理中，允许取消（但不中断后端请求，只重置前端状态）
  if (optimizationState.value === 'processing') {
    resetOptimization()
    return
  }
  if (optimizationState.value === 'reviewing') {
    rejectOptimization()
    return
  }
  if (optimizationState.value === 'input') {
    backToToolbar()
    return
  }
  resetOptimization()
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
  const originalText = currentSelection.value?.text || ''
  const originalLength = originalTo - originalFrom
  const newLength = newTo - newFrom

  // 1. 清除新文的高亮
  editor.value.chain()
    .setTextSelection({ from: newFrom, to: newTo })
    .unsetHighlight()
    .run()

  // 2. 删除原文
  editor.value.chain()
    .deleteRange({ from: originalFrom, to: originalTo })
    .run()

  const appliedFrom = Math.max(0, newFrom - originalLength)
  const appliedTo = appliedFrom + newLength
  lastAppliedOptimization.value = {
    from: appliedFrom,
    to: appliedTo,
    originalText
  }
  clearUndoHint()
  showUndoHint.value = true
  undoHintTimer = setTimeout(() => {
    showUndoHint.value = false
    undoHintTimer = null
  }, UNDO_HINT_DURATION_MS)

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
  emitEntityFocus('')
  if (editor.value) {
    editor.value.commands.setFakeSelection(false)
  }
}

const undoLastOptimization = () => {
  const snapshot = lastAppliedOptimization.value
  if (!editor.value || !snapshot) return
  const maxSize = editor.value.state.doc.content.size
  const from = Math.max(0, Math.min(snapshot.from, maxSize))
  const to = Math.max(from, Math.min(snapshot.to, maxSize))
  editor.value.chain()
    .deleteRange({ from, to })
    .insertContentAt(from, snapshot.originalText)
    .run()
  lastAppliedOptimization.value = null
  clearUndoHint()
}

/**
 * 滚动到指定字符偏移并临时高亮该区间（V3.1 F4 审校问题点击定位）。
 *
 * offset 是 [start, end] 字符偏移（基于纯文本，非 ProseMirror pos）。
 * 因为 ProseMirror 的 pos 含块级节点边界开销，与纯文本字符偏移不一致，
 * 这里先在 doc 文本上累计映射到 ProseMirror pos，再滚动+高亮。
 *
 * 高亮 2.5s 后自动清除（避免持久污染正文）。
 */
let auditHighlightTimer = null

const scrollToOffsetAndHighlight = (offset) => {
  if (!editor.value || !offset || offset.length < 2) return
  const [startChar, endChar] = offset
  if (typeof startChar !== 'number' || typeof endChar !== 'number') return
  if (endChar <= startChar) return

  // 先清除上次的高亮（若存在）
  clearAuditHighlight()

  const doc = editor.value.state.doc
  // 构建"纯文本字符偏移 → ProseMirror pos"的映射
  let charCount = 0
  let startPs = null
  let endPs = null

  doc.descendants((node, pos) => {
    if (startPs !== null && endPs !== null) return false
    if (!node.isText) return true
    const text = node.text || ''
    const len = text.length
    // 检查 startChar 是否落在当前节点
    if (startPs === null && charCount + len >= startChar) {
      startPs = pos + (startChar - charCount)
    }
    if (endPs === null && charCount + len >= endChar) {
      endPs = pos + (endChar - charCount)
    }
    charCount += len
    return true
  })

  // 兜底：若 endChar 超出文本末尾，取文档末尾
  if (startPs !== null && endPs === null) {
    endPs = doc.content.size
  }
  if (startPs === null) return

  const safeEnd = endPs ?? startPs + 1

  // 应用 auditHighlight mark
  const markType = editor.value.state.schema.marks.auditHighlight
  if (markType) {
    const tr = editor.value.state.tr.addMark(startPs, safeEnd, markType.create())
    editor.value.view.dispatch(tr)
  }

  // 滚动到该位置（选区设置 + scrollIntoView）
  editor.value.commands.setTextSelection({ from: startPs, to: safeEnd })
  editor.value.commands.scrollIntoView()

  // 2.5s 后清除高亮
  auditHighlightTimer = setTimeout(() => {
    clearAuditHighlight()
  }, 2500)
}

const clearAuditHighlight = () => {
  if (auditHighlightTimer) {
    clearTimeout(auditHighlightTimer)
    auditHighlightTimer = null
  }
  if (!editor.value) return
  const markType = editor.value.state.schema.marks.auditHighlight
  if (!markType) return
  const tr = editor.value.state.tr.removeMark(0, editor.value.state.doc.content.size, markType)
  editor.value.view.dispatch(tr)
}

const handleGlobalKeydown = (event) => {
  if (!showUndoHint.value) return
  const isUndo = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z'
  if (!isUndo) return
  event.preventDefault()
  undoLastOptimization()
}

defineExpose({
  insertContent,
  clearContent,
  flushBuffer,
  editor,
  applyOptimizationDiff,
  resetOptimization,
  scrollToOffsetAndHighlight,
  clearAuditHighlight,
  getContent: () => editor.value?.getHTML() || ''
})
</script>

<template>
  <div ref="editorContainerRef" class="rich-text-editor bg-parchment-50 overflow-hidden flex flex-col h-full relative" :class="{ 'opacity-60': disabled }">
    <div v-if="editor && !disabled" class="toolbar flex items-center gap-1 px-3 py-1.5 bg-[var(--bg-secondary)]/80 backdrop-blur-sm border-b border-[var(--border-color)]/40 overflow-x-auto whitespace-nowrap flex-shrink-0">
      <button 
        @click="toggleBold" 
        :class="{ 'is-active': editor.isActive('bold') }"
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="加粗"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h8a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path><path d="M6 12h9a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path></svg>
      </button>
      <button 
        @click="toggleItalic" 
        :class="{ 'is-active': editor.isActive('italic') }"
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="斜体"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="4" x2="10" y2="4"></line><line x1="14" y1="20" x2="5" y2="20"></line><line x1="15" y1="4" x2="9" y2="20"></line></svg>
      </button>
      <button 
        @click="toggleUnderline" 
        :class="{ 'is-active': editor.isActive('underline') }"
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="下划线"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3v7a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3"></path><line x1="4" y1="21" x2="20" y2="21"></line></svg>
      </button>
      <button 
        @click="toggleStrike" 
        :class="{ 'is-active': editor.isActive('strike') }"
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="删除线"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.3 4.9c-2.3-.6-4.4-1-6.2-.9-2.7 0-5.3.7-5.3 3.6 0 1.5 1.8 3.3 3.6 3.9h.2"></path><path d="M8.7 19.1c2.3.6 4.4 1 6.2.9 2.7 0 5.3-.7 5.3-3.6 0-1.5-1.8-3.3-3.6-3.9h-.2"></path><line x1="3" y1="12" x2="21" y2="12"></line></svg>
      </button>
      <button 
        @click="formatContent" 
        :class="{ 'opacity-50 cursor-not-allowed': isFormatting }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors relative"
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
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="左对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="9" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('center')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'center' }) }"
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="居中"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="18" y1="12" x2="6" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('right')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'right' }) }"
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="右对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="15" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('justify')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'justify' }) }"
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="两端对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="3" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line><line x1="21" y1="6" x2="21" y2="18"></line></svg>
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="toggleSuperscript" 
        :class="{ 'is-active': editor.isActive('superscript') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="上标"
      >
        X<sup>2</sup>
      </button>
      <button 
        @click="toggleSubscript" 
        :class="{ 'is-active': editor.isActive('subscript') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="下标"
      >
        X<sub>2</sub>
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="toggleHeading(1)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 1 }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 1"
      >
        H1
      </button>
      <button 
        @click="toggleHeading(2)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 2 }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 2"
      >
        H2
      </button>
      <button 
        @click="toggleHeading(3)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 3 }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 3"
      >
        H3
      </button>
      <button 
        @click="toggleHeading(4)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 4 }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 4"
      >
        H4
      </button>
      <button 
        @click="toggleHeading(5)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 5 }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 5"
      >
        H5
      </button>
      <button 
        @click="toggleHeading(6)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 6 }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 6"
      >
        H6
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="setParagraph" 
        :class="{ 'is-active': editor.isActive('paragraph') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px]"
        title="正文"
      >
        正文
      </button>
      <button 
        @click="toggleCodeBlock" 
        :class="{ 'is-active': editor.isActive('codeBlock') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-mono"
        title="代码块"
      >
        &lt;/&gt;
      </button>
      <button 
        @click="toggleBlockquote" 
        :class="{ 'is-active': editor.isActive('blockquote') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px]"
        title="引用"
      >
        <Icon name="document" :size="14" />
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="toggleBulletList" 
        :class="{ 'is-active': editor.isActive('bulletList') }"
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="无序列表"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>
      </button>
      <button 
        @click="toggleOrderedList" 
        :class="{ 'is-active': editor.isActive('orderedList') }"
        class="p-1.5 rounded hover:bg-parchment-300/50 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="有序列表"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="10" y1="6" x2="21" y2="6"></line><line x1="10" y1="12" x2="21" y2="12"></line><line x1="10" y1="18" x2="21" y2="18"></line><path d="M4 6h1v4"></path><path d="M4 10h2"></path><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"></path></svg>
      </button>
    </div>
    
    <editor-content :editor="editor" class="flex-1 overflow-y-auto custom-scrollbar" />

    <transition name="copilot-menu">
      <div 
        v-if="showSelectionMenu"
        ref="selectionMenuRef"
        tabindex="-1"
        :style="{ top: selectionMenuPos.top + 'px', left: selectionMenuPos.left + 'px' }"
        class="absolute z-50 bg-[var(--bg-primary)]/95 backdrop-blur border border-[var(--border-color)] rounded-xl p-2 flex items-center gap-2 shadow-[0_10px_30px_rgba(15,23,42,0.14)]"
        @mousedown.prevent.stop
        @keydown.esc.prevent.stop="handleEscapeShortcut"
      >
      <template v-if="optimizationState === 'toolbar'">
        <button
          @click="toggleBold"
          class="px-2 py-1 text-[11px] rounded-md text-ink-600 hover:text-ink-900 hover:bg-parchment-100 transition-colors"
          :class="{ 'bg-accent-50 text-accent-600': editor?.isActive('bold') }"
          title="加粗"
        >
          B
        </button>
        <button
          @click="toggleItalic"
          class="px-2 py-1 text-[11px] rounded-md text-ink-600 hover:text-ink-900 hover:bg-parchment-100 transition-colors italic"
          :class="{ 'bg-accent-50 text-accent-600': editor?.isActive('italic') }"
          title="斜体"
        >
          I
        </button>
        <button
          @click="toggleUnderline"
          class="px-2 py-1 text-[11px] rounded-md text-ink-600 hover:text-ink-900 hover:bg-parchment-100 transition-colors underline"
          :class="{ 'bg-accent-50 text-accent-600': editor?.isActive('underline') }"
          title="下划线"
        >
          U
        </button>
        <div class="w-px h-4 bg-[var(--border-color)]"></div>
        <button
          @click="openAiRewrite"
          class="px-2.5 py-1 text-[11px] rounded-md bg-accent-600 text-white font-medium hover:bg-accent-500 transition-colors"
        >
          <Icon name="sparkles" :size="12" /> AI 润色/改写
        </button>
        <div class="w-px h-4 bg-[var(--border-color)]"></div>
        <button
          @click="addToGoldenSnippets"
          :disabled="!props.bookId || !hasSelection"
          class="px-2 py-1 text-[10px] rounded-md bg-emerald-50 text-emerald-600 hover:bg-emerald-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title="将选中片段添加到黄金锚点"
        >
          <Icon name="star" :size="12" /> 黄金片段
        </button>
        <button
          @click="addToBlacklist"
          :disabled="!props.bookId || !hasSelection"
          class="px-2 py-1 text-[10px] rounded-md bg-rose-50 text-rose-600 hover:bg-rose-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title="将选中片段添加到黑名单"
        >
          <Icon name="x-mark" :size="12" /> 黑名单
        </button>
      </template>

      <template v-else-if="optimizationState === 'input'">
        <div class="flex items-center gap-1">
          <button
            @click="setAiIntentMode('polish')"
            class="px-2 py-1 text-[10px] rounded-md border transition-colors"
            :class="aiIntentMode === 'polish' ? 'bg-accent-50 text-accent-600 border-accent-200' : 'bg-[var(--bg-primary)] text-ink-500 border-[var(--border-color)] hover:bg-parchment-100'"
          >
            润色
          </button>
          <button
            @click="setAiIntentMode('describe')"
            class="px-2 py-1 text-[10px] rounded-md border transition-colors"
            :class="aiIntentMode === 'describe' ? 'bg-accent-50 text-accent-600 border-accent-200' : 'bg-[var(--bg-primary)] text-ink-500 border-[var(--border-color)] hover:bg-parchment-100'"
          >
            描写
          </button>
          <button
            @click="setAiIntentMode('expand')"
            class="px-2 py-1 text-[10px] rounded-md border transition-colors"
            :class="aiIntentMode === 'expand' ? 'bg-accent-50 text-accent-600 border-accent-200' : 'bg-[var(--bg-primary)] text-ink-500 border-[var(--border-color)] hover:bg-parchment-100'"
          >
            扩写
          </button>
          <button
            @click="setAiIntentMode('compress')"
            class="px-2 py-1 text-[10px] rounded-md border transition-colors"
            :class="aiIntentMode === 'compress' ? 'bg-accent-50 text-accent-600 border-accent-200' : 'bg-[var(--bg-primary)] text-ink-500 border-[var(--border-color)] hover:bg-parchment-100'"
          >
            压缩
          </button>
          <button
            @click="setAiIntentMode('tone_shift')"
            class="px-2 py-1 text-[10px] rounded-md border transition-colors"
            :class="aiIntentMode === 'tone_shift' ? 'bg-accent-50 text-accent-600 border-accent-200' : 'bg-[var(--bg-primary)] text-ink-500 border-[var(--border-color)] hover:bg-parchment-100'"
          >
            换语气
          </button>
        </div>
        <!-- CP4.1：tone_shift 模式的目标语气输入框 -->
        <input
          v-if="aiIntentMode === 'tone_shift'"
          v-model="aiToneInput"
          placeholder="目标语气：如 冷峻/诙谐/抒情"
          class="text-xs border border-[var(--border-color)] rounded-lg px-2 py-1.5 outline-none focus:border-[var(--accent-600)] w-40 text-[var(--text-primary)] bg-[var(--bg-canvas)]"
        />
        <input 
          ref="aiInstructionInputRef"
          v-model="optimizationInstruction"
          @focus="handleInputFocus"
          @blur="handleInputBlur"
          @keydown="handleInstructionKeydown"
          :placeholder="getDynamicInstructionPlaceholder()"
          class="text-xs border border-[var(--border-color)] rounded-lg px-2 py-1.5 outline-none focus:border-[var(--accent-600)] w-72 text-[var(--text-primary)] bg-[var(--bg-canvas)]"
        />
        <button 
          @click="handleOptimizeSelection" 
          class="px-2 py-1 rounded-md text-xs bg-accent-50 text-accent-600 hover:bg-accent-100 transition-colors"
          title="执行优化"
        >
          执行
        </button>
        <button 
          @click="backToToolbar" 
          class="px-2 py-1 rounded-md text-xs bg-parchment-100 text-ink-600 hover:bg-parchment-200 transition-colors"
          title="取消"
        >
          取消
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
          替换原文
        </button>
        <button 
          @click="rejectOptimization"
          class="px-3 py-1 text-xs bg-parchment-100 text-ink-600 hover:bg-parchment-200 rounded border border-[var(--border-color)] transition-colors"
        >
          保留原文
        </button>
      </template>
      </div>
    </transition>

    <transition name="undo-hint">
      <button
        v-if="showUndoHint"
        class="absolute right-4 bottom-4 z-40 px-3 py-1.5 rounded-full text-xs bg-ink-900 text-white shadow-lg hover:bg-ink-800 transition-colors"
        @click="undoLastOptimization"
      >
        已替换 · 撤销
      </button>
    </transition>
  </div>
</template>

<style scoped>
.rich-text-editor .is-active {
  /* 使用 accent 色系的透明背景 */
  background-color: hsla(260, 60%, 55%, 0.12);
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
    font-size: 1rem;
    line-height: 2.0;
    color: var(--text-primary);
  }
  
  :deep(.ProseMirror p) {
    margin-bottom: 1.25em;
  }
:deep(.ProseMirror p.is-editor-empty:first-child::before) {
  color: var(--text-muted);
  /* ink-400 色调 */
  content: attr(data-placeholder);
  float: left;
  height: 0;
  pointer-events: none;
}
:deep(.fake-selection-highlight) {
  background-color: #b4d5fe;
}

.copilot-menu-enter-active,
.copilot-menu-leave-active {
  transition: opacity 0.14s ease, transform 0.14s ease;
}

.copilot-menu-enter-from,
.copilot-menu-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}

.undo-hint-enter-active,
.undo-hint-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.undo-hint-enter-from,
.undo-hint-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
