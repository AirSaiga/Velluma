<script setup>
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import BubbleMenuExtension from '@tiptap/extension-bubble-menu'
import Placeholder from '@tiptap/extension-placeholder'
  import TextAlign from '@tiptap/extension-text-align'
  import Underline from '@tiptap/extension-underline'
  import TextStyle from '@tiptap/extension-text-style'
  import Color from '@tiptap/extension-color'
  import Highlight from '@tiptap/extension-highlight'
  import Subscript from '@tiptap/extension-subscript'
  import Superscript from '@tiptap/extension-superscript'
  import { watch, onBeforeUnmount, onMounted, ref, nextTick, computed } from 'vue'
import { Extension } from '@tiptap/core'
import GhostDraftMark from '../extensions/GhostDraftMark'
import InlineDock from '../extensions/InlineDock'
import CanonHighlight from '../extensions/CanonHighlight'
import OutlineNoteNode from '../extensions/OutlineNoteNode'
import ChineseTypography, { normalizeDocumentPunctuation } from '../extensions/chineseTypography'
import EditorFind from '../extensions/editorFind'
import { stripForeignInlineStyles, FOREIGN_MARK_NAMES } from '../extensions/foreignStyles'
import { buildEntityMentionExtensions } from '../extensions/entityMention'
import { registerChapterEditor } from '../features/chapter-editor/editorHandle'
import { noHistory, setContentNoHistory } from '../features/chapter-editor/noHistory'
import { useEditorFind } from '../features/chapter-editor/composables/useEditorFind'
import EditorFindBar from '../features/chapter-editor/presentation/EditorFindBar.vue'
import { useEscStack } from '../composables/useEscStack'
import { reapGhostIfDead } from '../features/generation/composables/useGhostDraft'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { styleApi, deaiApi } from '../services/api/domain'
import Icon from './Icon.vue'
import { useToast } from '../composables/useToast'
import { useDeaiPairMark } from '../composables/useDeaiPairMark'

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
    // 双写收敛（任务包 B）：黄金片段只汇入文风样本库（source=golden_snippet）；
    // 旧 books.golden_snippets 表冻结只读（存量经文风页「from-golden」导入收编），
    // 不再双写。6 秒撤销胶囊即完整撤销（撤销只撤样本，正是全部副作用）。
    const sample = await styleApi.createSample(props.bookId, {
      content: selectedText,
      scene_type: 'general',
      source: 'golden_snippet',
    })
    styleApi.logStyleEvent(props.bookId, 'golden_to_sample')
    showToast('已存进文风样本库', 'success', 6000, {
      label: '撤销',
      onClick: () => {
        styleApi.deleteSample(props.bookId, sample.id).catch(() => {})
      },
    })
  } catch (e) {
    console.error('存进文风样本库失败:', e)
    showToast('保存失败：' + (e.message || ''), 'error')
  }
}

async function notLikeMyStyle() {
  // S3「这不像我」：选中不对味的文字 → 负面清单候选进文风收件箱（过目才生效）。
  // 「把这段改得更像我」= 现有的「AI 润色/改写」按钮（S2 起带文风注入），不再另设入口
  const selectedText = getSelectedText()
  if (!selectedText) {
    showToast('请先选中不像你的文字', 'warning')
    return
  }
  if (!props.bookId) {
    showToast('需要先打开书籍', 'warning')
    return
  }
  try {
    await styleApi.addInboxItem(
      props.bookId,
      'negative_candidate',
      {
        // 短语整句进候选词太粗暴——截前 16 字作禁词候选，全文留 source_text 供过目
        word: selectedText.trim().slice(0, 16),
        source_text: selectedText.trim().slice(0, 120),
      },
      'writing_desk',
    )
    styleApi.logStyleEvent(props.bookId, 'not_like_me')
    showToast('已记入文风收件箱——到文风页过目后生效', 'success')
  } catch (e) {
    console.error('投递文风候选失败:', e)
    showToast('投递失败: ' + (e.message || ''), 'error')
  }
}

