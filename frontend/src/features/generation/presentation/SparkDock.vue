<script setup lang="ts">
/**
 * NLE-ADF 灵感悬浮舱（Spark Dock）——灵感提示 + 补写入口。
 *
 * Tab 唤起时在光标段下方行间推挤展开（2026-09-09 布局重构：WidgetDecoration
 * 流内区块，宿主 InlineDockHost/InlineDock.ts；旧 fixed 浮层遮挡 FIM 后文的
 * 问题随之消亡），浮现 3~4 个【镜头特写挂件】（"老烟的血手"/"咬平齿的管钳"）。
 * 作者吸附挂件 → Space 微缝合（AI 基于挂件指引流式续写，幽灵草稿形态）→ Enter 锁死。
 *
 * 挂件来自后端 dock_generator 对 recent_text + projections + 设定(nutrients/
 * hard_constraints) 的 LLM 生发，不是角色名罗列，也不是抽象建议。
 *
 * 功能槽位两级层级（2026-08-29「不知所云」重构）：每张卡必须自解释
 * 「选这枚会发生什么」——主行=画面碎片，副行=后果短语（▸ 接着刚才那句往下写 /
 * ⚑ 往「节拍」那拍走的第一步 / ◆ 顺笔带出前情/暗示读者在等 / ○ 纯画面·不牵动剧情）。
 * 旧五向 direction 标签退役不上屏（分析面元数据）；「接着写」恒居首位。
 *
 * Sticky：缝合触发后舱不消失（连续吸附多件缝合）；Esc 关舱退出 sticky。
 *
 * 第 5 槽位·自定义镜头输入（第二冲程 2026-09-09）：作者一句话自定义镜头 →
 * 回车复用同一条 stitch 微缝合流水线（50 字级单镜头展开）。焦点纪律：
 * 零自动焦点（弹舱/回弹永不抢正文光标）——进入只两条路：↓ 浏览到底、点击；
 * 输入框聚焦期间全局作者键位让位（useGenerationSession 顶部守卫）。
 */
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import type { SparkPart } from '../composables/useSparkDock'
import {
  sparkDockVisible,
  sparkParts,
  sparkGuests,
  attachedParts,
  attachSparkPart,
  sparkSelectedIndex,
} from '../composables/useSparkDock'
import { ghostActive } from '../composables/useGhostDraft'
import { dockRefreshError } from '../composables/useAdaptiveAssist'
import { useProgressiveHint } from '../../../composables/useProgressiveHint'

/** 旧卡年龄人话（秒 → 「N 分钟前」；与报错行同帧捕获，不做活钟） */
const dockAgeText = computed(() => {
  const s = dockRefreshError.value?.partsAgeS
  if (s == null || !Number.isFinite(s)) return ''
  if (s < 60) return `${s} 秒前`
  if (s < 5400) return `${Math.round(s / 60)} 分钟前`
  return `${Math.round(s / 3600)} 小时前`
})

const emit = defineEmits<{
  /** 自定义镜头提交（第 5 槽位回车）→ 复用 stitch 微缝合流水线 */
  customStitch: [text: string]
  /** 临时在场角色「录入档案」（2026-09-09 涌现角色闭环）→ 容器接建档往返 */
  guestRegister: [name: string]
}>()

const visible = computed(() => sparkDockVisible.value || attachedParts.value.length > 0)

// ---- 首次开启引导行（渐进，前 3 次开舱显示；确实显示过的那回在关舱沿计数）----
// 2026-09-09 删除的舱顶自解释行以限次形态回归：常驻版嫌冗杂，零提示又不知
// 怎么用——折中是「头几次教你，学会了就闭嘴」（useProgressiveHint）。
const { visible: introVisible, markSeen: markIntroSeen } = useProgressiveHint('spark_dock_intro')
const dockShown = computed(() => visible.value && !ghostActive.value && sparkDockVisible.value)
let _introShownThisOpen = false
watch(dockShown, (now, was) => {
  if (now && introVisible.value) _introShownThisOpen = true
  if (was && !now && _introShownThisOpen) {
    _introShownThisOpen = false
    markIntroSeen()
  }
})

