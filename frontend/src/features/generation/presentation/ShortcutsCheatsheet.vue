<script setup lang="ts">
/**
 * 快捷键速查弹层（UX 修复：键位可发现性）。
 *
 * 此前 Alt+↓ 清脂、Ctrl+Backspace 回退等键位在全工程任何 UI 文本中都不出现，
 * 用户无从知晓。顶栏「?」按钮触发本弹层。
 */
import { onMounted, onBeforeUnmount } from 'vue'

const emit = defineEmits<{ close: [] }>()

const groups = [
  {
    title: '写作与 AI 辅助',
    items: [
      ['Space', '接着写：有灵感零件就拼上写，没有就顺着写'],
      ['Enter', '采纳幽灵草稿为正文'],
      ['Esc', '逐层退出：蒸发幽灵稿 → 收起卡舱 → 取消吸附'],
      ['Tab', '唤起灵感卡片舱'],
      ['Ctrl + Enter', '沉淀当前段（把新设定记下来）'],
      ['Ctrl + Space', '打开走向卡（选一条接着写）'],
      ['Alt + N', '世界速记：一句话记事件，过目入账'],
      ['1 - 4', '卡舱开启时：捡起挂件 / 选走向卡'],
    ],
  },
  {
    title: '修订',
    items: [
      ['Ctrl + Z', '撤销（打字/清脂/格式整理均可反悔）'],
      ['Ctrl + Shift + Z', '重做'],
      ['Alt + ↓', '清脂：刮掉当前段 AI 味用词'],
      ['Alt + Shift + ↓', '深度清脂（AI 重写当前段，去 AI 味更狠）'],
      ['Ctrl + Backspace', '回退上一步'],
    ],
  },
  {
    title: '界面',
    items: [
      ['Ctrl + \\', '固定 / 收起副驾面板'],
      ['Ctrl + 1~4', '切换副驾 tab：打算 / 此刻 / 本章 / 检查'],
      ['Ctrl + 5', 'AI 视角（副驾底部入口：AI 实际读到的内容）'],
    ],
  },
]

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
  }
}
onMounted(() => document.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div class="fixed inset-0 z-[110] flex items-center justify-center" @click.self="emit('close')">
        <div class="fixed inset-0 bg-black/40 backdrop-blur-sm"></div>
        <div
          class="modal-content relative bg-parchment-50 dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-lg mx-4 overflow-hidden"
          role="dialog"
          aria-modal="true"
          aria-label="快捷键一览"
        >
          <div class="flex items-center justify-between px-6 py-4 border-b border-ink-100 dark:border-gray-700">
            <h3 class="text-base font-heading font-semibold text-gray-900 dark:text-gray-100">快捷键一览</h3>
            <button
              class="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-sm px-2 py-1"
              @click="emit('close')"
            >Esc 关闭</button>
          </div>
          <div class="px-6 py-4 max-h-[70vh] overflow-y-auto space-y-5">
            <section v-for="g in groups" :key="g.title">
              <h4 class="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-2">{{ g.title }}</h4>
              <ul class="space-y-1.5">
                <li v-for="item in g.items" :key="item[0]" class="flex items-center justify-between gap-4 text-sm">
                  <kbd class="shrink-0 px-2 py-0.5 rounded-md bg-ink-50 dark:bg-gray-700 border border-ink-200 dark:border-gray-600 text-xs font-mono text-gray-800 dark:text-gray-200">{{ item[0] }}</kbd>
                  <span class="flex-1 text-right text-gray-600 dark:text-gray-300">{{ item[1] }}</span>
                </li>
              </ul>
            </section>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