// deai 训练对收集（docs/deai-integration.md §5a，数据飞轮手动起点）：
// 两步配对——①选中卡片舱生成的原样文本点「记改前」暂存 ②亲手改完，
// 选中改后文本点「记改后」成对落 data/deai_pairs.jsonl（本地零上报）。
// 攒够后跑 deai/scripts/ingest_behavior_pairs.py 六闸入库出训练集。
// pending 状态在 useDeaiPairMark 模块单例——浮窗开合不丢，换书作废。
const { pendingBad, markBad, markGood, clearPending } = useDeaiPairMark()

async function markDeaiPair() {
  const selectedText = getSelectedText()
  const goodText = selectedText.trim()
  const bookKey = String(props.bookId || '')
  if (!pendingBad.value) {
    const r = markBad(selectedText, bookKey)
    showToast(r.message, r.ok ? 'success' : 'warning')
    return
  }
  const r = markGood(selectedText, bookKey)
  if (!r.ok) {
    showToast(r.message, 'warning')
    return
  }
  try {
    const saved = await deaiApi.savePair({
      bad: r.bad || '',
      good: goodText,
      book_id: props.bookId || undefined,
    })
    clearPending()
    showToast(
      `已存第 ${saved.total} 对「改前→改后」样本（${r.bad?.length ?? 0} 字 → ${goodText.length} 字）`,
      'success',
      6000,
      {
        label: '撤销',
        onClick: () => {
          deaiApi.deletePair(saved.id).catch(() => {})
        },
      },
    )
  } catch (e) {
    // 失败保留 pending——修好网络或换个选区可直接重试/重配
    showToast('存对失败: ' + (e?.message || '未知错误'), 'error')
  }
}