/** 槽位 → 功能符号（landing=▸ 承接 / toward_beat=⚑ 锚点语言 / echo=◆ / ambient=○） */
const SOURCE_SYMBOL: Record<NonNullable<SparkPart['source']>, string> = {
  landing: '▸',
  toward_beat: '⚑',
  echo: '◆',
  ambient: '○',
}

/** 无 note 槽位的固定副行（ambient 留白设计已废除——2026-08-29 二轮实测：
 * 没人知道「留白是信息」，看到的只是「这张卡连解释都没有」） */
const SOURCE_FALLBACK_NOTE: Partial<Record<NonNullable<SparkPart['source']>, string>> = {
  landing: '接着刚才那句往下写',
  ambient: '纯画面 · 不牵动剧情',
}

function noteOf(part: SparkPart): string {
  return part.note || SOURCE_FALLBACK_NOTE[part.source ?? 'ambient'] || ''
}

function symbolOf(part: SparkPart): string {
  return part.source ? SOURCE_SYMBOL[part.source] : '○'
}

function onPick(index: number) {
  attachSparkPart(index)
}

// ---- 第 5 槽位：自定义镜头输入（零自动焦点纪律）----
const customInput = ref<HTMLInputElement | null>(null)
const customText = ref('')

/** ↓ 到底/点击切入焦点（velluma:dock-focus-custom 由 useGenerationSession 派发） */
function _onFocusRequest() {
  if (sparkDockVisible.value && !ghostActive.value) customInput.value?.focus()
}

onMounted(() => window.addEventListener('velluma:dock-focus-custom', _onFocusRequest))
onBeforeUnmount(() => window.removeEventListener('velluma:dock-focus-custom', _onFocusRequest))

/** Enter 提交：IME 组合态的 Enter（选词/确认候选）不提交；空文本忽略；
 * 提交即退焦（输入框使命完成，光标交还正文） */
function onCustomEnter(e: KeyboardEvent) {
  if (e.isComposing) return
  const t = customText.value.trim()
  if (!t) return
  customText.value = ''
  customInput.value?.blur()
  emit('customStitch', t)
}

/** Esc 只退焦不关舱（stopPropagation 防全局 Esc 栈连坐）——第二次 Esc
 * （焦点已在正文）才走全局关舱 */
function onCustomEsc() {
  customInput.value?.blur()
}
</script>

