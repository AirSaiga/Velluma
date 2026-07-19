<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useFocusTrap } from '../../../composables/useFocusTrap'
import type { BeatEditorItem, ChapterCard } from '../../../types'

const props = defineProps<{
  show: boolean
  previewBeats: BeatEditorItem[]
  beatPreviewError: string
  // CP2.5b：合并闸门——章节卡
  chapterCard?: ChapterCard | null
  planDegraded?: { reason: string; action: string; detail?: string } | null
  beatPreviewLoading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:previewBeats', beats: BeatEditorItem[]): void
  (e: 'update:chapterCard', card: ChapterCard): void
  (e: 'close'): void
  (e: 'confirm'): void
  (e: 'regenerate', editedCardFields: Record<string, any>): void
}>()

const modalRef = ref<HTMLElement | null>(null)
const showRef = computed(() => props.show)
useFocusTrap(modalRef, showRef, { onEscape: () => emit('close') })

// CP2.5b：本地章节卡编辑副本（深拷贝，避免直接改 prop）
const localCard = ref<ChapterCard | null>(null)
watch(() => props.chapterCard, (newCard) => {
  localCard.value = newCard ? JSON.parse(JSON.stringify(newCard)) : null
}, { immediate: true })

const cardCollapsed = ref(false)
const hasCard = computed(() => !!localCard.value)

const expandedBeats = ref<Set<string>>(new Set())
const editingBeats = ref<Record<string, Partial<BeatEditorItem>>>({})

function toggleBeatDetail(beatId: string) {
  if (expandedBeats.value.has(beatId)) {
    expandedBeats.value.delete(beatId)
  } else {
    expandedBeats.value.add(beatId)
  }
}

function getPovModeLabel(mode: string): string {
  const labels: Record<string, string> = {
    single: '单视角',
    ensemble: '多视角',
    omniscient: '全知'
  }
  return labels[mode] || mode
}

function getPovApertureLabel(aperture: string): string {
  const labels: Record<string, string> = {
    internal_only: '内心独白',
    subjective_observation: '主观观察',
    systemic_sense: '全景感知'
  }
  return labels[aperture] || aperture
}

function isEditing(beatId: string) {
  return beatId in editingBeats.value
}

function startEdit(beat: BeatEditorItem) {
  const id = beat.beat_id || String(beat.position)
  editingBeats.value[id] = { ...beat }
}

function cancelEdit(beat: BeatEditorItem) {
  const id = beat.beat_id || String(beat.position)
  delete editingBeats.value[id]
}

function saveEdit(beat: BeatEditorItem) {
  const id = beat.beat_id || String(beat.position)
  const edit = editingBeats.value[id]
  if (!edit) return
  const newBeats = props.previewBeats.map(b => {
    if ((b.beat_id || String(b.position)) === id) {
      return { ...b, ...edit } as BeatEditorItem
    }
    return b
  })
  emit('update:previewBeats', newBeats)
  delete editingBeats.value[id]
}

function removeBeat(target: BeatEditorItem) {
  const id = target.beat_id || String(target.position)
  const newBeats = props.previewBeats
    .filter(b => (b.beat_id || String(b.position)) !== id)
    .map((b, idx) => ({ ...b, position: idx + 1 }))
  emit('update:previewBeats', newBeats)
}

function getEditValue(beat: BeatEditorItem, key: keyof BeatEditorItem) {
  const id = beat.beat_id || String(beat.position)
  return (editingBeats.value[id]?.[key] ?? beat[key]) as any
}

