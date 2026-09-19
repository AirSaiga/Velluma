<script setup lang="ts">
/**
 * 禁词扫描审稿模态（S3 E3）——三层禁词命中清单 + 逐条裁决。
 *
 * 红线：绝不静默改正文——每条命中由作者选「替换（应用替代词到本章）/ 仅收入清单 / 忽略」。
 * 替换动作由容器执行（chapterApi.update 后台改 content_text，作者回写作台即见）。
 */
import { ref, watch } from 'vue'
import Icon from '../../../components/Icon.vue'
import ModalShell from '../../../components/ModalShell.vue'
import type { StyleScanResult, StyleScanHit } from '../../../types'

const props = defineProps<{
  open: boolean
  chapters: Array<{ id: string; chapter_number: number; title: string | null }>
  scanning: boolean
  result: StyleScanResult | null
  /** 已裁决的词（前端记状态，避免重复操作） */
  resolvedWords: string[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'scan', chapterId: string): void
  (e: 'apply', hit: StyleScanHit): void
  (e: 'collect', hit: StyleScanHit): void
  (e: 'ignore', hit: StyleScanHit): void
}>()

const selectedChapterId = ref('')

watch(
  () => props.open,
  (open) => {
    if (open && !selectedChapterId.value && props.chapters.length > 0) {
      selectedChapterId.value = props.chapters[props.chapters.length - 1].id
    }
  },
)

watch(
  () => props.chapters,
  (list) => {
    if (list.length > 0 && !list.some(c => c.id === selectedChapterId.value)) {
      selectedChapterId.value = list[list.length - 1].id
    }
  },
)

function isResolved(word: string): boolean {
  return props.resolvedWords.includes(word)
}
</script>

<template>
  <ModalShell v-if="open" title="禁词扫描（审稿模式）" width="36rem" @close="emit('close')">
        <div class="modal-body">
          <p class="modal-note">
            用三层禁词（系统陈词库 + 本书黑名单 + 负面清单）扫描本章正文。
            命中后由你逐条裁决——替换、收入清单或忽略，绝不静默改正文。
          </p>

          <div class="scan-toolbar">
            <select v-model="selectedChapterId" class="chapter-select">
              <option v-for="c in chapters" :key="c.id" :value="c.id">
                第{{ c.chapter_number }}章 {{ c.title || '' }}
              </option>
            </select>
            <button
              class="btn-primary"
              :disabled="scanning || !selectedChapterId"
              @click="emit('scan', selectedChapterId)"
            >{{ scanning ? '扫描中…' : '扫描本章' }}</button>
          </div>

          <div v-if="result && result.hits.length === 0 && !scanning" class="empty-note">
            干净——本章没有命中任何禁词。
          </div>
          <div
            v-for="hit in result?.hits || []"
            :key="hit.word"
            class="hit-card"
            :class="{ resolved: isResolved(hit.word) }"
          >
            <div class="hit-head">
              <span class="hit-word">「{{ hit.word }}」</span>
              <span class="hit-count">× {{ hit.count }}</span>
              <span v-if="hit.severity === 'blocker'" class="hit-sev" title="硬禁：检查时命中即判不通过（只提示，绝不自动改正文）">硬禁</span>
              <span v-if="hit.alternative" class="hit-alt">
                <Icon name="arrow-right" :size="12" /> {{ hit.alternative }}
              </span>
              <span v-else class="hit-alt dim">（无替代建议）</span>
            </div>
            <p class="hit-context">…{{ hit.occurrences[0]?.context }}…</p>
            <div class="hit-actions">
              <template v-if="!isResolved(hit.word)">
                <button
                  v-if="hit.alternative"
                  class="btn-mini btn-apply"
                  @click="emit('apply', hit)"
                >替换为「{{ hit.alternative }}」（{{ hit.count }} 处）</button>
                <button class="btn-mini btn-collect" @click="emit('collect', hit)">仅收入清单</button>
                <button class="btn-mini btn-ignore" @click="emit('ignore', hit)">忽略</button>
              </template>
              <span v-else class="hit-done"><Icon name="check-circle" :size="12" /> 已处理</span>
            </div>
          </div>
        </div>

        <template #footer>
          <button class="btn-ghost" @click="emit('close')">关闭</button>
        </template>
  </ModalShell>
</template>

<style scoped>
.modal-body {
  flex: 1;
  padding: 1rem;
  overflow-y: auto;
}
.modal-note {
  margin: 0 0 0.75rem;
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--text-muted);
}
.scan-toolbar {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.chapter-select {
  flex: 1;
  min-width: 0;
  padding: 0.375rem 0.5rem;
  font-size: var(--text-base);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
.btn-primary {
  min-height: 28px;
  padding: 0.375rem 0.875rem;
  font-size: var(--text-base);
  color: var(--bg-canvas);
  background: var(--accent-500);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-primary:disabled {
  opacity: 0.5;
}
.empty-note {
  padding: 1.5rem 0;
  font-size: 0.8125rem;
  text-align: center;
  color: var(--ok);
}
.hit-card {
  padding: 0.625rem var(--space-3);
  margin-bottom: var(--space-2);
  background: var(--surface-card);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
}
.hit-card.resolved {
  opacity: 0.55;
}
.hit-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.hit-word {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary);
}
.hit-count {
  padding: 0.0625rem 0.375rem;
  font-size: var(--text-xs);
  color: var(--danger);
  background: var(--danger-bg);
  border-radius: var(--radius-xs);
}
/* 硬禁档标识（Phase 3：与负面清单/系统陈词库同款红 chip） */
.hit-sev {
  padding: 0.0625rem 0.3125rem;
  font-size: var(--text-xs);
  color: var(--danger);
  background: var(--danger-bg);
  border-radius: var(--radius-xs);
}
.hit-alt {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--ok);
}
.hit-alt.dim {
  color: var(--text-muted);
}
.hit-context {
  margin: 0.375rem 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.hit-actions {
  display: flex;
  gap: 0.375rem;
  flex-wrap: wrap;
}
.btn-mini {
  padding: 0.25rem 0.5625rem;
  font-size: var(--text-xs);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.btn-apply {
  color: var(--bg-canvas);
  background: var(--accent-500);
}
.btn-apply:hover {
  background: var(--accent-600);
}
.btn-collect {
  color: var(--warn);
  background: var(--warn-bg);
}
.btn-ignore {
  color: var(--text-muted);
  background: var(--bg-tertiary);
}
.hit-done {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: var(--text-xs);
  color: var(--ok);
}
.btn-ghost {
  min-height: 28px;
  padding: 0.375rem 0.75rem;
  font-size: var(--text-base);
  color: var(--text-secondary);
  background: var(--surface-overlay);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
</style>
