<script setup lang="ts">
/**
 * 发布结果弹窗（02 §5 收编 ModalShell：Esc 栈/焦点陷阱/遮罩统一托底）。
 */
import ModalShell from '../../../components/ModalShell.vue'

const props = defineProps<{
  show: boolean
  characterUpdates: Array<{
    character_id: string
    character_name: string
    old_state: string
    new_state: string
  }>
  characterExtraction: any
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <ModalShell
    v-if="show"
    title="发布成功"
    width="32rem"
    @close="emit('close')"
  >
    <div v-if="characterUpdates.length > 0" class="pm-section">
      <h4 class="pm-subhead">本次角色状态变更记录</h4>
      <div class="pm-list">
        <div
          v-for="update in characterUpdates"
          :key="update.character_id"
          class="pm-card"
        >
          <div class="pm-card-name">{{ update.character_name }}</div>
          <div class="pm-card-meta">
            <span class="line-through">{{ update.old_state }}</span>
            <span class="mx-1">→</span>
            <span class="pm-new-state">{{ update.new_state }}</span>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="pm-empty">本次发布无角色状态变更记录</div>

    <div v-if="characterExtraction && characterExtraction.extracted_characters && characterExtraction.extracted_characters.length > 0" class="pm-section">
      <h4 class="pm-subhead">从本章认出的角色</h4>
      <div class="pm-list">
        <div
          v-for="character in characterExtraction.extracted_characters"
          :key="character.name"
          class="pm-card"
        >
          <div class="pm-card-head">
            <div class="pm-card-name">{{ character.name }}</div>
            <span v-if="character.is_new" class="pm-chip pm-chip--new">新角色</span>
            <span v-else class="pm-chip pm-chip--known">已有角色</span>
          </div>
          <div class="pm-card-meta">
            <div v-if="character.description" class="mb-1">{{ character.description }}</div>
            <div class="flex items-center gap-2 mt-1">
              <span>角色类型: {{ character.role_type }}</span>
              <span>重要性: {{ character.importance_level }}</span>
            </div>
            <div v-if="character.aliases && character.aliases.length > 0" class="mt-1">
              别名: {{ character.aliases.join(', ') }}
            </div>
          </div>
        </div>
      </div>
      <div class="pm-foot-hint">
        本章共认出 {{ characterExtraction.extracted_characters.length }} 个角色，其中新角色 {{ characterExtraction.new_characters_count }} 个
      </div>
    </div>
    <template #footer>
      <button class="pm-done" @click="emit('close')">完成</button>
    </template>
  </ModalShell>
</template>

<style scoped>
.pm-section { margin-bottom: var(--space-5); }
.pm-subhead {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
}
.pm-list { display: flex; flex-direction: column; gap: var(--space-2); }
.pm-card {
  padding: var(--space-2);
  background: var(--surface-overlay);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
}
.pm-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: 2px;
}
.pm-card-name { font-weight: 500; color: var(--text-primary); }
.pm-card-meta { color: var(--text-muted); margin-top: 2px; }
.pm-new-state { color: var(--ok); }
.pm-empty {
  text-align: center;
  font-size: var(--text-sm);
  color: var(--text-muted);
  padding: var(--space-4) 0;
}
.pm-chip {
  padding: 1px 8px;
  font-size: var(--text-xs);
  border-radius: var(--radius-pill);
  white-space: nowrap;
}
.pm-chip--new { background: color-mix(in srgb, var(--ok) 12%, transparent); color: var(--ok); }
.pm-chip--known { background: var(--info-bg); color: var(--info); }
.pm-foot-hint {
  margin-top: var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.pm-done {
  padding: 6px 16px;
  font-size: var(--text-xs);
  border: none;
  border-radius: var(--radius-md);
  background: var(--accent-500);
  color: var(--bg-canvas);
  cursor: pointer;
  transition: background var(--dur-2) var(--ease-out);
}
.pm-done:hover { background: var(--accent-600); }
</style>