function cancelDeaiPairMark() {
  clearPending()
  showToast('已放弃这次配对', 'info')
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

const emitEntityFocus = (keyword = '', meta = {}) => {
  const normalized = (keyword || '').trim()
  // W2 情境浮卡：载荷带 source（cursor/selection/mention）+ 视口坐标 + 提及实体 id
  emit('entity-focus-change', { keyword: normalized, ...meta })
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
    return '想往哪扩？如：补细节、情绪和动作'
  }
  if (aiIntentMode.value === 'compress') {
    return '想怎么压？如：留信息、提节奏'
  }
  if (aiIntentMode.value === 'describe') {
    return '想细写什么？如：看到的、听到的、摸到的'
  }
  if (aiIntentMode.value === 'tone_shift') {
    return '换语气：在上方输入目标语气（如 冷峻/诙谐/抒情），此处可补充细节（Enter 执行）'
  }
  return '想怎么润色？如：更紧凑 / 更温柔（Enter 执行）'
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
    // 原生撤销/重做开启（Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y）。
    // 警示：AI/系统的程序化变更（幽灵草稿流式灌入、切章 setContent、外部回流、
    // 划轨回拨、选区优化 diff）必须经 noHistory/setContentNoHistory 打标隔离，
    // 否则 Ctrl+Z 会倒放打字机或把上一章内容灌进新章。
    StarterKit.configure({
      history: { depth: 100, newGroupDelay: 500 },
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
    TextStyle,
    Color,
    Highlight.configure({
      multicolor: true,
    }),
    Subscript,
    Superscript,
    GhostDraftMark,
    // 行间推挤式卡片舱（2026-09-09 布局重构）：SparkDock 挂 WidgetDecoration，
    // 光标段下方流内撑开，替代旧 fixed 浮层
    InlineDock,
    // NLE-ADF 3.0 细纲胶囊：行内速记 → 落笔扩写（存盘剥除，会话级）
    OutlineNoteNode,
    // NLE-ADF 2.0 行内极速 Hook：@ 角色 / # 资产 提及 + 静默绑定本章
    ...buildEntityMentionExtensions({
      getBookId: () => props.bookId,
      getChapterId: () => props.id,
    }),
    SelectionHighlighter,
    // NLE-ADF 3.0 Canon 词高亮（角色名/伏笔词虚线小标，Decoration 纯视图不入库）
    CanonHighlight,
    // 中文标点规范化（2026-09-10）：打字即正——半角标点/省略号/直引号落进正文前
    // 就变中文标点（判据见 chineseTypography 顶部；英文/数字上下文一律不动）
    ChineseTypography,
    // 写作台查找/替换（Ctrl+F）：命中高亮走 Decoration 纯视图层，不入库不进撤销栈
    EditorFind,
  ],
  editorProps: {
    attributes: {
      class: 'prose prose-lg max-w-3xl mx-auto focus:outline-none min-h-[560px] px-12 pt-3 pb-10 text-[var(--text-primary)] leading-[2.0]',
    },
    // 粘贴净化（2026-09-10）：剥掉外来行内长相样式（颜色/底色/字体族字号）——
    // 深色主题下粘进来的深色字会变成「纸面隐身」，而作者在主题里找不到原因。
    // 粗体/斜体/下划线等排版意图保留（判据见 extensions/foreignStyles.ts）。
    transformPastedHTML: (html) => stripForeignInlineStyles(html),
    // W2 情境浮卡：点击 @/# 提及节点 → 按实体 id 直取浮卡（旁路通知，不拦截默认行为）
    handleClick: (view, pos, event) => {
      const isMention = (n) =>
        n && (n.type.name === 'charMention' || n.type.name === 'assetMention')
      const $pos = view.state.doc.resolve(pos)
      const node = isMention($pos.nodeAfter)
        ? $pos.nodeAfter
        : isMention($pos.nodeBefore)
          ? $pos.nodeBefore
          : null
      if (node) {
        emit('entity-focus-change', {
          keyword: node.attrs.label || node.attrs.id || '',
          source: 'mention',
          x: event.clientX,
          y: event.clientY + 10,
          entityId: node.attrs.id || null,
          entityKind: node.type.name === 'charMention' ? 'character' : 'asset',
        })
      }
      return false
    },
  },
  onUpdate: ({ editor }) => {
    // 幽灵死亡收割（2026-08-29 手动删除事故）：作者退格/选删亲手删光幽灵
    // 文本时 ghostActive 残留真值——僵尸态吃 Tab、禁 Space、卡 authorLane、
    // sticky 卡舱恢复等不到落沿。每个文档事务后扫一次：状态说有幽灵而文档
    // 扫不到即收尾（作者自己的流式灌入事务里幽灵恒在，纯空转一次树扫）。
    reapGhostIfDead()
    // 查找条开着时正文在变（作者自己改/AI 写），命中集与条上计数跟着重算
    if (findOpen.value) refreshFind()
    emit('update:modelValue', editor.getHTML())
  },
  onBlur: ({ editor }) => {
    applyPendingExternalUpdate()
  },
  onSelectionUpdate: ({ editor }) => {
    // 查找跳转会反复移动选区——查找条开着时不动选区浮窗（否则每跳一条都弹
    // 「AI 润色/改写」工具条，把查找体验淹没），也不发情境浮卡的跟随通知。
    if (findOpen.value) return
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
      emitEntityFocus(detectEntityAroundCursor(editor, from), { source: 'cursor' })
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
      // 浮卡锚点用视口坐标（卡体 Teleport 到 body，fixed 定位）
      const cardCoords = editor.view.coordsAtPos(current.from)
      emitEntityFocus(currentSelection.value.text, {
        source: 'selection',
        x: cardCoords.left,
        y: cardCoords.bottom + 10,
      })
    }, SELECTION_DEBOUNCE_MS) // 延迟以确保选区稳定
  }
})

watch(() => props.disabled, (val) => {
  editor.value?.setEditable(!val)
})

// ===== 查找/替换（Ctrl+F，2026-09-10）=====
// 状态机在 features/chapter-editor/composables/useEditorFind；命中判据在
// extensions/editorFind（单一权威）。条不常驻——「纸面常裸」，不搜即不存在。
const {
  open: findOpen,
  term: findTerm,
  replacement: findReplacement,
  caseSensitive: findCaseSensitive,
  activeLabel: findActiveLabel,
  matchCount: findMatchCount,
  focusToken: findFocusToken,
  openFind,
  close: closeFind,
  setTerm: setFindTerm,
  toggleCaseSensitive: toggleFindCaseSensitive,
  next: findNext,
  prev: findPrev,
  replaceCurrent: findReplaceCurrent,
  replaceAll: findReplaceAll,
  refresh: refreshFind,
} = useEditorFind(editor)

