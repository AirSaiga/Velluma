<script setup lang="ts">
/**
 * NLE-ADF 2.0 岔路门画布横幅（Branch Banner）。
 *
 * 写到剧情岔路口时，从画布顶部滑入的抉择条——唯一允许打断心流的组件
 * （岔路是走向级决策，作者必须表态）。选项 = DDE 决策集节点：
 *   数字/点击选走向；自定义走向走 custom: 通道；loop1_gap 缺口节点只收补充文本。
 * Space = 默认走向（session 全局键位已覆盖 beat_branch_choosing 态）。
 * 与右栏 BranchDecisionPanel 同数据源（session.branchChoicePending），画布内形态。
 */
import { computed, ref, watch } from 'vue'
import type { GenerationSession } from '../composables/useGenerationSession'

const props = defineProps<{ session: GenerationSession }>()

const pending = computed(() => props.session.branchChoicePending.value)
const customText = ref('')

// 每次新岔路清空自定义输入
watch(pending, (val) => {
  if (val) customText.value = ''
})

const isGapNode = computed(() => pending.value?.node?.source === 'loop1_gap')

function choose(optionId: string | null) {
  props.session.submitBranchChoice(optionId)
}

function submitCustom() {
  const text = customText.value.trim()
  if (!text) return
  props.session.submitBranchChoice(`custom:${text}`)
}
</script>

<template>
  <Transition name="branch-banner">
    <div v-if="pending" class="branch-banner">
      <div class="branch-banner__title">
        <span class="branch-banner__icon">⑂</span>
        <span>{{ pending.node.node_title }}</span>
        <span class="branch-banner__seg">第 {{ pending.segment_index + 1 }} 拍</span>
      </div>
      <!-- 来源区分副标题：dde=代笔必须先定走向；loop1_gap=可跳过的补充提示 -->
      <div class="branch-banner__subtitle">
        {{ isGapNode ? '补充信息可让代笔更准（可跳过）' : 'AI 代笔需要先定走向' }}
      </div>

      <!-- DDE 岔路节点：选项 + 自定义走向 -->
      <div v-if="!isGapNode" class="branch-banner__options">
        <button
          v-for="(opt, i) in pending.node.options"
          :key="opt.option_id"
          class="branch-banner__option"
          :class="{ 'branch-banner__option--default': opt.option_id === pending.node.default_option }"
          @click="choose(opt.option_id)"
        >
          <span class="branch-banner__num">{{ i + 1 }}</span>
          <span class="branch-banner__label">{{ opt.label }}</span>
          <span v-if="opt.plot_impact" class="branch-banner__impact">{{ opt.plot_impact }}</span>
        </button>
      </div>

      <!-- loop1_gap 缺口节点 / 自定义走向 -->
      <div class="branch-banner__custom">
        <input
          v-model="customText"
          class="branch-banner__input"
          :placeholder="isGapNode ? '补充这一拍的走向信息…' : '或自己写走向…'"
          @keydown.enter="submitCustom"
        />
        <button
          class="branch-banner__submit"
          :disabled="!customText.trim()"
          @click="submitCustom"
        >确定</button>
        <!-- 缺口节点必须有跳过出口（不填不能被卡死）；dde 节点给默认走向 -->
        <button
          v-if="isGapNode"
          class="branch-banner__default"
          title="不补充，按原大纲代笔"
          @click="choose(null)"
        >跳过</button>
        <button
          v-else
          class="branch-banner__default"
          title="接受默认走向（Space）"
          @click="choose(pending.node.default_option || 'A')"
        >默认</button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.branch-banner {
  margin: 0 auto 8px;
  max-width: 720px;
  border-radius: 10px;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid rgba(217, 119, 6, 0.3);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
  padding: 12px 16px;
  z-index: 60;
}

.branch-banner__title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #b45309;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}

.branch-banner__seg {
  margin-left: auto;
  color: var(--text-muted, #a89e90);
  font-size: 11px;
  font-weight: 400;
}

.branch-banner__subtitle {
  color: var(--text-muted, #a89e90);
  font-size: 11px;
  margin: -4px 0 10px;
}

.branch-banner__options {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.branch-banner__option {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--border-color, #e0dbd3);
  background: transparent;
  color: var(--text-primary, #2c2c2c);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}

.branch-banner__option:hover {
  border-color: rgba(217, 119, 6, 0.45);
  background: rgba(217, 119, 6, 0.05);
}

.branch-banner__option--default {
  border-color: rgba(217, 119, 6, 0.35);
}

.branch-banner__num {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  background: rgba(217, 119, 6, 0.12);
  color: #b45309;
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  align-self: center;
}

.branch-banner__impact {
  color: var(--text-muted, #a89e90);
  font-size: 11px;
}

.branch-banner__custom {
  display: flex;
  gap: 6px;
}

.branch-banner__input {
  flex: 1;
  background: var(--bg-secondary, #faf8f4);
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 6px;
  color: var(--text-primary, #2c2c2c);
  font-size: 13px;
  padding: 6px 10px;
  outline: none;
}

.branch-banner__input:focus {
  border-color: rgba(217, 119, 6, 0.5);
}

.branch-banner__submit,
.branch-banner__default {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid rgba(217, 119, 6, 0.35);
  background: rgba(217, 119, 6, 0.08);
  color: #b45309;
  font-size: 12px;
  cursor: pointer;
}

.branch-banner__submit:disabled {
  opacity: 0.4;
  cursor: default;
}

.branch-banner__default {
  border-color: rgba(42, 45, 53, 0.9);
  background: transparent;
  color: var(--text-muted, #a89e90);
}

/* 顶部滑入 */
.branch-banner-enter-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.branch-banner-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.branch-banner-enter-from,
.branch-banner-leave-to {
  opacity: 0;
  transform: translateY(-12px);
}
</style>
