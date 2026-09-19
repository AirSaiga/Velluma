<script setup lang="ts">
/**
 * 文风页「负面词清洗库」（模块 B，2026-09 靶场批）——硬禁词清单的极简面。
 *
 * 去极客化：只呈现「词 ➔ 处理方式」+ 回车即加。档位切换保留但缩为
 * 小开关（硬禁=代码确定性拦截/提醒=仅提示），完整三层可见性
 * （系统陈词库/豁免/扫描审稿）迁往「研究数据」折叠舱，不在此打扰。
 *
 * 2026-09-17 视觉归一：标题降 .style-eyebrow 组眉标（栏头「写作底线」之
 * 下的次级分组），样式全量迁移 token 方言（docs/design/style-page-redesign.md §4.5）。
 */
import { ref } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { NegativeItem } from '../../../types'

const props = defineProps<{
  items: NegativeItem[]
}>()

const emit = defineEmits<{
  (e: 'add', word: string): void
  (e: 'remove', index: number): void
  (e: 'toggle', item: NegativeItem): void
}>()

const draft = ref('')

function submit() {
  const word = draft.value.trim()
  if (!word) return
  emit('add', word)
  draft.value = ''
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    submit()
  }
}

/** 生效条目（有词的）在前，未填词的新行沉底 */
function activeItems(): Array<{ item: NegativeItem; index: number }> {
  const out: Array<{ item: NegativeItem; index: number }> = []
  props.items.forEach((item, index) => {
    if (item.word.trim()) out.push({ item, index })
  })
  return out
}
</script>

<template>
  <section id="style-sec-bans" class="style-section">
    <h3 class="style-eyebrow ban-eyebrow">已拦截的禁词</h3>

    <div class="ban-list">
      <div
        v-for="{ item, index } in activeItems()"
        :key="index"
        class="ban-row"
        :class="{ 'sev-hard': item.severity === 'blocker' }"
      >
        <span class="ban-word">{{ item.word }}</span>
        <Icon class="ban-arrow" name="arrow-right" :size="14" />
        <span class="ban-alt" :class="{ 'ban-alt-none': !item.alternative?.trim() }">
          {{ item.alternative?.trim() || '[直接删除]' }}
        </span>
        <button
          class="sev-toggle"
          :class="{ 'sev-blocker': item.severity === 'blocker' }"
          title="硬禁：AI 写到就自动拦下改掉 / 提醒：只提醒，不自动改"
          @click="emit('toggle', item)"
        >{{ item.severity === 'blocker' ? '硬禁' : '提醒' }}</button>
        <button class="icon-danger" title="移出清洗库" @click="emit('remove', index)">
          <Icon name="x-mark" :size="12" />
        </button>
      </div>
      <div v-if="activeItems().length === 0" class="empty-note">
        还没有拦下的词——在中间「试写对比」里划选不顺眼的词，点一下就能加进来。
      </div>
    </div>

    <!-- 实体输入组（降噪批）：实体边框输入 + 拦截按钮成组 -->
    <div class="ban-add">
      <input
        v-model="draft"
        class="ban-input"
        placeholder="输入想屏蔽的词…"
        @keydown="onKeydown"
      >
      <button class="ban-add-btn" :disabled="!draft.trim()" @click="submit">加入拦截</button>
    </div>
  </section>
</template>

<style scoped>
.style-section {
  margin-top: var(--space-6);
}
.ban-eyebrow {
  margin: 0 0 var(--space-1);
}
.ban-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.ban-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: var(--control-h-sm);
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-sm);
  border-radius: var(--radius-sm);
}
.ban-row:hover {
  background: var(--state-hover);
}
/* 朱批 tick（身份层③）：硬禁行左缘 2px 朱砂内影=红批改订记；提醒档无 tick */
.ban-row.sev-hard {
  box-shadow: inset 2px 0 0 var(--cinnabar-bright);
}
.ban-word {
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-all;
}
.ban-arrow {
  flex-shrink: 0;
  color: var(--text-faint);
}
.ban-alt {
  flex: 1;
  overflow: hidden;
  color: var(--text-secondary);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ban-alt-none {
  color: var(--text-muted);
}
.sev-toggle {
  flex-shrink: 0;
  min-height: var(--control-h-sm);
  padding: 0 var(--space-3);
  font-size: var(--text-xs);
  color: var(--warn);
  background: var(--warn-bg);
  border: none;
  border-radius: var(--radius-pill);
  cursor: pointer;
  white-space: nowrap;
}
.sev-toggle:hover {
  color: var(--text-secondary);
}
.sev-toggle.sev-blocker {
  font-weight: 600;
  color: var(--danger);
  background: var(--danger-bg);
}
.icon-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
  cursor: pointer;
}
.icon-danger:hover {
  color: var(--danger);
  background: var(--danger-bg);
}
.empty-note {
  padding: var(--space-2);
  font-size: var(--text-xs);
  line-height: var(--lh-compact);
  color: var(--text-muted);
}
.ban-add {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.ban-input {
  flex: 1;
  min-width: 0;
  min-height: var(--control-h-sm);
  padding: 0 var(--control-px);
  font-size: var(--text-sm);
  color: var(--text-primary);
  background: var(--field-bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
.ban-input:focus-visible {
  border-color: var(--accent-400);
}
.ban-add-btn {
  flex-shrink: 0;
  min-height: var(--control-h-sm);
  padding: 0 var(--space-3);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  background: var(--surface-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
  white-space: nowrap;
}
.ban-add-btn:hover:not(:disabled) {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.ban-add-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
