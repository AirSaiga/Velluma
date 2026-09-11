import { computed, ref, watch, type Ref } from 'vue'
import type { Editor } from '@tiptap/core'
import { collectDocMatches, setFindSearch, type DocMatch } from '../../../extensions/editorFind'

/**
 * 查找/替换状态机（写作台 Ctrl+F，2026-09-10）。
 *
 * 分工：命中扫描与高亮判据在 `extensions/editorFind.ts`（单一权威），本文件只
 * 管「当前第几条 / 上下跳 / 替换 / 全部替换」这些交互状态，UI 在 EditorFindBar。
 *
 * 三条纪律：
 * - 每次替换各是一个事务（逐条可 Ctrl+Z 反悔）；「全部替换」合成**单事务**
 *   （一次撤销整批回退——批量动作只给一个反悔点才符合直觉）；
 * - 替换用 JSON 内容 / 裸事务 insertText：字符串走 HTML 解析，替换词里带
 *   `<`、`&` 会被吃成标签；
 * - 跳转只移动选区不抢焦点（焦点留在查找输入框，作者可以接着打字继续找）。
 *
 * 输入框焦点走 `focusToken` 计数器下发（条是子组件，本文件拿不到它的 DOM）：
 * 每次唤起都 +1，条那边 watch 到变化就聚焦并全选输入框。这样「Ctrl+F 连按」
 * 也能把焦点从正文拽回查找框。
 */
export function useEditorFind(editorRef: Ref<Editor | null | undefined>) {
  const open = ref(false)
  const term = ref('')
  const replacement = ref('')
  const caseSensitive = ref(false)
  const activeIndex = ref(0)
  const matches = ref<DocMatch[]>([])
  const focusToken = ref(0)

  const matchCount = computed(() => matches.value.length)
  const activeLabel = computed(() => {
    if (!term.value) return ''
    if (!matchCount.value) return '0/0'
    return `${Math.min(activeIndex.value + 1, matchCount.value)}/${matchCount.value}`
  })

  /** 重扫命中并把搜索态推给插件（装饰随之刷新）。不移动选区。 */
  function refresh(pushState = true) {
    const ed = editorRef.value
    if (!ed) {
      matches.value = []
      return
    }
    matches.value = term.value ? collectDocMatches(ed.state.doc, term.value, caseSensitive.value) : []
    if (activeIndex.value >= matches.value.length) {
      activeIndex.value = matches.value.length ? matches.value.length - 1 : 0
    }
    if (pushState) {
      setFindSearch(ed, { term: term.value, caseSensitive: caseSensitive.value, activeIndex: activeIndex.value })
    }
  }

  /** 跳到第 index 条命中（越界自动环绕），并滚动到可见处。 */
  function jumpTo(index: number) {
    const ed = editorRef.value
    const n = matches.value.length
    if (!ed || !n) return
    const i = ((index % n) + n) % n
    activeIndex.value = i
    const m = matches.value[i]
    ed.chain().setTextSelection({ from: m.from, to: m.to }).scrollIntoView().run()
    setFindSearch(ed, { activeIndex: i })
  }

  /** 光标之后的第一条命中下标（打开查找时的起始位置，与「从当前位置往下找」同直觉） */
  function indexFromCursor(): number {
    const ed = editorRef.value
    if (!ed || !matches.value.length) return 0
    const cursor = ed.state.selection.from
    const hit = matches.value.findIndex((m) => m.from >= cursor)
    return hit === -1 ? 0 : hit
  }

  function openFind(initialTerm?: string) {
    const ed = editorRef.value
    // 已开着时只把焦点送回输入框：连按 Ctrl+F 绝不能拿「当前命中的选区文本」
    // 覆写作者输了一半的搜索词（选区此刻正是命中项）
    if (open.value) {
      focusToken.value += 1
      return
    }
    open.value = true
    if (ed) {
      // 有选区时预填选区文本当搜索词（≤60 字——整段文本当搜索词没有意义）
      const { from, to, empty } = ed.state.selection
      if (!empty && initialTerm === undefined) {
        const sel = ed.state.doc.textBetween(from, to, ' ').trim()
        if (sel && sel.length <= 60) term.value = sel
      }
    }
    if (initialTerm !== undefined) term.value = initialTerm
    activeIndex.value = 0
    refresh()
    jumpTo(indexFromCursor())
    focusToken.value += 1
  }

  function close() {
    const ed = editorRef.value
    open.value = false
    term.value = ''
    replacement.value = ''
    matches.value = []
    activeIndex.value = 0
    if (ed) {
      setFindSearch(ed, { term: '', activeIndex: 0 })
      // 关条即回正文。走 ed.view.focus() 而不是 commands.focus()：后者把真正的
      // view.focus() 推迟进 requestAnimationFrame，而 rAF 在窗口不可见时会被
      // 节流/暂停——实测（IAB）关条后焦点停在 body，作者以为还在输入框里打字。
      ed.view.focus()
    }
  }

  function setTerm(value: string) {
    term.value = value
    activeIndex.value = 0
    refresh()
    if (value) jumpTo(0)
  }

  function toggleCaseSensitive() {
    caseSensitive.value = !caseSensitive.value
    activeIndex.value = 0
    refresh()
    if (term.value) jumpTo(0)
  }

  function next() {
    jumpTo(activeIndex.value + 1)
  }

  function prev() {
    jumpTo(activeIndex.value - 1)
  }

  /** 替换当前命中（独立事务，可单独撤销）。 */
  function replaceCurrent(): boolean {
    const ed = editorRef.value
    const m = matches.value[activeIndex.value]
    if (!ed || !m) return false
    const at = activeIndex.value
    const text = replacement.value
    const chain = ed.chain()
    if (text) {
      // 用 JSON 内容而不是字符串：字符串走 HTML 解析，替换词里带 `<`、`&`
      // 会被吃成标签（「替换为空」= 删除，单独走 deleteRange）
      chain.insertContentAt({ from: m.from, to: m.to }, { type: 'text', text })
    } else {
      chain.deleteRange({ from: m.from, to: m.to })
    }
    chain.run()
    refresh()
    // 替换后沿用同一下标（原地可能又有新命中），越界则回到末条
    jumpTo(Math.min(at, matches.value.length - 1))
    return true
  }

  /** 全部替换（单事务——一次撤销整批回退）。返回替换条数。 */
  function replaceAll(): number {
    const ed = editorRef.value
    if (!ed || !matches.value.length) return 0
    const list = [...matches.value].sort((a, b) => b.from - a.from)
    const tr = ed.state.tr
    for (const m of list) tr.insertText(replacement.value, m.from, m.to)
    ed.view.dispatch(tr)
    refresh()
    return list.length
  }

  // 搜索词清空即撤掉高亮（避免「关了词还满屏黄底」）
  watch(term, (v) => {
    if (!v) refresh()
  })

  return {
    open,
    term,
    replacement,
    caseSensitive,
    activeIndex,
    matches,
    focusToken,
    matchCount,
    activeLabel,
    openFind,
    close,
    setTerm,
    toggleCaseSensitive,
    next,
    prev,
    replaceCurrent,
    replaceAll,
    refresh,
  }
}