// Esc 走全局 Esc 栈（一次 Esc 只剥一层：查找条 > 助手面板），不在输入框里
// 自处理——window 捕获层的栈先于输入框 bubble 跑，两处都接=一次按键关两层。
// 注：会话写作 Esc（蒸发幽灵/关卡舱）优先级更高，按既有分层让位（见 useEscStack）。
const { push: pushEsc, remove: removeEsc } = useEscStack()
let _findEscId = null
watch(findOpen, (open) => {
  if (open && !_findEscId) {
    _findEscId = pushEsc(() => closeFind(), 'editor-find')
  } else if (!open && _findEscId) {
    removeEsc(_findEscId)
    _findEscId = null
  }
})

/** Ctrl/Cmd+F 唤起：挂在编辑器容器上（正文或查找框有焦点时都生效） */
function handleFindShortcut(e) {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return
  if (e.key.toLowerCase() !== 'f') return
  e.preventDefault()
  e.stopPropagation()
  openFind()
}

const setFindReplacement = (value) => {
  findReplacement.value = value
}

/**
 * 整理标点（本地确定性，零 LLM / 零 API Key，单事务可一次 Ctrl+Z 反悔）。
 * 有选区只整理选区（作者点名范围），无选区整篇。
 */
function normalizePunctuation() {
  const ed = editor.value
  if (!ed) return
  const { from, to } = ed.state.selection
  const scope = from !== to ? { from, to } : undefined
  const result = normalizeDocumentPunctuation(ed, scope)
  if (!result.edits) {
    showToast('标点已经是规整的，没有要改的', 'info')
    return
  }
  const where = scope ? '选区' : '本篇'
  showToast(`${where}已整理 ${result.edits} 处标点`, 'success', 6000, {
    label: '撤销',
    onClick: () => ed.chain().focus().undo().run(),
  })
}

/**
 * 目标范围里有没有「外来长相标记」（textStyle/highlight）——决定提示语说实话。
 * 只看标记不改文档（命令执行前的预检）。
 */
function rangeHasForeignMarks(ed, from, to) {
  let found = false
  ed.state.doc.nodesBetween(from, to, (node) => {
    if (found) return false
    if (node.isText && node.marks.some((m) => FOREIGN_MARK_NAMES.includes(m.type.name))) {
      found = true
      return false
    }
    return true
  })
  return found
}

/**
 * 清除外来样式：剥掉粘贴带进来的颜色/底色/字体族字号（深色主题下会让字隐身），
 * 粗体/斜体/下划线/结构一律保留。无选区=整篇。
 */
function clearForeignStyles() {
  const ed = editor.value
  if (!ed) return
  const { from, to } = ed.state.selection
  const scoped = from !== to
  if (!rangeHasForeignMarks(ed, scoped ? from : 0, scoped ? to : ed.state.doc.content.size)) {
    showToast('没有可清除的外来样式', 'info')
    return
  }
  const chain = ed.chain()
  if (!scoped) chain.selectAll()
  // 摘标记不改文档结构、位置不变——末了还原原选区。整篇清理靠 selectAll，
  // 不还原的话作者回正文一打字就把整章替换掉（菜单入口尤其危险）
  for (const mark of FOREIGN_MARK_NAMES) chain.unsetMark(mark)
  chain.setTextSelection({ from, to }).focus()
  chain.run()
  showToast(scoped ? '已清除选区里粘贴带进来的颜色与字体' : '已清除本篇粘贴带进来的颜色与字体', 'success')
}

