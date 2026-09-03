import { ref, watch, type Ref } from 'vue'
import { adaptiveApi, type ChapterSpine } from '../../../services/api/domain/adaptive.api'
import { plotLedgerApi } from '../../../services/api/domain'
import type { PlotLedgerEntry } from '../../../services/api/domain'
import { readerMirrorApi } from '../../../services/api/domain/reader-mirror.api'
import { canonApi } from '../../../services/api/domain/canon.api'
import { groupReveals, type StorylineLedger } from '../engine/storyline'

interface TensionRaw {
  chapter_number: number
  overall_tension: number
  is_payoff_chapter?: boolean
}

/**
 * 伏笔账本 API 字段 → 引擎形状的边界映射（created_at_chapter → plantedChapter）。
 * 引擎纯函数只认引擎接口字段；在此一处转换，防字段名漂移静默清空弧线。
 */
function toStorylineLedger(l: PlotLedgerEntry): StorylineLedger {
  return {
    id: l.id,
    content: l.content,
    status: l.status,
    plantedChapter: l.created_at_chapter ?? null,
    resolvedChapterId: l.resolved_in_chapter_id ?? null,
  }
}

/**
 * 故事线俯视板数据聚合：spine（逐章）/ 伏笔账本 / 张力曲线 / 真相揭示点。
 *
 * 四路全并行、逐路降级（任一路失败不影响其余——张力曲线与真相多为空数据，
 * 不是错误）；带过期响应守卫（快速切书旧响应整包丢弃，与 useWorld 同纪律）。
 * spine 无批量端点（章列表响应不含 spine 列），逐章 GET 并行拉取，单章失败静默 null。
 */
export function useStoryline(bookId: Ref<string | null>, chapterIds: Ref<string[]>) {
  /** 章ID → spine（null = 无打算/加载失败，卡片按缺席处理） */
  const spines = ref<Record<string, ChapterSpine | null>>({})
  const ledgers = ref<StorylineLedger[]>([])
  const tensionSamples = ref<TensionRaw[]>([])
  /** 章号 → 该章计划揭示的真相标题列表 */
  const reveals = ref<Map<number, string[]>>(new Map())
  const loading = ref(false)
  /** spine 缓存归属的书（切书不继承旧书章 spine） */
  let spineBook: string | null = null

  async function loadSpines(ids: string[], loaded: Record<string, ChapterSpine | null>) {
    const missing = ids.filter((id) => !(id in loaded))
    if (missing.length === 0) return loaded
    const entries = await Promise.all(
      missing.map(async (id) => {
        try {
          const r = await adaptiveApi.getSpine(id)
          return [id, r.spine] as const
        } catch {
          return [id, null] as const
        }
      }),
    )
    return { ...loaded, ...Object.fromEntries(entries) }
  }

  async function load() {
    const bid = bookId.value
    if (!bid) {
      spines.value = {}
      ledgers.value = []
      tensionSamples.value = []
      reveals.value = new Map()
      spineBook = null
      loading.value = false
      return
    }
    loading.value = true
    const base = spineBook === bid ? spines.value : {}
    const [ls, tension, nodes, spineMap] = await Promise.all([
      plotLedgerApi
        .listByBook(bid)
        .then((entries) => entries.map(toStorylineLedger))
        .catch(() => [] as StorylineLedger[]),
      readerMirrorApi
        .get(bid)
        .then((d) => d.tension_curve || [])
        .catch(() => [] as TensionRaw[]),
      canonApi
        .listNodes(bid)
        .then((ns) => groupReveals(ns))
        .catch(() => new Map<number, string[]>()),
      loadSpines(chapterIds.value, base),
    ])
    // 过期守卫：加载期间切书，旧响应整包丢弃
    if (bookId.value !== bid) return
    spines.value = spineMap
    spineBook = bid
    ledgers.value = ls
    tensionSamples.value = tension
    reveals.value = nodes
    loading.value = false
  }

  watch(bookId, () => load(), { immediate: true })
  // 新建章节 → 只补拉缺失章的 spine（账本/张力/真相按书加载不随章集变）
  watch(
    () => chapterIds.value.join(','),
    () => {
      const bid = bookId.value
      if (!bid || spineBook !== bid) return
      loadSpines(chapterIds.value, spines.value).then((m) => {
        if (bookId.value === bid && spineBook === bid) spines.value = m
      })
    },
  )

  return { spines, ledgers, tensionSamples, reveals, loading, reload: load }
}
