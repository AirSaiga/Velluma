<script setup lang="ts">
/**
 * NLE-ADF 2.0「本章聚焦」面板（记忆倒灌可视化）。
 *
 * 设计稿隐形抽屉的核心内容：让作者看到 AI 在后台偷偷记了什么——
 * 每拍锁死时 Loop3 抽取的涌现实体/关系变化/新地点/大纲补遗，逐拍累积在此。
 * 信任的来源：倒灌不再是无形的黑盒。
 *
 * 上半 = 本章关联角色（设定库链接态）；下半 = 涌现记录（按拍分组，最新在上）。
 */
import { computed } from 'vue'
import type { GenerationSession } from '../composables/useGenerationSession'
import type { Character } from '../../../types'

const props = defineProps<{
  session: GenerationSession
  characters: Character[]
  linkedIds: string[]
}>()

interface FocusEntry {
  key: string
  icon: string
  name: string
  detail: string
  beatId: string
  beatIndex: number
}

/** 涌现条目共性化：LLM 产出 dict 的键不稳定，防御式取名/摘要 */
function _normalize(item: any): { name: string; detail: string } {
  if (typeof item === 'string') return { name: item, detail: '' }
  if (!item || typeof item !== 'object') return { name: String(item ?? ''), detail: '' }
  const name = item.name || item.entity || item.character || item.title || item.location || ''
  const detail =
    item.summary || item.description || item.change || item.state || item.note || item.status || ''
  return { name: String(name), detail: String(detail) }
}

const emergentEntries = computed<FocusEntry[]>(() => {
  const facts = props.session.emergentFacts.value
  const slots = props.session.beatSlots.value
  const out: FocusEntry[] = []
  for (const [beatId, f] of Object.entries(facts)) {
    if (!f || typeof f !== 'object') continue
    const beatIndex = slots.find((s) => s.beat_id === beatId)?.segment_index ?? 0
    const groups: Array<[string, string, any[]]> = [
      ['new_entities', '👤', (f as any).new_entities],
      ['relationship_changes', '🔗', (f as any).relationship_changes],
      ['new_locations', '📍', (f as any).new_locations],
      ['outline_addenda', '📝', (f as any).outline_addenda],
    ]
    for (const [key, icon, list] of groups) {
      if (!Array.isArray(list)) continue
      for (const item of list) {
        const { name, detail } = _normalize(item)
        if (!name) continue
        out.push({ key: `${beatId}:${key}:${name}`, icon, name, detail, beatId, beatIndex })
      }
    }
  }
  // 最新拍的记录排前面
  return out.sort((a, b) => b.beatIndex - a.beatIndex)
})

const linkedCharacters = computed(() =>
  props.characters.filter((c) => props.linkedIds.includes(c.id)),
)

/** 本章缺口（Loop1 大纲自检产出，source=loop1_gap 的决策节点）。
 *  NLE-ADF 2.0 改道：缺口永不拦路（岔路门已 JIT 化到代笔时），
 *  在此被动展示供作者参考——"缺口的家是抽屉，不是横幅"。 */
const gapNodes = computed(() => {
  const ds = props.session.decisionSet.value
  if (!ds?.decision_nodes?.length) return []
  const slots = props.session.beatSlots.value
  return ds.decision_nodes
    .filter((n: any) => n?.source === 'loop1_gap')
    .map((n: any) => ({
      beatId: n.beat_id,
      title: n.node_title,
      beatIndex: slots.find((s) => s.beat_id === n.beat_id)?.segment_index ?? 0,
    }))
})
</script>

<template>
  <div class="focus-panel">
    <!-- 本章关联角色 -->
    <section class="focus-section">
      <h3 class="focus-title">📌 本章聚焦（{{ linkedCharacters.length }}）</h3>
      <div v-if="linkedCharacters.length" class="focus-list">
        <div v-for="c in linkedCharacters" :key="c.id" class="focus-item">
          <span class="focus-icon">👤</span>
          <span class="focus-name">{{ c.name }}</span>
          <span v-if="c.dynamic_state" class="focus-detail">
            {{ c.dynamic_state }}
          </span>
        </div>
      </div>
      <p v-else class="focus-empty">本章尚未关联角色（「设定」标签可勾选）</p>
    </section>

    <!-- 本章缺口（Loop1 自检；被动展示，永不拦路） -->
    <section v-if="gapNodes.length" class="focus-section">
      <h3 class="focus-title">🕳 本章缺口（{{ gapNodes.length }}）</h3>
      <p class="focus-hint">大纲自检发现的待补信息；召唤代笔到对应拍时可顺手补充</p>
      <div class="focus-list">
        <div v-for="g in gapNodes" :key="g.beatId" class="focus-item">
          <span class="focus-icon">🕳</span>
          <span class="focus-beat">拍 {{ g.beatIndex + 1 }}</span>
          <span class="focus-detail">{{ g.title }}</span>
        </div>
      </div>
    </section>

    <!-- 记忆倒灌：涌现记录 -->
    <section class="focus-section">
      <h3 class="focus-title">🌱 涌现记录（{{ emergentEntries.length }}）</h3>
      <p class="focus-hint">每拍锁死时 AI 在后台提取的新实体/变化（Loop3 记忆倒灌）</p>
      <div v-if="emergentEntries.length" class="focus-list">
        <div v-for="e in emergentEntries" :key="e.key" class="focus-item">
          <span class="focus-icon">{{ e.icon }}</span>
          <span class="focus-name">{{ e.name }}</span>
          <span class="focus-beat">拍 {{ e.beatIndex + 1 }}</span>
          <span v-if="e.detail" class="focus-detail">{{ e.detail }}</span>
        </div>
      </div>
      <p v-else class="focus-empty">锁死第一拍后，这里会开始累积 AI 记下的设定变化</p>
    </section>
  </div>
</template>

<style scoped>
.focus-panel {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  font-size: 13px;
}

.focus-title {
  color: var(--text-primary, #e0e2e8);
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.focus-hint {
  color: var(--text-muted, #8b8f98);
  font-size: 11px;
  margin: -4px 0 8px;
}

.focus-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.focus-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
  flex-wrap: wrap;
}

.focus-icon {
  flex-shrink: 0;
}

.focus-name {
  color: var(--text-primary, #e0e2e8);
  font-weight: 500;
}

.focus-beat {
  color: #34d399;
  font-size: 11px;
  flex-shrink: 0;
}

.focus-detail {
  flex-basis: 100%;
  color: var(--text-muted, #8b8f98);
  font-size: 12px;
  line-height: 1.5;
}

.focus-empty {
  color: var(--text-muted, #8b8f98);
  font-size: 12px;
  padding: 8px;
  border: 1px dashed rgba(42, 45, 53, 0.9);
  border-radius: 6px;
}
</style>