// NLE-ADF 2.0：注册全局编辑器句柄（生成会话层的幽灵草稿/Spark Dock
// 控制器经此直接操作文档；卸载时清空，见 onBeforeUnmount）。
watch(editor, (instance) => {
  registerChapterEditor(instance ?? null)
}, { immediate: true })

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
    // 隔离撤销栈：切章覆盖若入栈，Ctrl+Z 会把上一章全文灌进新章（串章事故）
    setContentNoHistory(editor.value, normalizedValue, false)
    pendingExternalUpdate.value = null
    return
  }

  // 2. 如果内容完全一致，不需要更新
  const isSame = editor.value.getHTML() === normalizedValue
  if (isSame) {
    pendingExternalUpdate.value = null
    return
  }

  // 2.5 幽灵草稿/细纲胶囊在屏（未确认的 AI 中间态）：外部回流绝不能覆盖编辑器——
  //    自动保存会在落库前剥除幽灵与细纲节点，回流的 modelValue 必然比编辑器"旧"；
  //    此时 setContent = 幽灵/细纲被误清（点火/空章场景编辑器常无焦点，会走立即分支）。
  //    暂存为 pending，等被采纳/蒸发后由后续回流自然收敛。
  if (
    editor.value.getHTML().includes('data-ghost-draft') ||
    editor.value.getHTML().includes('data-outline-note')
  ) {
    pendingExternalUpdate.value = normalizedValue
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

  // 外部回流（服务器回声/生成预览流式）隔离撤销栈，防"幽灵撤销步"
  setContentNoHistory(editor.value, normalizedValue, false)
  pendingExternalUpdate.value = null
  // 生成预览态（disabled 只读）：外部内容更新后自动滚到底，
  // 让最新渲染段/当前段进度始终可见（正常编辑态不干预滚动位置）
  if (props.disabled) {
    nextTick(() => {
      const scrollEl = editorContainerRef.value?.querySelector('.overflow-y-auto')
      if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight
    })
  }
})

const applyPendingExternalUpdate = () => {
  if (pendingExternalUpdate.value && !editor.value?.isFocused) {
    // 幽灵/细纲在屏时同样不应用（理由见 watch 的 2.5 条）
    const html = editor.value?.getHTML() || ''
    if (html.includes('data-ghost-draft') || html.includes('data-outline-note')) return
    setContentNoHistory(editor.value, normalizeToHtml(pendingExternalUpdate.value), false)
    pendingExternalUpdate.value = null
  }
}

onBeforeUnmount(() => {
  clearUndoHint()
  registerChapterEditor(null)
  document.removeEventListener('mousedown', handleSelectionMenuOutsidePress)
  editorContainerRef.value?.removeEventListener('keydown', handleFindShortcut)
  if (_findEscId) {
    removeEsc(_findEscId)
    _findEscId = null
  }
  editor.value.destroy()
})

onMounted(() => {
  document.addEventListener('mousedown', handleSelectionMenuOutsidePress)
  editorContainerRef.value?.addEventListener('keydown', handleFindShortcut)
})

const toggleBold = () => editor.value.chain().focus().toggleBold().run()
const toggleItalic = () => editor.value.chain().focus().toggleItalic().run()
const toggleUnderline = () => editor.value.chain().focus().toggleUnderline().run()

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

/** 全文智能格式整理（页面头 ⋯ 菜单入口；始终作用于全文，不看选区）。 */
const formatWholeDocument = () => {
  if (!editor.value || props.isFormatting) return
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
  // 整个 diff 预览/确认/拒绝流程均隔离撤销栈：中间态（删除线+双色高亮）不应成为撤销步，
  // 撤销出口是确认后的「撤销」按钮（undoLastOptimization，入栈可再反悔）。
  editor.value.chain()
    .command(noHistory)
    .setTextSelection({ from, to })
    .setStrike()
    .setHighlight({ color: 'var(--diff-del-bg)' })
    .run()

  // 2. 插入新文 (Green Highlight)
  // 注意：插入后位置会变，需要计算
  const insertPos = to
  editor.value.chain()
    .command(noHistory)
    .insertContentAt(insertPos, optimizedText)
    .setTextSelection({ from: insertPos, to: insertPos + optimizedText.length })
    .unsetStrike()
    .setHighlight({ color: 'var(--diff-add-bg)' })
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
    .command(noHistory)
    .setTextSelection({ from: newFrom, to: newTo })
    .unsetHighlight()
    .run()

  // 2. 删除原文
  editor.value.chain()
    .command(noHistory)
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
    .command(noHistory)
    .deleteRange({ from: newFrom, to: newTo })
    .run()

  // 2. 恢复原文样式 (移除 Strike 和 Highlight)
  editor.value.chain()
    .command(noHistory)
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
  // 此恢复操作入撤销栈：Ctrl+Z 可再反悔（等价于重做优化）
  editor.value.chain()
    .deleteRange({ from, to })
    .insertContentAt(from, snapshot.originalText)
    .run()
  lastAppliedOptimization.value = null
  clearUndoHint()
}

