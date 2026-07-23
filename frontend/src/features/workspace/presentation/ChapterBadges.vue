<script setup lang="ts">
/**
 * 章节状态徽标（V3.1 F2 新建，规格 §4.1）。
 *
 * 细线小徽标，不喧宾夺主。展示在 binder 章节列表每行：
 * - 定档徽标：高/转/推/过（文字 chip，不用 emoji）
 * - 生成状态：草稿/生成中/已生成
 * - 高潮评分：分数（生成后显示）
 * - 待处理审校问题数
 *
 * 设计依据：规格 §4.1 "每章一行状态徽标（细线小图标，不喧宾夺主）"
 * + F4 原则 "chrome 界面零 emoji，AI 存在感统一且克制"
 */
import { computed } from 'vue'
import type { Chapter } from '../../../types'

const props = defineProps<{
  chapter: Chapter
  /** 高潮评分（来自质量报告，F4 接入；F2 阶段可能为 null） */
  climaxScore?: number | null
  /** 待处理审校问题数（F4 接入） */
  auditIssueCount?: number | null
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
  const genStatus = (props.chapter as any).generation_status
  if (genStatus?.generating) {
    return { label: '生成中', cls: 'gen-active' }
  }
  if (status === 'published') {
    return { label: '已发布', cls: 'gen-published' }
  }
  if (props.chapter.draft_text && !props.chapter.content_text) {
    return { label: '草稿', cls: 'gen-draft' }
  }
  if (props.chapter.content_text) {
    return { label: '已生成', cls: 'gen-done' }
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

    <!-- 高潮评分 -->
    <span
      v-if="climaxScore != null"
      class="badge score"
      :title="`高潮评分 ${climaxScore}/10`"
    >{{ climaxScore }}</span>

    <!-- 待处理审校问题 -->
    <span
      v-if="auditIssueCount && auditIssueCount > 0"
      class="badge issues"
      :title="`${auditIssueCount} 个待处理审校问题`"
    >{{ auditIssueCount }}</span>
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
.badge.status.gen-active {
  color: var(--accent-500);
}
.badge.status.gen-published {
  color: #16a34a;
}
.badge.status.gen-draft {
  color: var(--text-muted);
}
.badge.status.gen-done {
  color: var(--text-secondary);
}

/* 高潮评分 */
.badge.score {
  background: rgba(124, 106, 173, 0.12);
  color: var(--accent-500);
  font-weight: 600;
}

/* 审校问题 */
.badge.issues {
  background: rgba(217, 119, 6, 0.14);
  color: #b45309;
  font-weight: 600;
}
</style>
