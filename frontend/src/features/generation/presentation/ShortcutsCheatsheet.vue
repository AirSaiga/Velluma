<script setup lang="ts">
/**
 * 快捷键速查弹层（UX 修复：键位可发现性）。
 * 02 §5 收编 ModalShell（Esc 栈/焦点陷阱统一托底），dark: 手工补丁双轨随之消灭。
 */
import ModalShell from '../../../components/ModalShell.vue'

const emit = defineEmits<{ close: [] }>()

const groups = [
  {
    title: '写作与 AI 辅助',
    items: [
      ['Space', '接着写：有卡舱画面就照着写，没有就顺着写'],
      ['Enter', '采纳幽灵草稿（变成你的正文）'],
      ['Esc', '逐层退出：蒸发幽灵稿 → 收起卡舱 → 取消吸附'],
      ['Tab', '弹出卡舱（接着写的画面）'],
      ['Ctrl + Enter', '沉淀：把这段里的新设定记进世界'],
      ['Ctrl + Space', '打开走向卡（选一条接着写）'],
      ['Alt + N', '世界速记：一句话记下剧情事实'],
      ['1 - 4', '卡舱开启时：快速选择'],
    ],
  },
  {
    title: '修订',
    items: [
      ['Ctrl + Z', '撤销（打字/清脂/整理标点/格式整理均可反悔）'],
      ['Ctrl + Shift + Z', '重做'],
      ['Ctrl + F', '查找 / 替换（改称呼、查重复用词）'],
      ['Alt + ↓', '清脂：刮掉当前段 AI 味用词'],
      ['Alt + Shift + ↓', '深度清脂（AI 重写当前段，去 AI 味更狠）'],
    ],
  },
  {
    title: '界面',
    items: [
      ['Ctrl + \\', '固定 / 收起助手面板'],
      ['Ctrl + 1~4', '打开助手面板：打算 / 此刻 / 本章 / 检查'],
      ['Ctrl + 5', '打开助手面板：AI 视角'],
    ],
  },
]
</script>

<template>
  <ModalShell title="快捷键一览" width="32rem" @close="emit('close')">
    <div class="sc-groups">
      <section v-for="g in groups" :key="g.title">
        <h4 class="sc-group-title">{{ g.title }}</h4>
        <ul class="sc-list">
          <li v-for="item in g.items" :key="item[0]" class="sc-item">
            <kbd class="sc-kbd">{{ item[0] }}</kbd>
            <span class="sc-desc">{{ item[1] }}</span>
          </li>
        </ul>
      </section>
    </div>
  </ModalShell>
</template>

<style scoped>
.sc-groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.sc-group-title {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin-bottom: var(--space-2);
}
.sc-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sc-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  font-size: var(--text-sm);
}
.sc-kbd {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.sc-desc {
  flex: 1;
  text-align: right;
  color: var(--text-secondary);
}
</style>