<template>
    <Transition name="spark-dock">
      <div
        v-if="visible && !ghostActive"
        class="spark-dock elev-2"
        @mousedown.prevent
      >
        <!-- Tab 重算失败可见化（2026-09-15 槽位治理）：点名强制重算失败时旧缓存
             照发——这行把真相摆到脸上，旧卡维持可用但不再伪装新鲜 -->
        <div v-if="dockRefreshError" class="spark-dock__err">
          <span class="spark-dock__err-sym">⚠</span>
          刷新失败：{{ dockRefreshError.brief }}<template v-if="sparkParts.length && dockAgeText">——下面是 {{ dockAgeText }}的旧卡</template><template v-else>——暂无卡片</template>
        </div>
        <!-- 挂件栏（镜头特写 chips，数字键 1~4 吸附）。2026-09-09 行间推挤化：
             顶栏自解释行与「多写几段」按钮删除（推挤幅度收敛；Tab 唤起本身
             已是自解释入口，Ctrl+Space 仍直达走向卡舱） -->
        <div v-if="sparkDockVisible" class="spark-dock__row">
          <button
            v-for="(part, i) in sparkParts"
            :key="part.key"
            class="spark-dock__chip"
            :class="{
              'spark-dock__chip--attached': attachedParts.some(p => p.key === part.key),
              'spark-dock__chip--selected': i === sparkSelectedIndex,
            }"
            :title="part.note ? `${part.text}\n${part.note}` : part.text"
            @click="onPick(i)"
          >
            <span class="spark-dock__num">{{ i + 1 }}</span>
            <span class="spark-dock__body">
              <span class="spark-dock__text">{{ part.text }}</span>
              <span v-if="noteOf(part)" class="spark-dock__note">
                <span class="spark-dock__note-sym">{{ symbolOf(part) }}</span>
                {{ noteOf(part) }}
              </span>
            </span>
          </button>
        </div>
        <!-- 意图吸附栏（已选挂件 + 操作提示） -->
        <div v-if="attachedParts.length" class="spark-dock__intent">
          <span class="spark-dock__intent-pin">📌</span>
          <span
            v-for="part in attachedParts"
            :key="part.key"
            class="spark-dock__picked"
          >
            <span v-if="symbolOf(part)" class="spark-dock__note-sym">{{ symbolOf(part) }}</span>
            {{ part.text }}
          </span>
          <span class="spark-dock__hint">点选可多枚同缝 · 数字键直接开单镜头</span>
        </div>
        <!-- 第 5 槽位：自定义镜头输入 + 临时通行证芯片（同一横排，芯片不占垂直行）。
             输入 @mousedown.stop：根节点的 @mousedown.prevent（防点舱偷编辑器焦点）
             会连坐拦掉输入框的原生点击聚焦——在此截断冒泡，让 mousedown 默认行为
             （聚焦 input）照常发生 -->
        <div v-if="sparkDockVisible" class="spark-dock__foot">
          <input
            ref="customInput"
            v-model="customText"
            class="spark-dock__custom-input"
            placeholder="✏️ 自定义镜头，回车扩写…"
            @mousedown.stop
            @keydown.enter="onCustomEnter"
            @keydown.esc.stop.prevent="onCustomEsc"
          />
          <button
            v-for="g in sparkGuests"
            :key="g"
            class="spark-dock__guest"
            :title="`${g} 还没建档——点一下去世界页录入，建完自动回到原光标`"
            @mousedown.stop
            @click="emit('guestRegister', g)"
          >👤 {{ g }} ➔ 建档</button>
        </div>
        <!-- 首次开启引导行（渐进：前 3 次显示，看过淡出） -->
        <div v-if="dockShown && introVisible" class="spark-dock__hint">
          数字键直写单镜头 · ↑↓ 浏览 · 点选可吸附多枚 · Esc 关
        </div>
      </div>
    </Transition>
  </template>

<style scoped>
/* 磨砂玻璃浮窗（Cyber-Parchment Dark 双主题自适应） */
.spark-dock {
  /* 光标层内区块（07 期 §2.5：宿主 CursorLayer 管 fixed 定位与宽度） */
  width: 100%;
  box-sizing: border-box;
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  padding: 6px;
  user-select: none;
}

/* 深色档：背景随 --bg-elevated token，毛玻璃保留（阴影 lg 盖过 elev-2 的 md，维持现状） */
:root.dark .spark-dock {
  background: color-mix(in srgb, var(--bg-elevated) 92%, transparent);
  backdrop-filter: blur(8px);
  box-shadow: var(--elev-3-shadow);
}

.spark-dock__row {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
}

.spark-dock__chip {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  max-width: 100%;
  padding: 5px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--text-primary);
  /* button 的 UA 样式表默认 text-align:center——chip 自身是 flex 不受影响，
     但内部 body 无显式值会继承 center，主行（普通 span）满宽后文字整行居中
     （副行 note 是 flex 容器幸免）。旧浮层窄看不出，行间贴满正文列宽后暴露。
     与 .beat-dock__card 同款防御 */
  text-align: left;
  /* 行间推挤化（2026-09-09）后舱住正文列内，与 16px 正文同屏读——
     主行 12.5→14px（≈正文 87%），副行 10→12px（75%） */
  font-size: var(--text-base);
  line-height: 1.5;
  cursor: pointer;
  transition: background var(--dur-1) var(--ease-out), border-color var(--dur-1) var(--ease-out);
}

.spark-dock__chip:hover {
  background: color-mix(in srgb, var(--mint) 10%, transparent);
}

.spark-dock__chip--attached {
  border-color: color-mix(in srgb, var(--mint) 40%, transparent);
  background: color-mix(in srgb, var(--mint) 8%, transparent);
}
/* ↑↓ 浏览选中（纯视觉，不影响吸附） */
.spark-dock__chip--selected {
  border-color: var(--accent-500);
  background: color-mix(in srgb, var(--accent-500) 10%, transparent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent-500) 15%, transparent);
}

