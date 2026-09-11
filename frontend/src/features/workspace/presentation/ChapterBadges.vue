<script setup lang="ts">
/**
 * 章节状态徽标（V3.1 F2 新建，规格 §4.1；07 期 B-10 降噪）。
 *
 * 细线小徽标，不喧宾夺主。展示在 binder 章节列表每行：
 * - 定档徽标：高/转/推/过（文字 chip，不用 emoji；存量老书数据）
 * - 状态：已发布 / 草稿
 *
 * 07 期退役：「生成中」（旧引擎字段，adaptive 时代不产生）与「已生成」
 * （content_text 存在即亮 = 写过的章全顶着它，零信息量）；死 props
 * climaxScore/auditIssueCount 同删（零消费方）。
 */
import { computed } from 'vue'
import type { Chapter } from '../../../types'

const props = defineProps<{
  chapter: Chapter
}>()

interface TierBadge {
  abbr: string
  label: string
  cls: string
}

const tierBadge = computed<TierBadge | null>(() => {
  const tier = (props.chapter as any).tier || (props.chapter as any).generation_status?.tier
  switch (tier) {
    case 'climax':
      return { abbr: '高', label: '高潮章', cls: 'tier-climax' }
    case 'turn':
      return { abbr: '转', label: '转折章', cls: 'tier-turn' }
    case 'progress':
      return { abbr: '推', label: '推进章', cls: 'tier-progress' }
    case 'transition':
      return { abbr: '过', label: '过渡章', cls: 'tier-transition' }
    default:
      return null
  }
})

const generationStatus = computed<{ label: string; cls: string } | null>(() => {
  const status = props.chapter.status
  if (status === 'published') {
    return { label: '已发布', cls: 'gen-published' }
  }
  if (props.chapter.draft_text && !props.chapter.content_text) {
    return { label: '草稿', cls: 'gen-draft' }
  }
  return null
})
</script>

<template>
  <div class="chapter-badges">
    <!-- 定档徽标 -->
    <span
      v-if="tierBadge"
      class="badge tier"
      :class="tierBadge.cls"
      :title="tierBadge.label"
    >{{ tierBadge.abbr }}</span>

    <!-- 生成状态 -->
    <span
      v-if="generationStatus"
      class="badge status"
      :class="generationStatus.cls"
    >{{ generationStatus.label }}</span>
  </div>
</template>

<style scoped>
.chapter-badges {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
  flex-shrink: 0;
}

.badge {
  font-size: 0.5625rem;
  line-height: 1;
  letter-spacing: 0.01em;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  padding: 0.09375rem 0.25rem;
  border-radius: 0.1875rem;
  font-weight: 500;
}

/* 定档徽标：文字 chip */
.badge.tier {
  font-weight: 600;
}
.badge.tier-climax {
  background: rgba(217, 119, 6, 0.14);
  color: #b45309;
}
.badge.tier-turn {
  background: rgba(124, 106, 173, 0.14);
  color: var(--accent-500);
}
.badge.tier-progress {
  background: var(--bg-tertiary);
  color: var(--text-muted);
}
.badge.tier-transition {
  background: var(--bg-tertiary);
  color: var(--text-muted);
  opacity: 0.7;
}

/* 生成状态 */
.badge.status.gen-published {
  color: #16a34a;
}
.badge.status.gen-draft {
  color: var(--text-muted);
}
</style>