// 原生 history 已开启：Ctrl+Z 全局撤销由 TipTap 接管，不再拦截
//（旧实现仅在 showUndoHint 窗口期拦截 Ctrl+Z 做优化撤销，会与原生栈双撤销）。

defineExpose({
  insertContent,
  clearContent,
  flushBuffer,
  editor,
  applyOptimizationDiff,
  resetOptimization,
  formatWholeDocument,
  getContent: () => editor.value?.getHTML() || '',
  // 2026-09-10 编辑器优化：⋯ 菜单两个本地命令 + 查找条（Ctrl+F 之外的可发现入口）
  normalizePunctuation,
  clearForeignStyles,
  openFind,
})
</script>

<template>
  <div ref="editorContainerRef" class="rich-text-editor overflow-hidden flex flex-col flex-1 min-h-0 relative" :class="{ 'opacity-60': disabled }">
    <editor-content :editor="editor" class="flex-1 overflow-y-auto custom-scrollbar" />

    <!-- 查找/替换条（Ctrl+F 唤起；Esc / × 收，收后焦点回正文） -->
    <EditorFindBar
      v-if="findOpen"
      :term="findTerm"
      :replacement="findReplacement"
      :case-sensitive="findCaseSensitive"
      :active-label="findActiveLabel"
      :match-count="findMatchCount"
      :focus-token="findFocusToken"
      @update:term="setFindTerm"
      @update:replacement="setFindReplacement"
      @toggle-case="toggleFindCaseSensitive"
      @next="findNext"
      @prev="findPrev"
      @replace-current="findReplaceCurrent"
      @replace-all="findReplaceAll"
      @close="closeFind"
    />

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
          class="px-2 py-1 text-xs rounded-md text-ink-600 hover:text-ink-900 hover:bg-parchment-100 transition-colors"
          :class="{ 'bg-accent-50 text-accent-600': editor?.isActive('bold') }"
          title="加粗"
        >
          B
        </button>
        <button
          @click="toggleItalic"
          class="px-2 py-1 text-xs rounded-md text-ink-600 hover:text-ink-900 hover:bg-parchment-100 transition-colors italic"
          :class="{ 'bg-accent-50 text-accent-600': editor?.isActive('italic') }"
          title="斜体"
        >
          I
        </button>
        <button
          @click="toggleUnderline"
          class="px-2 py-1 text-xs rounded-md text-ink-600 hover:text-ink-900 hover:bg-parchment-100 transition-colors underline"
          :class="{ 'bg-accent-50 text-accent-600': editor?.isActive('underline') }"
          title="下划线"
        >
          U
        </button>
        <div class="w-px h-4 bg-[var(--border-color)]"></div>
        <button
          @click="openAiRewrite"
          class="px-2.5 py-1 text-xs rounded-md bg-accent-600 text-[var(--bg-canvas)] font-medium hover:bg-accent-500 transition-colors"
        >
          <Icon name="sparkles" :size="12" /> AI 润色/改写
        </button>
        <div class="w-px h-4 bg-[var(--border-color)]"></div>
        <button
          @click="addToGoldenSnippets"
          :disabled="!props.bookId || !hasSelection"
          class="px-2 py-1 text-xs rounded-md bg-[color-mix(in_srgb,var(--gold)_14%,transparent)] text-[color-mix(in_srgb,var(--gold)_75%,var(--text-primary))] hover:bg-[color-mix(in_srgb,var(--gold)_24%,transparent)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title="把这段存进你的文风样本库，AI 以后会学它的写法"
        >
          <Icon name="star" :size="12" /> 黄金片段
        </button>
        <button
          @click="notLikeMyStyle"
          :disabled="!props.bookId || !hasSelection"
          class="px-2 py-1 text-xs rounded-md bg-[color-mix(in_srgb,var(--danger)_10%,transparent)] text-[var(--danger)] hover:bg-[color-mix(in_srgb,var(--danger)_18%,transparent)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title="这段不像你写的——记为负面清单候选（进文风收件箱，过目后生效）"
        >
          <Icon name="x-mark" :size="12" /> 这不像我
        </button>
        <div class="w-px h-4 bg-[var(--border-color)]"></div>
        <button
          @click="markDeaiPair"
          :disabled="!props.bookId || !hasSelection"
          class="px-2 py-1 text-xs rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          :class="pendingBad
            ? 'bg-[color-mix(in_srgb,var(--warn)_22%,transparent)] text-[var(--warn)] hover:bg-[color-mix(in_srgb,var(--warn)_32%,transparent)] font-medium'
            : 'bg-[color-mix(in_srgb,var(--warn)_8%,transparent)] text-[var(--warn)] hover:bg-[color-mix(in_srgb,var(--warn)_16%,transparent)]'"
          :title="pendingBad
            ? `配对中（改前 ${pendingBad.text.length} 字）——选中你改好的文字，点这里完成配对`
            : '帮 AI 学你的改法：先记下这段原文，亲手改完后选中它再点这里'"
        >
          <Icon name="check-badge" :size="12" /> {{ pendingBad ? '记改后' : '记改前' }}
        </button>
        <button
          v-if="pendingBad"
          @click="cancelDeaiPairMark"
          class="px-1.5 py-1 text-xs rounded-md text-[var(--warn)] hover:bg-[color-mix(in_srgb,var(--warn)_14%,transparent)] transition-colors"
          title="放弃这次配对"
        >
          <Icon name="x-mark" :size="12" />
        </button>
      </template>

      <template v-else-if="optimizationState === 'input'">
        <div class="flex items-center gap-1">
          <button
            @click="setAiIntentMode('polish')"
            class="px-2 py-1 text-xs rounded-md border transition-colors"
            :class="aiIntentMode === 'polish' ? 'bg-accent-50 text-accent-600 border-accent-200' : 'bg-[var(--bg-primary)] text-ink-500 border-[var(--border-color)] hover:bg-parchment-100'"
          >
            润色
          </button>
          <button
            @click="setAiIntentMode('describe')"
            class="px-2 py-1 text-xs rounded-md border transition-colors"
            :class="aiIntentMode === 'describe' ? 'bg-accent-50 text-accent-600 border-accent-200' : 'bg-[var(--bg-primary)] text-ink-500 border-[var(--border-color)] hover:bg-parchment-100'"
          >
            描写
          </button>
          <button
            @click="setAiIntentMode('expand')"
            class="px-2 py-1 text-xs rounded-md border transition-colors"
            :class="aiIntentMode === 'expand' ? 'bg-accent-50 text-accent-600 border-accent-200' : 'bg-[var(--bg-primary)] text-ink-500 border-[var(--border-color)] hover:bg-parchment-100'"
          >
            扩写
          </button>
          <button
            @click="setAiIntentMode('compress')"
            class="px-2 py-1 text-xs rounded-md border transition-colors"
            :class="aiIntentMode === 'compress' ? 'bg-accent-50 text-accent-600 border-accent-200' : 'bg-[var(--bg-primary)] text-ink-500 border-[var(--border-color)] hover:bg-parchment-100'"
          >
            压缩
          </button>
          <button
            @click="setAiIntentMode('tone_shift')"
            class="px-2 py-1 text-xs rounded-md border transition-colors"
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
          <span>AI 改写中…</span>
        </div>
      </template>

      <template v-else-if="optimizationState === 'reviewing'">
        <button 
          @click="confirmOptimization"
          class="px-3 py-1 text-xs bg-[color-mix(in_srgb,var(--ok)_10%,transparent)] text-[var(--ok)] hover:bg-[color-mix(in_srgb,var(--ok)_18%,transparent)] rounded border border-[color-mix(in_srgb,var(--ok)_35%,transparent)] transition-colors"
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
        class="absolute right-4 bottom-4 z-40 px-3 py-1.5 rounded-full text-xs bg-[var(--text-primary)] text-[var(--bg-canvas)] shadow-lg hover:opacity-90 transition-opacity"
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
    border-radius: var(--radius-xs);
  }
  .custom-scrollbar::-webkit-scrollbar-thumb:hover {
    background-color: var(--text-muted);
  }
  
  /* Tiptap Prose Customization */
  /* 排版（字体族/字号/行高）不在这里写死——单一权威是 :root 的 --editor-* token
     （style.css 的 `.rich-text-editor .ProseMirror`）。此前这里重复声明了
     font-family/font-size/line-height，scoped 规则晚于全局表注入、同权重胜出，
     把「实验：编辑器排版（宽排）」的 token 覆写成死档（切 18px/1.8 毫无反应）。
     2026-09-10 去掉重复声明：改排版只改 token 一处。 */
  :deep(.ProseMirror) {
    height: 100%;
    outline: none;
    color: var(--text-primary);
    /* 行间推挤卡舱（InlineDock）配套：关掉浏览器原生滚动锚定，防止舱展开
       撑高时锚定节点与 InlineDockHost 的 scrollIntoView(nearest) 互搏跳滚 */
    overflow-anchor: none;
  }

  /* 行间推挤卡舱的 widget 外壳（PM 管的 DOM 岛，2026-09-09）：块级、贴满
     正文列宽；高度动画在 InlineDockHost 根上，这里只保证不额外变形 */
  :deep(.velluma-inline-dock-widget) {
    display: block;
    width: 100%;
  }
  
  :deep(.ProseMirror p) {
    margin-bottom: 1.25em;
    /* 保持默认左对齐——2026-09-09 试过 justify 后回退（截图像素实测）：
       Chromium 120 无标点压缩（text-spacing-trim 要 129+），justify 把
       禁则/半角行的空隙摊成分数像素字距，这些满行的栅格反而涣散；
       纯中文满行左对齐本就天然齐右缘（834px 行宽实测 910-912 三线齐平），
       不需要 justify。勿再试 */
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
  background-color: color-mix(in srgb, var(--info) 30%, transparent); /* 伪造选区（旧浏览器默认选区蓝 #b4d5fe 语义平移） */
}