.spark-dock__num {
  flex-shrink: 0;
  width: 17px;
  height: 17px;
  margin-top: 2px;
  border-radius: var(--radius-sm);
  background: var(--state-hover);
  color: var(--text-muted);
  font-size: 11.5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

/* 卡片主体：主行=画面碎片，副行=功能出处（2026-08-29 两级层级） */
.spark-dock__body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}

.spark-dock__text {
  /* 碎片文字允许换行，完整显示 8-16 字内容（不截断） */
  word-break: break-word;
  white-space: normal;
}

/* 功能出处副行：12px 弱化灰——主行是唯一主角，副行只回答「选这枚会发生什么」 */
.spark-dock__note {
  display: flex;
  align-items: baseline;
  gap: 3px;
  font-size: var(--text-xs);
  line-height: 1.4;
  color: var(--text-muted);
  word-break: break-word;
  white-space: normal;
}

.spark-dock__note-sym {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--accent-500);
}

/* Tab 重算失败行（2026-09-15 槽位治理）：朱色警示但不抢交互——一行事实，
   告诉作者旧卡是旧的、为什么没换新 */
.spark-dock__err {
  display: flex;
  align-items: baseline;
  gap: 5px;
  font-size: var(--text-xs);
  line-height: 1.4;
  color: var(--cinnabar);
  word-break: break-word;
  white-space: normal;
  padding-bottom: 4px;
}

.spark-dock__err-sym {
  flex-shrink: 0;
  font-size: var(--text-xs);
}

/* 舱顶自解释行（07 期 §2.5.2：替代旧 tips 行）——2026-09-09 行间推挤化删除 */
.spark-dock__intent {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 4px;
  margin-top: 4px;
  border-top: 1px dashed var(--border-color);
}

.spark-dock__intent:first-child {
  border-top: none;
  margin-top: 0;
  padding-top: 0;
}

.spark-dock__intent-pin {
  font-size: var(--text-xs);
}

.spark-dock__picked {
  padding: 1px 8px;
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--mint) 12%, transparent);
  color: var(--mint-ink);
  font-size: var(--text-sm);
  white-space: nowrap;
}

.spark-dock__hint {
  margin-left: auto;
  color: var(--text-muted);
  font-size: var(--text-xs);
}

/* 临时通行证芯片（输入行右端）：不换行不占垂直行，多了横向滚动兜底 */
.spark-dock__guest {
  flex-shrink: 0;
  text-align: left;
  padding: 2px 8px;
  border: 1px dashed color-mix(in srgb, var(--mint) 50%, transparent);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--mint) 6%, transparent);
  color: var(--mint-ink);
  font-size: 12.5px;
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--dur-1) var(--ease-out);
}

.spark-dock__guest:hover { background: color-mix(in srgb, var(--mint) 16%, transparent); }

/* 第 5 槽位脚行：自定义镜头输入 + 临时通行证芯片同排横置（2026-09-09
   行间推挤化——芯片不再垂直占行，推挤幅度收敛） */
.spark-dock__foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px dashed var(--border-color);
}

.spark-dock__custom-input {
  flex: 1;
  min-width: 0;
  box-sizing: border-box;
  padding: 5px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-base);
  line-height: 1.5;
  outline: none;
  /* 根节点 user-select:none 的豁免——输入框内文本必须可选中可编辑 */
  user-select: text;
  transition: border-color var(--dur-1) var(--ease-out);
}

.spark-dock__custom-input:focus {
  border-color: var(--accent-500);
}

.spark-dock__custom-input::placeholder {
  color: var(--text-muted);
}

/* 淡入下滑（150ms） */
.spark-dock-enter-active {
  transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out);
}
.spark-dock-leave-active {
  transition: opacity var(--dur-1) var(--ease-out), transform var(--dur-1) var(--ease-out);
}
.spark-dock-enter-from,
.spark-dock-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
