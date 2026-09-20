<script setup lang="ts">
/**
 * 快捷键速查弹层（引导体系重构 2026-09-20 场景化重写）。
 *
 * 组织方式从「键位字典」改为「什么时候按什么」：按使用时机分四组，
 * 每条 = 键 + 动作 + 条件小字（触发门槛/行为差异写在第二行），
 * 修正旧版全部漂移（补 Alt+O/`[[`/↑↓、区分卡片舱与走向卡、写明 Space 门槛）。
 * 入口：右缘栏 ? 按钮 + 全局 ? 键（WorkspaceView，正文/输入框内不触发）。
 * 02 §5 收编 ModalShell（Esc 栈/焦点陷阱统一托底）。
 */
import ModalShell from '../../../components/ModalShell.vue'

const emit = defineEmits<{ close: [] }>()

interface CheatItem {
  keys: string[]
  action: string
  note?: string
}
interface CheatGroup {
  title: string
  note?: string
  items: CheatItem[]
}

const groups: CheatGroup[] = [
  {
    title: '写的时候',
    items: [
      { keys: ['Space'], action: '接着写', note: '本章写满 4 个字后生效；光标段有字就顺着写，吸附了镜头则照镜头写' },
      { keys: ['Tab'], action: '找镜头（卡片舱）', note: '数字键 1-4 直写单镜头 · ↑↓ 浏览 · Esc 关' },
      { keys: ['Ctrl + Space'], action: '选走向（走向卡）', note: '段落往哪写，数字键选向即写' },
      { keys: ['Alt + O', '[['], action: '细纲胶囊', note: '一句话记打算，Enter 落笔扩写' },
      { keys: ['Alt + N'], action: '记一笔', note: '一句话记剧情事实，过目后记入世界' },
      { keys: ['??'], action: '问书', note: '查一个书里的事实，答案浮在行间，不进正文' },
    ],
  },
  {
    title: '屏幕上有幽灵草稿时',
    note: '灰绿色那段 AI 字',
    items: [
      { keys: ['Tab'], action: '采纳为正文' },
      { keys: ['Enter'], action: '暂留：停在原地', note: '回来 Tab 转正 / Esc 丢弃' },
      { keys: ['Esc'], action: '蒸发不要', note: '60 秒内再按 Space 原样找回 · 逐层退出：幽灵 → 走向卡 → 卡片舱 → 清空吸附' },
    ],
  },
  {
    title: '改稿的时候',
    items: [
      { keys: ['Alt + ↓', 'Alt + Shift + ↓'], action: '清脂 / 深度清脂', note: '刮掉本段 AI 味用词 / AI 重写本段，更狠' },
      { keys: ['Ctrl + F'], action: '查找 / 替换' },
      { keys: ['Ctrl + Z', 'Ctrl + Shift + Z'], action: '撤销 / 重做', note: '打字、清脂、整理标点都可反悔' },
    ],
  },
  {
    title: '记进世界 / 界面',
    items: [
      { keys: ['Ctrl + Enter'], action: '沉淀：把这段的新设定记进世界', note: 'AI 辅助开着、本章写满 4 个字后可用' },
      { keys: ['Ctrl + \\'], action: '固定 / 收起助手面板' },
      { keys: ['Ctrl + 1~4'], action: '助手面板：打算 / 此刻 / 检查 / AI 视角' },
      { keys: ['?'], action: '打开本表' },
    ],
  },
]
</script>

<template>
  <ModalShell title="快捷键一览" width="34rem" @close="emit('close')">
    <div class="sc-groups">
      <section v-for="g in groups" :key="g.title">
        <h4 class="sc-group-title">
          {{ g.title }}<span v-if="g.note" class="sc-group-note">（{{ g.note }}）</span>
        </h4>
        <ul class="sc-list">
          <li v-for="item in g.items" :key="item.action" class="sc-item">
            <div class="sc-keys">
              <kbd v-for="k in item.keys" :key="k" class="sc-kbd">{{ k }}</kbd>
            </div>
            <div class="sc-text">
              <span class="sc-action">{{ item.action }}</span>
              <span v-if="item.note" class="sc-note">{{ item.note }}</span>
            </div>
          </li>
        </ul>
      </section>
    </div>
    <p class="sc-foot">按 ? 随时打开这张表（正文里打问号不受影响）</p>
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
.sc-group-note {
  font-weight: 400;
  letter-spacing: normal;
}
.sc-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sc-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  font-size: var(--text-sm);
}
/* 键位列：多个键（如 Alt+O / [[）纵排右对齐，与文字列对齐成栏 */
.sc-keys {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
  min-width: 6.5em;
}
.sc-kbd {
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-tertiary);
  border: 1px solid var(--line-faint);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--text-primary);
  white-space: nowrap;
}
.sc-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sc-action {
  color: var(--text-primary);
}
.sc-note {
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-muted);
}
.sc-foot {
  margin-top: var(--space-5);
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-align: center;
}
</style>
