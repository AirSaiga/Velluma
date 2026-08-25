<script setup lang="ts">
/**
 * 全书通读模态（2026-08-25「系统自己去读」存量首秀入口）。
 *
 * 流程：介绍 → 阶段 A 认人（进度）→ 实体过目（勾选）→ 阶段 B 记事（进度）→ 完成。
 * 职责切分：本组件只渲染 + 抛动作，编排全在 useReadBook（composable 层）。
 */
import ModalShell from './ModalShell.vue'
import type { EntityCandidate, LocationCandidate, ReadBookPhase } from '../composables/useReadBook'

const props = defineProps<{
  phase: ReadBookPhase
  progress: { done: number; total: number; label: string } | null
  entityCandidates: EntityCandidate[]
  locationCandidates: LocationCandidate[]
  createdEntities: number
  createdCandidates: number
  skippedCount: number
  errorMsg: string
  reviewCount: number
  /** 建设期忙碌闸（防连点重复建实体，2026-08-26 实测事故） */
  creating: boolean
  createProgress: { done: number; total: number } | null
}>()

const emit = defineEmits<{
  close: []
  cancel: []
  confirmEntities: []
}>()
</script>

<template>
  <ModalShell
    title="让 AI 通读本书"
    subtitle="它自己读正文，把发现的人物与世界变化放进待确认——你只需过目"
    width="560px"
    @close="emit('close')"
  >
    <!-- 阶段 A/B 进度 -->
    <div v-if="phase === 'entities' || phase === 'events'" class="rb-progress">
      <p class="rb-progress__label">
        {{ phase === 'entities' ? '正在认人（第' : '正在记事（第' }}{{ progress?.done }}/{{ progress?.total }}章）<template v-if="progress?.label">：{{ progress.label }}</template>
      </p>
      <div class="rb-bar">
        <div
          class="rb-bar__fill"
          :style="{ width: progress && progress.total ? (progress.done / progress.total * 100) + '%' : '0%' }"
        />
      </div>
      <p class="rb-note">已读过的章会自动跳过，中断后重跑只补未读的。</p>
      <button class="rb-btn rb-btn--ghost" @click="emit('cancel')">中断</button>
    </div>

    <!-- 实体过目 -->
    <div v-else-if="phase === 'review'" class="rb-review">
      <template v-if="entityCandidates.length || locationCandidates.length">
        <p class="rb-review__lead">通读发现这些人物与地点——勾掉的不会建。确认后接着记事。</p>
        <div v-if="entityCandidates.length" class="rb-group">
          <div class="rb-group__label">人物与势力</div>
          <label v-for="c in entityCandidates" :key="c.name" class="rb-row">
            <input v-model="c.checked" type="checkbox" />
            <span class="rb-row__name">{{ c.name }}</span>
            <span class="rb-row__desc">{{ c.description }}</span>
            <span v-if="c.mentions > 1" class="rb-row__meta">{{ c.mentions }} 章出现</span>
          </label>
        </div>
        <div v-if="locationCandidates.length" class="rb-group">
          <div class="rb-group__label">地点</div>
          <label v-for="c in locationCandidates" :key="c.name" class="rb-row">
            <input v-model="c.checked" type="checkbox" />
            <span class="rb-row__name">{{ c.name }}</span>
            <span class="rb-row__desc">{{ c.description }}</span>
            <span v-if="c.mentions > 1" class="rb-row__meta">{{ c.mentions }} 章出现</span>
          </label>
        </div>
      </template>
      <p v-else class="rb-review__lead">没有认出新人物或地点——可以直接记事。</p>
    </div>

    <!-- 完成 / 出错 -->
    <div v-else-if="phase === 'done'" class="rb-done">
      <p>读完了。</p>
      <ul class="rb-done__list">
        <li v-if="createdEntities">新建人物/地点 {{ createdEntities }} 个</li>
        <li>收件箱新增 {{ createdCandidates }} 条世界变化，等你过目</li>
        <li v-if="skippedCount">跳过 {{ skippedCount }} 章（太短或已读过）</li>
      </ul>
    </div>
    <div v-else-if="phase === 'error'" class="rb-done">
      <p>{{ errorMsg || '通读中断' }}</p>
    </div>

    <template #footer>
      <span v-if="creating && createProgress" class="rb-creating">
        正在建设 {{ createProgress.done }}/{{ createProgress.total }}……
      </span>
      <button
        v-if="phase === 'review'"
        class="rb-btn rb-btn--ghost"
        :disabled="creating"
        @click="emit('confirmEntities')"
      >一个都不建，直接记事</button>
      <button
        v-if="phase === 'review'"
        class="rb-btn rb-btn--primary"
        :disabled="creating || (!reviewCount && (entityCandidates.length + locationCandidates.length) > 0)"
        @click="emit('confirmEntities')"
      >建好勾选的（{{ reviewCount }}），开始记事</button>
      <button
        v-if="phase === 'done' || phase === 'error'"
        class="rb-btn rb-btn--primary"
        @click="emit('close')"
      >好</button>
    </template>
  </ModalShell>
</template>

<style scoped>
.rb-progress { padding: 8px 0; }
.rb-progress__label { font-size: 13px; color: var(--text-secondary, #6b6560); margin: 0 0 10px; }
.rb-bar { height: 6px; border-radius: 3px; background: var(--bg-muted, #f1f0ec); overflow: hidden; }
.rb-bar__fill { height: 100%; background: var(--accent-500, #7c6aad); transition: width 0.3s ease; }
.rb-note { font-size: 11px; color: var(--text-muted, #a09a92); margin: 10px 0; }
.rb-review__lead { font-size: 13px; color: var(--text-secondary, #6b6560); margin: 0 0 10px; }
.rb-group { margin-bottom: 12px; }
.rb-group__label { font-size: 11px; color: var(--text-muted, #a09a92); margin-bottom: 4px; }
.rb-row {
  display: flex; align-items: baseline; gap: 8px;
  padding: 5px 6px; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.rb-row:hover { background: var(--bg-muted, #f5f4f0); }
.rb-row__name { font-weight: 600; flex-shrink: 0; }
.rb-row__desc { color: var(--text-muted, #a09a92); font-size: 12px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rb-row__meta { font-size: 11px; color: var(--text-muted, #a09a92); flex-shrink: 0; }
.rb-done__list { margin: 8px 0 0; padding-left: 18px; font-size: 13px; color: var(--text-secondary, #6b6560); }
.rb-btn {
  padding: 6px 14px; border-radius: 8px; font-size: 13px; cursor: pointer;
  border: 1px solid var(--border-color, #d6d3d1); background: transparent; color: inherit;
}
.rb-btn--primary { background: var(--accent-500, #7c6aad); border-color: transparent; color: #fff; }
.rb-btn--primary:disabled { opacity: 0.4; cursor: default; }
.rb-btn--ghost:disabled { opacity: 0.4; cursor: default; }
.rb-creating { font-size: 12px; color: var(--text-muted, #a09a92); margin-right: auto; align-self: center; }
.rb-btn--ghost:hover { background: var(--bg-muted, #f5f4f0); }
</style>