/* NLE-ADF 3.0 Canon 词高亮：正文角色名/伏笔词虚线小标（Decoration，不入库） */
:deep(.canon-mark) {
  border-bottom: 1.5px dotted currentColor;
  padding-bottom: 1px;
  cursor: help;
}
:deep(.canon-mark--character) {
  border-bottom-color: var(--info);
}
:deep(.canon-mark--hook) {
  border-bottom-color: var(--warn);
}
:deep(.canon-mark--contradiction) {
  border-bottom-color: var(--danger);
  background: color-mix(in srgb, var(--danger) 6%, transparent);
}
/* 矛盾段左缘条（Decoration.node，整段标识） */
:deep(.canon-para--contradiction) {
  box-shadow: inset 3px 0 0 var(--danger); /* 矛盾段左缘朱条=红笔批注 */
}

.copilot-menu-enter-active {
  transition: opacity var(--dur-1) var(--ease-out), transform var(--dur-1) var(--ease-out);
}
.copilot-menu-leave-active {
  transition: opacity var(--dur-1) var(--ease-in), transform var(--dur-1) var(--ease-in);
}

.copilot-menu-enter-from,
.copilot-menu-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}

.undo-hint-enter-active,
.undo-hint-leave-active {
  transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out);
}

.undo-hint-enter-from,
.undo-hint-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
