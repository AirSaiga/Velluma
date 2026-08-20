/**
 * 叙事时间来源可见 + 录入侧警示的纯函数（A4，docs/foundation-hardening.md §2.2）。
 *
 * 两个消费方：
 * - WorldSceneSlice（写作页切片条）：时刻行来源小字 + 锚定本章按钮的显隐
 * - QuickCapturePanel（世界页快速录入）：未来事件内联警示的显隐与文案
 *
 * 纯展示/提示逻辑，不含任何请求；判定口径与后端 resolve_narrative_time
 * 四级降级对齐（本章锚 → 前序最近锚 → 事件最大时刻 → 0），红线：只提示不拦截。
 */

/** 切片条来源小字输入（scene-slice 的 t_source / t_source_note / t_source_chapter） */
export interface NarrativeSourceInfo {
  source: string
  /** prev_anchor 来源章号（缺席 = 后端未取到） */
  chapter?: number | null
  /** max_event 来源事件摘要（截 30 字；缺席 = 后端未取到） */
  note?: string | null
}

/**
 * 时刻行来源小字：来自本章锚 / 来自第N章锚 / 来自事件『……』 / 未锚定。
 * 附加信息缺席时退到该 source 的无细节说法（不猜数据）。
 */
export function narrativeSourceText(info: NarrativeSourceInfo): string {
  switch (info.source) {
    case 'chapter_anchor':
      return '来自本章锚'
    case 'prev_anchor':
      return info.chapter != null ? `来自第${info.chapter}章锚` : '来自前章锚'
    case 'max_event':
      return info.note ? `来自事件『${info.note}』` : '来自最远事件'
    default:
      return '未锚定'
  }
}

/** 录入侧警示输入：全部章节锚投影（narrative_time=null 即未锚）+ 事件流最大时刻 */
export interface FutureEventWarnInput {
  /** 新事件的 time_start（连续日计数） */
  timeStart: number
  /** 全部章节的锚投影；空数组 = 取不到锚定信息（静默不警示） */
  chapterAnchors: { narrative_time: number | null }[]
  /** 现有事件流最大 time_start（无锚书的当前叙事基准；无事件按 0） */
  maxEventTime?: number
}

/** 未来事件警示文案（null = 不显示） */
export const FUTURE_EVENT_WARN = (day: number) =>
  `此事件晚于当前叙事时刻，未锚定章节的『此刻』将被拉到第 ${day} 日`

/**
 * 录入侧警示判定（只提示不拦截）：
 * - 有锚书：time_start 大于当前最大章锚才警示（未超出 = 无人被拉动）；
 * - 无锚书：time_start 大于事件流最大时刻（= 未锚章节当前所处的叙事基准）才警示；
 * - 章节全部已锚 / 锚定信息缺席（无章节数据）→ 静默不显示（警示语义为空）。
 */
export function futureEventWarning(input: FutureEventWarnInput): string | null {
  const { timeStart, chapterAnchors } = input
  if (!chapterAnchors.length) return null // 取不到锚定信息：静默
  const anchored = chapterAnchors.filter((c) => c.narrative_time != null) as {
    narrative_time: number
  }[]
  const hasUnanchored = anchored.length < chapterAnchors.length
  if (!hasUnanchored) return null // 全部章节已锚：无人会被拉动

  if (anchored.length) {
    const maxAnchor = Math.max(...anchored.map((c) => c.narrative_time))
    return timeStart > maxAnchor ? FUTURE_EVENT_WARN(timeStart) : null
  }
  const maxEvent = input.maxEventTime ?? 0
  return timeStart > maxEvent ? FUTURE_EVENT_WARN(timeStart) : null
}
