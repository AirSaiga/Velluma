/**
 * 开章卡状态（01 下一阶段 M1）：拉取 + 展开态 + 专用计数。
 *
 * 纯查表零 LLM；数据形状 OpeningCard（每行独立空集缺席）。展开=就地看完整
 * 内容（表/里/揭示计划原文），一次点击彻底回答——不跳世界页（规则二）。
 * 计数走 opening-card/touch（05 瘦身后专用 jsonl，不接协作事件总线）。
 */
import { ref, watch, type Ref } from 'vue'
import { adaptiveApi, type OpeningCard } from '../../../services/api/domain/adaptive.api'

const card = ref<OpeningCard | null>(null)
const loading = ref(false)
const expanded = ref<Set<string>>(new Set())
/** 每章只记一次 shown（心跳级重挂载不重复计数） */
const shownFor = ref<string | null>(null)

async function load(chapterId: string) {
  loading.value = true
  try {
    card.value = await adaptiveApi.getOpeningCard(chapterId)
    // 有任何一行可显示才计 shown（空卡片 {} 不算出现——空集零像素的同口径）
    if (card.value && Object.keys(card.value).length > 0 && shownFor.value !== chapterId) {
      shownFor.value = chapterId
      void adaptiveApi.touchOpeningCard(chapterId, 'shown').catch(() => {})
    }
  } catch {
    card.value = null
  } finally {
    loading.value = false
  }
}

function toggleExpand(chapterId: string, key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
    void adaptiveApi.touchOpeningCard(chapterId, 'expand').catch(() => {})
  }
  expanded.value = next
}

function reset() {
  expanded.value = new Set()
}

export function useOpeningCard(chapterId: Ref<string | null>) {
  watch(
    chapterId,
    (id) => {
      reset()
      if (id) void load(id)
      else card.value = null
    },
    { immediate: true },
  )
  return { card, loading, expanded, toggleExpand }
}