function setEditValue(beat: BeatEditorItem, key: keyof BeatEditorItem, value: any) {
  const id = beat.beat_id || String(beat.position)
  if (!editingBeats.value[id]) {
    editingBeats.value[id] = { ...beat }
  }
  ;(editingBeats.value[id] as any)[key] = value
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      ref="modalRef"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3"
    >
      <div class="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-4xl max-h-[85vh] overflow-hidden flex flex-col">
        <div class="p-3 border-b border-white/60 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-[var(--text-primary)]">剧情节拍预览</h3>
          <button @click="emit('close')" class="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <div class="p-4 overflow-y-auto max-h-[calc(85vh-56px)] space-y-3">
          <!-- CP2.5b：合并闸门——章节卡编辑区（在节拍列表上方）-->
          <div v-if="hasCard && localCard" class="p-4 bg-amber-50 rounded-xl border border-amber-200 space-y-3">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <svg class="w-4 h-4 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                </svg>
                <span class="text-xs font-semibold text-amber-800">章节卡（Chapter Card）</span>
                <span v-if="planDegraded" class="px-1.5 py-0.5 text-[10px] rounded bg-orange-100 text-orange-700" :title="planDegraded.detail">
                  降级：{{ planDegraded.reason }}
                </span>
              </div>
              <div class="flex items-center gap-2">
                <button
                  @click="emit('regenerate', localCard as any)"
                  :disabled="beatPreviewLoading"
                  class="px-2 py-1 text-[11px] rounded bg-amber-200 text-amber-900 hover:bg-amber-300 disabled:opacity-50"
                  title="编辑后重新生成节拍（重规划）"
                >
                  {{ beatPreviewLoading ? '生成中...' : '重新生成节拍' }}
                </button>
                <button @click="cardCollapsed = !cardCollapsed" class="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
                  <svg class="w-4 h-4 transition-transform" :class="{ 'rotate-180': cardCollapsed }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                  </svg>
                </button>
              </div>
            </div>
            <div v-show="!cardCollapsed" class="space-y-2">
              <!-- 主旨 -->
              <div>
                <label class="text-[11px] text-[var(--text-muted)]">本章主旨（场景化语言）</label>
                <textarea
                  v-model="localCard.purpose"
                  rows="2"
                  class="w-full mt-0.5 px-2 py-1 text-xs bg-white rounded border border-amber-200 focus:border-amber-400 focus:outline-none"
                  placeholder="例：她第一次对他说谎，手在抖但语气平稳"
                ></textarea>
              </div>
              <!-- 必达事件 -->
              <div>
                <label class="text-[11px] text-[var(--text-muted)]">必达事件（每项含情绪目标）</label>
                <div class="space-y-1 mt-0.5">
                  <div
                    v-for="(ev, idx) in localCard.must_hit_events"
                    :key="idx"
                    class="flex items-center gap-1"
                  >
                    <input
                      v-model="ev.event"
                      class="flex-1 px-2 py-1 text-xs bg-white rounded border border-amber-200 focus:border-amber-400 focus:outline-none"
                      placeholder="事件描述"
                    />
                    <input
                      v-model="ev.emotion"
                      class="w-24 px-2 py-1 text-xs bg-white rounded border border-amber-200 focus:border-amber-400 focus:outline-none"
                      placeholder="情绪目标"
                    />
                    <button @click="localCard.must_hit_events.splice(idx, 1)" class="text-red-400 hover:text-red-600 text-xs">✕</button>
                  </div>
                  <button
                    @click="localCard.must_hit_events.push({ event: '', emotion: '', must: true })"
                    class="text-[11px] text-amber-700 hover:text-amber-900"
                  >+ 添加事件</button>
                </div>
              </div>
              <!-- 量化字段 -->
              <div class="grid grid-cols-3 gap-2">
                <div>
                  <label class="text-[11px] text-[var(--text-muted)]">目标字数</label>
                  <input
                    v-model.number="localCard.word_target"
                    type="number"
                    min="500"
                    step="500"
                    class="w-full mt-0.5 px-2 py-1 text-xs bg-white rounded border border-amber-200 focus:border-amber-400 focus:outline-none"
                  />
                </div>
                <div>
                  <label class="text-[11px] text-[var(--text-muted)]">节奏</label>
                  <select
                    v-model="localCard.pacing"
                    class="w-full mt-0.5 px-2 py-1 text-xs bg-white rounded border border-amber-200 focus:border-amber-400 focus:outline-none"
                  >
                    <option value="fast">快</option>
                    <option value="medium">中</option>
                    <option value="slow">慢</option>
                  </select>
                </div>
                <div>
                  <label class="text-[11px] text-[var(--text-muted)]">张力 (1-10)</label>
                  <input
                    v-model.number="localCard.tension"
                    type="number"
                    min="1"
                    max="10"
                    class="w-full mt-0.5 px-2 py-1 text-xs bg-white rounded border border-amber-200 focus:border-amber-400 focus:outline-none"
                  />
                </div>
              </div>
            </div>
          </div>

          <!-- 节拍列表 -->
          <div v-if="previewBeats.length === 0" class="text-center text-[var(--text-muted)] text-sm py-8">
            暂无预览数据
          </div>
          <div
            v-for="beat in previewBeats"
            :key="beat.beat_id || beat.position"
            class="p-4 bg-[var(--bg-panel)] rounded-xl border border-[var(--border-color)] space-y-3"
          >
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="text-xs font-medium text-[var(--accent-500)]">Beat {{ beat.position }}</span>
                <span v-if="beat.pov_mode" class="px-1.5 py-0.5 text-[10px] rounded bg-blue-100 text-blue-700">
                  {{ getPovModeLabel(beat.pov_mode) }}
                </span>
              </div>
              <div class="flex items-center gap-2">
                <span v-if="!isEditing(beat.beat_id || String(beat.position))" class="text-[10px] text-[var(--text-muted)]">{{ beat.word_count_target || beat.target_words }}字</span>
                <button
                  v-if="!isEditing(beat.beat_id || String(beat.position))"
                  @click="startEdit(beat)"
                  class="text-[10px] px-2 py-1 rounded bg-[var(--bg-canvas)] text-[var(--text-secondary)] hover:text-[var(--accent-500)] transition-colors"
                >
                  编辑
                </button>
                <template v-else>
                  <button
                    @click="cancelEdit(beat)"
                    class="text-[10px] px-2 py-1 rounded bg-[var(--bg-canvas)] text-[var(--text-secondary)] hover:text-rose-500 transition-colors"
                  >
                    取消
                  </button>
                  <button
                    @click="saveEdit(beat)"
                    class="text-[10px] px-2 py-1 rounded bg-[var(--accent-500)] text-white hover:bg-accent-600 transition-colors"
                  >
                    保存
                  </button>
                </template>
                <button
                  @click="removeBeat(beat)"
                  class="text-[10px] px-2 py-1 rounded bg-rose-50 text-rose-500 hover:bg-rose-100 transition-colors"
                  title="删除此节拍"
                >
                  删除
                </button>
              </div>
            </div>

            <div v-if="!isEditing(beat.beat_id || String(beat.position))">
              <p class="text-sm text-[var(--text-primary)] leading-relaxed">{{ beat.summary }}</p>
            </div>
            <div v-else class="space-y-2">
              <textarea
                :value="getEditValue(beat, 'summary')"
                @input="(e) => setEditValue(beat, 'summary', (e.target as HTMLTextAreaElement).value)"
                rows="2"
                class="w-full px-2.5 py-2 rounded-lg bg-[var(--bg-canvas)] text-[var(--text-primary)] text-xs leading-relaxed focus:outline-none ring-1 ring-transparent focus:ring-[var(--accent-500)] resize-none"
                placeholder="节拍摘要..."
              />
              <div class="flex items-center gap-2">
                <label class="text-[10px] text-[var(--text-muted)]">字数目标</label>
                <input
                  type="number"
                  :value="getEditValue(beat, 'word_count_target') || getEditValue(beat, 'target_words')"
                  @input="(e) => setEditValue(beat, 'word_count_target', Number((e.target as HTMLInputElement).value))"
                  class="w-20 px-2 py-1 rounded bg-[var(--bg-canvas)] text-[var(--text-primary)] text-xs focus:outline-none focus:ring-1 focus:ring-[var(--accent-500)]"
                />
                <label class="text-[10px] text-[var(--text-muted)]">视角角色</label>
                <input
                  :value="getEditValue(beat, 'pov_character')"
                  @input="(e) => setEditValue(beat, 'pov_character', (e.target as HTMLInputElement).value)"
                  class="flex-1 min-w-0 px-2 py-1 rounded bg-[var(--bg-canvas)] text-[var(--text-primary)] text-xs focus:outline-none focus:ring-1 focus:ring-[var(--accent-500)]"
                />
              </div>
            </div>

            <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--text-muted)]">
              <span v-if="beat.location" class="flex items-center gap-1">
                <span>📍</span>
                <span>{{ beat.location }}</span>
              </span>
              <span v-if="beat.pov_character" class="flex items-center gap-1">
                <span>👤</span>
                <span>{{ beat.pov_character }}</span>
              </span>
              <span v-if="beat.pov_aperture" class="flex items-center gap-1">
                <span>🔍</span>
                <span>{{ getPovApertureLabel(beat.pov_aperture) }}</span>
              </span>
              <span v-if="beat.hook_ids && beat.hook_ids.length > 0" class="flex items-center gap-1">
                <span></span>
                <span>{{ beat.hook_ids.join(' / ') }}</span>
              </span>
            </div>

            <button
              @click="toggleBeatDetail(beat.beat_id || String(beat.position))"
              class="text-xs text-[var(--accent-500)] hover:text-[var(--accent-600)] transition-colors"
            >
              {{ expandedBeats.has(beat.beat_id || String(beat.position)) ? '收起详情' : '展开详情 ↓' }}
            </button>

            <div
              v-if="expandedBeats.has(beat.beat_id || String(beat.position))"
              class="space-y-2 pt-2 border-t border-[var(--border-color)]"
            >
              <div v-if="beat.action_summary" class="text-xs">
                <span class="text-[var(--text-secondary)] font-medium">动作摘要：</span>
                <span class="text-[var(--text-primary)]">{{ beat.action_summary }}</span>
              </div>
              <div v-if="beat.openingState || beat.stoppingState" class="text-xs space-y-1">
                <div>
                  <span class="text-[var(--text-secondary)] font-medium">进入状态：</span>
                  <span class="text-[var(--text-primary)]">{{ beat.openingState || '—' }}</span>
                </div>
                <div>
                  <span class="text-[var(--text-secondary)] font-medium">离开状态：</span>
                  <span class="text-[var(--text-primary)]">{{ beat.stoppingState || '—' }}</span>
                </div>
              </div>
              <div v-if="beat.worldbuilding_instruction" class="text-xs">
                <span class="text-[var(--text-secondary)] font-medium">世界观指令：</span>
                <span class="text-[var(--text-primary)]">{{ beat.worldbuilding_instruction }}</span>
              </div>
              <div v-if="beat.forbiddenEventsText" class="text-xs">
                <span class="text-[var(--text-secondary)] font-medium">红线约束：</span>
                <span class="text-red-600">{{ beat.forbiddenEventsText }}</span>
              </div>
              <div v-if="beat.pov_characters && beat.pov_characters.length > 0" class="text-xs">
                <span class="text-[var(--text-secondary)] font-medium">多视角角色：</span>
                <span class="text-[var(--text-primary)]">{{ beat.pov_characters.join('、') }}</span>
              </div>
            </div>
          </div>
          <div class="flex justify-end gap-2 pt-2">
            <button @click="emit('close')" class="px-3 py-1.5 text-xs rounded-lg bg-[var(--bg-panel)] text-[var(--text-secondary)] hover:bg-parchment-100">
              取消
            </button>
            <button @click="emit('confirm')" class="px-3 py-1.5 text-xs rounded-lg bg-[var(--accent-500)] text-white hover:bg-accent-600">
              确认并生成
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
