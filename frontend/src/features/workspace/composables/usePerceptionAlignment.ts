import { ref, watch, onBeforeUnmount, type Ref } from 'vue'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'

/**
 * 感知带按行对齐：把每个 Canon hint 的 label 锚定到正文里对应词的垂直位置。
 *
 * 原理：CanonHighlight 扩展已给正文里的角色名/伏笔词打了 .canon-mark 标记。
 * 本 composable 查这些 DOM 元素的视口 Y，换算成相对感知带容器的 top，
 * 让感知卡 absolute 锚定到「对应正文行」——视觉上指哪打哪。
 *
 * 滚动：监听编辑器滚动容器，rAF 节流重算（coords 随滚动变）。
 * 文档变化（打字/hints 更新）也重算。
 *
 * 找不到正文位置的 label（orphan hook / leak 等，label 不在当前段落）
 * 返回 null，由 PerceptionBand 放底部兜底区。
 */

/** 锚定卡最小避让（header 保底；顶部固定区实高由 reserveTop 动态传入） */
const RESERVED_FLOOR = 40
/** 编辑器滚动容器选择器（RichTextEditor 的 .overflow-y-auto） */
const SCROLL_HOST_SEL = '.overflow-y-auto'

export function usePerceptionAlignment(
  labels: Ref<string[]>,
  bandEl: Ref<HTMLElement | null>,
  /** 顶部固定区实高（header+谋篇行+镜头碎片舱），锚定卡避让到它之下。
   *  动态传入——舱体 4 挂件可占 ~230px，旧硬编码 92 只够 header+spine，
   *  卡位落进舱体范围会被 z-2 的舱盖住（2026-08-27 实测事故）。 */
  reserveTop?: Ref<number>,
) {
  /** 每个 label 相对感知带的 top（px）；null = 找不到正文位置 */
  const anchors = ref<(number | null)[]>([])
  const reserve = reserveTop ?? ref(0)
  let scrollHost: HTMLElement | null = null
  let rafId: number | null = null

  /** 找 label 在正文里第一次出现的视口 top（通过 canon-mark 标记元素） */
  function findLabelViewportTop(editor: any, label: string): number | null {
    if (!label || label.length < 2) return null
    try {
      const marks = editor.view.dom.querySelectorAll('.canon-mark')
      for (const el of marks) {
        if ((el.textContent || '').includes(label)) {
          return (el as HTMLElement).getBoundingClientRect().top
        }
      }
    } catch {
      // editor 不在 / DOM 查询失败 → null
    }
    return null
  }

  function recompute() {
    const editor = chapterEditorHandle.value
    const band = bandEl.value
    const list = labels.value
    if (!editor || !band || list.length === 0) {
      anchors.value = list.map(() => null)
      return
    }
    const bandRect = band.getBoundingClientRect()
    anchors.value = list.map((label) => {
      const viewportY = findLabelViewportTop(editor, label)
      if (viewportY === null) return null
      const relY = viewportY - bandRect.top
      // 避让顶部固定区（实高动态测得，40px 保底）；负值（label 在可见区上方）也压进去
      return Math.max(relY, reserve.value, RESERVED_FLOOR)
    })
  }

  /** rAF 节流：一帧最多重算一次（scroll 高频） */
  function scheduleRecompute() {
    if (rafId !== null) return
    rafId = requestAnimationFrame(() => {
      rafId = null
      recompute()
    })
  }

  function setupScroll() {
    cleanupScroll()
    const editor = chapterEditorHandle.value
    if (!editor) return
    try {
      scrollHost = editor.view.dom.closest(SCROLL_HOST_SEL) as HTMLElement | null
    } catch {
      scrollHost = null
    }
    if (scrollHost) {
      scrollHost.addEventListener('scroll', scheduleRecompute, { passive: true })
    }
  }

  function cleanupScroll() {
    if (scrollHost) {
      scrollHost.removeEventListener('scroll', scheduleRecompute)
      scrollHost = null
    }
  }

  // labels 变化（新 hints 到）或编辑器实例变化 → 重算 + 重挂滚动监听
  watch(
    [labels, chapterEditorHandle],
    () => {
      recompute()
      setupScroll()
    },
    { immediate: true },
  )

  // 编辑器文档变化（打字/缝合）→ 重算（label 位置可能变）
  watch(
    chapterEditorHandle,
    (editor, prev) => {
      prev?.off('update', scheduleRecompute)
      editor?.on('update', scheduleRecompute)
    },
    { immediate: true },
  )

  // 顶部固定区实高变化（舱弹出/收起/挂件增减）→ 重算（锚定卡避让线随动）
  watch(reserve, () => { scheduleRecompute() })

  onBeforeUnmount(() => {
    cleanupScroll()
    if (rafId !== null) cancelAnimationFrame(rafId)
    const editor = chapterEditorHandle.value
    editor?.off('update', scheduleRecompute)
  })

  return { anchors, recompute }
}
