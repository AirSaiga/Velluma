<script setup lang="ts">
/**
 * 外观面板（2026-09-15 设置拆分：外观从旧设置弹窗独立，左缘无遮罩抽屉）。
 *
 * 为什么是抽屉不是弹窗：外观全部即时生效（useAppearance 设备本地），无遮罩
 * 意味着换主题/换背景的瞬间**整个应用就在身后变色**——弹窗的遮罩+模糊会挡住
 * 这份即时反馈。无焦点陷阱：开着也能继续读稿/打字，Esc 收起（EscStack 分层）。
 *
 * 内容沿旧设置弹窗「外观」区（主题系统 docs/design/theme-system/01-theme-architecture.md
 * §6 + 编辑器排版 03 期 §7），控件重排为窄抽屉形态：主题五张行式卡 +
 * 明暗/背景/排版分段控件。零「保存」钮——所见即已生效。
 */
import { computed, onScopeDispose, ref, watch } from 'vue'
import Icon from './Icon.vue'
import SegmentedPill from './SegmentedPill.vue'
import { THEME_ORDER, THEME_PREVIEW_PRESETS, PREVIEW_GRAIN_URI } from './appearancePreviewPresets'
import { useAppSettings } from '../composables/useAppSettings'
import { useAppearance, type AppearanceMode, type BgSpec, type ThemeId } from '../composables/useAppearance'
import { useEscStack } from '../composables/useEscStack'
import { useToast } from '../composables/useToast'

const { appearanceVisible, closeAppearance } = useAppSettings()
const { appearance, setTheme, setMode, setBg, setMotionLow } = useAppearance()
const { showToast } = useToast()

// ============================================================
// 主题行式卡（05 §9.1 v2：16:10 上下半切浅/深微型场景预览；
// 色值唯一权威=appearancePreviewPresets.ts，与 style.css 十块同源维护）
// ============================================================

interface ThemeCard {
  id: ThemeId
  name: string
  word: string
}

const themeCards: ReadonlyArray<ThemeCard> = THEME_ORDER.map((id, i) => ({
  id: id as ThemeId,
  name: THEME_PREVIEW_PRESETS[i].name,
  word: THEME_PREVIEW_PRESETS[i].word,
}))

/** 主题卡缩略图 CSS 变量组（上半浅档/下半深档各带 accent/text） */
function miniVars(id: ThemeId): Record<string, string> {
  const i = THEME_ORDER.indexOf(id)
  const p = THEME_PREVIEW_PRESETS[i < 0 ? 0 : i]
  return {
    '--tp-paper-l': p.light.paper,
    '--tp-paper-d': p.dark.paper,
    '--tp-accent-l': p.light.accent,
    '--tp-accent-d': p.dark.accent,
    '--tp-text-l': p.light.text,
    '--tp-text-d': p.dark.text,
  }
}

/** 当前实生效明暗（system 档读 documentElement 既有 class——applyAppearance 已同步） */
const isDarkNow = computed(
  () =>
    appearance.value.mode === 'dark' ||
    (appearance.value.mode === 'system' && document.documentElement.classList.contains('dark')),
)

/** 「主题默认」缩略卡=当前主题桌面色 */
const themeCanvasNow = computed(() => {
  const i = THEME_ORDER.indexOf(appearance.value.theme)
  const p = THEME_PREVIEW_PRESETS[i < 0 ? 0 : i]
  return (isDarkNow.value ? p.dark : p.light).canvas
})

const MODES: Array<{ value: AppearanceMode; label: string }> = [
  { value: 'system', label: '跟随系统' },
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
]

/** P1 §8.7：明暗/排版分段控件换 SegmentedPill（原 .seg 直角拼接退役） */
const typographyOptions: ReadonlyArray<{ label: string; value: string }> = [
  { label: '标准', value: 'standard' },
  { label: '宽排', value: 'large' },
]

// ============================================================
// 背景（只换桌面层，稿纸永远保持主题纸色）
// ============================================================

/** 纯色档的色板草稿（进入纯色背景时给一个不刺眼的暖中性默认） */
const bgColorDraft = ref('#dfd8cb')

function onBgKind(kind: 'theme' | 'color' | 'image' | 'texture') {
  if (kind === 'theme') {
    setBg({ kind: 'theme' })
  } else if (kind === 'color') {
    setBg({ kind: 'color', color: bgColorDraft.value, veil: 0.55 })
  } else if (kind === 'texture') {
    const prev = appearance.value.bg
    setBg({ kind: 'texture', texture: prev.kind === 'texture' ? prev.texture : 'grain', veil: prev.kind === 'texture' ? prev.veil ?? 0.35 : 0.35 })
  } else if (kind === 'image') {
    // 图片档：直接开文件选择，选中并压缩成功才落 bg（空 dataUrl 是非法 spec）
    bgFileRef.value?.click()
  }
}

function onBgColor(ev: Event) {
  const color = (ev.target as HTMLInputElement).value
  bgColorDraft.value = color
  const bg = appearance.value.bg
  setBg(bg.kind === 'color' ? { kind: 'color', color, veil: bg.veil ?? 0.55 } : { kind: 'color', color, veil: 0.55 })
}

const bgVeil = computed(() => {
  const bg = appearance.value.bg
  return bg.kind === 'theme' ? 0.55 : bg.veil ?? 0.55
})

function onBgVeil(ev: Event) {
  const v = parseFloat((ev.target as HTMLInputElement).value)
  if (Number.isNaN(v)) return
  const bg = appearance.value.bg
  if (bg.kind === 'theme') return
  setBg({ ...bg, veil: Math.min(0.8, Math.max(0, v)) } as BgSpec)
}

function chooseTexture(texture: 'grain' | 'weave') {
  setBg({ kind: 'texture', texture, veil: bgVeil.value })
}

const bgFileRef = ref<HTMLInputElement | null>(null)
const bgImageBusy = ref(false)

/** 图片压缩（01 §5）：canvas 最长边 1920、JPEG q0.8；压缩后 >1.5MB 拒绝 */
function compressImage(file: File, maxEdge = 1920, quality = 0.8): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      try {
        const scale = Math.min(1, maxEdge / Math.max(img.width, img.height))
        const w = Math.max(1, Math.round(img.width * scale))
        const h = Math.max(1, Math.round(img.height * scale))
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        const ctx = canvas.getContext('2d')
        if (!ctx) throw new Error('canvas 不可用')
        ctx.drawImage(img, 0, 0, w, h)
        resolve(canvas.toDataURL('image/jpeg', quality))
      } finally {
        URL.revokeObjectURL(url)
      }
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('图片解码失败'))
    }
    img.src = url
  })
}

async function onPickBgImage(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许连续选同一张
  if (!file) return
  if (!file.type.startsWith('image/')) {
    showToast('请选择图片文件', 'error')
    return
  }
  bgImageBusy.value = true
  try {
    const dataUrl = await compressImage(file)
    if (dataUrl.length > 1.5 * 1024 * 1024) {
      showToast('图片压缩后仍超过 1.5MB，请换一张更小的图', 'error')
      return
    }
    setBg({ kind: 'image', dataUrl, veil: bgVeil.value })
  } catch {
    showToast('图片读取失败', 'error')
  } finally {
    bgImageBusy.value = false
  }
}

// ============================================================
// 编辑器排版（03 期 §7；迁自旧设置弹窗）：localStorage 设备本地键 + html class；
// 回退=选「标准」即摘 class 零残留
// ============================================================

const EDITOR_TYPOGRAPHY_KEY = 'velluma:editor-typography'
const editorTypography = ref<'standard' | 'large'>('standard')
try {
  if (localStorage.getItem(EDITOR_TYPOGRAPHY_KEY) === 'large') editorTypography.value = 'large'
} catch {}
watch(editorTypography, (mode) => {
  document.documentElement.classList.toggle('editor-type-large', mode === 'large')
  try {
    if (mode === 'large') localStorage.setItem(EDITOR_TYPOGRAPHY_KEY, 'large')
    else localStorage.removeItem(EDITOR_TYPOGRAPHY_KEY)
  } catch {}
})

// ============================================================
// Esc 收起（分层栈：写作台先剥自己的层，抽屉随后；无焦点陷阱——不抢打字焦点）
// ============================================================

const escStack = useEscStack()
let escId: symbol | null = null
watch(appearanceVisible, (on) => {
  if (on) {
    if (!escId) escId = escStack.push(() => closeAppearance(), 'appearance-panel')
  } else if (escId) {
    escStack.remove(escId)
    escId = null
  }
}, { immediate: true })
onScopeDispose(() => {
  if (escId) {
    escStack.remove(escId)
    escId = null
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="ap-slide">
      <aside v-if="appearanceVisible" class="appearance-panel" aria-label="外观设置">
        <header class="ap-head">
          <span class="ap-title">外观</span>
          <button class="ap-close" title="收起（Esc）" @click="closeAppearance">
            <Icon name="x-mark" :size="15" />
          </button>
        </header>

        <div class="ap-body">
          <!-- 主题：行式卡（05 §9.1 v2：16:10 上下半切浅/深微型场景预览，
               accent 标题行+正文线+薄荷/朱砂点；选中=accent ring+柔光+对勾 chip） -->
          <section>
            <div class="ap-section-title eyebrow">主题</div>
            <div class="theme-list">
              <button
                v-for="t in themeCards"
                :key="t.id"
                type="button"
                class="theme-row"
                :class="{ active: appearance.theme === t.id }"
                @click="setTheme(t.id)"
              >
                <span class="theme-mini" :style="{ ...miniVars(t.id), '--preview-grain': PREVIEW_GRAIN_URI }">
                  <span class="tm-half tm-half--light">
                    <i class="tm-title"></i>
                    <i class="tm-line"></i>
                    <i class="tm-line tm-line--short"></i>
                  </span>
                  <span class="tm-half tm-half--dark">
                    <i class="tm-title"></i>
                    <i class="tm-line"></i>
                  </span>
                  <span class="tm-dots"><i class="tm-mint"></i><i class="tm-cinnabar"></i></span>
                </span>
                <span class="theme-meta">
                  <span class="theme-name">{{ t.name }}</span>
                  <span class="theme-word">{{ t.word }}</span>
                </span>
                <span v-if="appearance.theme === t.id" class="tm-check" aria-hidden="true">
                  <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4.5 10.5l3.5 3.5 7.5-8" />
                  </svg>
                </span>
              </button>
            </div>
          </section>

          <!-- 明暗 -->
          <section>
            <div class="ap-section-title eyebrow">明暗</div>
            <SegmentedPill
              :model-value="appearance.mode"
              :options="MODES"
              @update:model-value="(v) => setMode(v as AppearanceMode)"
            />
          </section>

          <!-- 桌面背景（只铺桌面，稿纸永远保持主题纸色） -->
          <section>
            <div class="ap-section-title eyebrow">桌面背景</div>
            <!-- 05 §9.1 v2：四档 2×2 缩略卡。「图片」档保留 P1 单向绑定语义：
                 点击只弹文件选择器，取消选择时 .on 不残留（勿回退 v-model） -->
            <div class="bg-grid">
              <button
                type="button"
                class="bg-card"
                :class="{ on: appearance.bg.kind === 'theme' }"
                @click="onBgKind('theme')"
              >
                <span class="bg-thumb" :style="{ background: themeCanvasNow }">
                  <i class="bg-thumb-mark">Aa</i>
                </span>
                <span class="bg-card-name">主题默认</span>
              </button>
              <button
                type="button"
                class="bg-card"
                :class="{ on: appearance.bg.kind === 'color' }"
                @click="onBgKind('color')"
              >
                <span
                  class="bg-thumb"
                  :style="appearance.bg.kind === 'color' ? { background: appearance.bg.color } : undefined"
                >
                  <Icon v-if="appearance.bg.kind !== 'color'" name="paint-brush" :size="15" />
                </span>
                <span class="bg-card-name">纯色</span>
              </button>
              <button
                type="button"
                class="bg-card"
                :class="{ on: appearance.bg.kind === 'image' }"
                @click="onBgKind('image')"
              >
                <span class="bg-thumb">
                  <img v-if="appearance.bg.kind === 'image'" :src="appearance.bg.dataUrl" alt="背景图缩略" />
                  <Icon v-else name="arrow-up-tray" :size="15" />
                </span>
                <span class="bg-card-name">{{ bgImageBusy ? '处理中…' : '图片' }}</span>
              </button>
              <button
                type="button"
                class="bg-card"
                :class="{ on: appearance.bg.kind === 'texture' }"
                @click="onBgKind('texture')"
              >
                <span class="bg-thumb bg-thumb--texture" :style="{ backgroundImage: PREVIEW_GRAIN_URI }"></span>
                <span class="bg-card-name">纸纹</span>
              </button>
            </div>
            <div v-if="appearance.bg.kind === 'color'" class="bg-extra">
              <input type="color" :value="appearance.bg.color" @input="onBgColor" aria-label="背景颜色" />
              <label class="bg-veil">遮罩
                <input type="range" min="0" max="0.8" step="0.05" :value="bgVeil" @input="onBgVeil" />
                {{ Math.round(bgVeil * 100) }}%
              </label>
            </div>
            <div v-else-if="appearance.bg.kind === 'image'" class="bg-extra">
              <button type="button" class="link-btn" @click="bgFileRef?.click()">选择图片…</button>
              <input ref="bgFileRef" type="file" accept="image/*" hidden @change="onPickBgImage" />
              <label class="bg-veil">遮罩
                <input type="range" min="0" max="0.8" step="0.05" :value="bgVeil" @input="onBgVeil" />
                {{ Math.round(bgVeil * 100) }}%
              </label>
              <button type="button" class="link-btn" @click="setBg({ kind: 'theme' })">清除背景</button>
            </div>
            <div v-else-if="appearance.bg.kind === 'texture'" class="bg-extra">
              <button type="button" class="texture-chip" :class="{ on: appearance.bg.texture === 'grain' }" @click="chooseTexture('grain')">细纹</button>
              <button type="button" class="texture-chip" :class="{ on: appearance.bg.texture === 'weave' }" @click="chooseTexture('weave')">织纹</button>
              <label class="bg-veil">遮罩
                <input type="range" min="0" max="0.8" step="0.05" :value="bgVeil" @input="onBgVeil" />
                {{ Math.round(bgVeil * 100) }}%
              </label>
            </div>
          </section>

          <!-- 稿纸排版（只覆写字号/行高两枚 token，纸列 880px 不变） -->
          <section>
            <div class="ap-section-title eyebrow">稿纸排版</div>
            <SegmentedPill
              :model-value="editorTypography"
              :options="typographyOptions"
              @update:model-value="(v) => (editorTypography = v as 'standard' | 'large')"
            />
          </section>

          <!-- 动效 -->
          <section>
            <div class="ap-section-title eyebrow">动效</div>
            <label class="check-row">
              <input
                type="checkbox"
                :checked="appearance.motionLow"
                @change="setMotionLow(($event.target as HTMLInputElement).checked)"
              />
              <span>降低动效（罗盘摆动/呼吸微光等全部静止）</span>
            </label>
          </section>

          <p class="ap-hint">主题与外观只保存在这台设备上，即时生效、无需保存。正文纸感、朱批、薄荷 AI 指示在所有主题下保持一致；背景只铺桌面，稿纸永远干净。</p>
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* 左缘贴边抽屉：紧挨 AppRail（56px=3.5rem）右沿、全高、无遮罩——
   换肤的即时反馈靠「身后应用裸露可见」，任何遮罩都会杀掉这份反馈 */
.appearance-panel {
  position: fixed;
  left: 3.5rem;
  top: 0;
  bottom: 0;
  width: 352px;
  z-index: var(--z-drawer); /* 分层表：页内飞出抽屉层（85）——低于模态(110)/Toast(120) */
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  border-right: 1px solid var(--line-faint);
  border-top: 1px solid var(--line-faint);
  border-bottom: 1px solid var(--line-faint);
  border-radius: 0 var(--radius-lg) var(--radius-lg) 0;
  box-shadow: var(--elev-3-shadow);
}

/* P1 挂账（05 §9.1）：抽屉自身过渡 token 化 */
.ap-slide-enter-active,
.ap-slide-leave-active {
  transition: transform var(--dur-2) var(--ease-out), opacity var(--dur-2) var(--ease-out);
}
.ap-slide-enter-from,
.ap-slide-leave-to {
  transform: translateX(-14px);
  opacity: 0;
}

.ap-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 12px 10px 16px;
  border-bottom: 1px solid var(--line-faint);
  flex-shrink: 0;
}

.ap-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}

.ap-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}
.ap-close:hover {
  background: var(--state-hover);
  color: var(--text-primary);
}

.ap-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* N1 §3.6：分区眉标收编 .eyebrow 工具类（本类留作挂点，防样式悬空） */
.ap-section-title {
  /* 皮肤由 .eyebrow 提供（模板挂 class="ap-section-title eyebrow"） */
}

/* ---------- 主题行式卡 ---------- */

.theme-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.theme-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
  cursor: pointer;
  position: relative;
  text-align: left;
  transition: border-color var(--dur-2) var(--ease-out), box-shadow var(--dur-2) var(--ease-out);
}

.theme-row:hover {
  border-color: var(--text-faint);
}

/* P2 §9.1 选中态：accent 2px ring + --glow-accent 柔光（退役 6px 朱点角标与
   旧 1px 双描边——对勾 chip 见 .tm-check） */
.theme-row.active {
  border-color: transparent;
  box-shadow: 0 0 0 2px var(--accent-500), var(--glow-accent);
}

.tm-check {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 18px;
  height: 18px;
  border-radius: 999px;
  background: var(--accent-500);
  color: var(--bg-canvas);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--elev-1-shadow);
}
.tm-check svg {
  width: 11px;
  height: 11px;
}

/* 16:10 微型场景预览：上半=浅档纸面、下半=深档纸面（半切），
   各带 accent 标题行 + 正文线；薄荷/朱砂两点居右下；极低剂量 grain 复用
   PREVIEW_GRAIN_URI（独立于 useAppearance TEXTURES 对拍契约） */
.theme-mini {
  display: block;
  width: 76px;
  aspect-ratio: 16 / 10;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(0, 0, 0, 0.06);
  position: relative;
  overflow: hidden;
}

.tm-half {
  position: absolute;
  left: 0;
  right: 0;
  height: 50%;
  background-image: var(--preview-grain, none);
}
.tm-half--light {
  top: 0;
  background-color: var(--tp-paper-l);
}
.tm-half--dark {
  bottom: 0;
  background-color: var(--tp-paper-d);
}

.tm-title {
  position: absolute;
  left: 16%;
  width: 30%;
  height: 3px;
  border-radius: 2px;
}
.tm-half--light .tm-title {
  top: 24%;
  background: var(--tp-accent-l);
}
.tm-half--dark .tm-title {
  top: 26%;
  background: var(--tp-accent-d);
}

.tm-line {
  position: absolute;
  left: 16%;
  right: 18%;
  height: 2px;
  border-radius: 2px;
  opacity: 0.55;
}
.tm-half--light .tm-line {
  top: 58%;
  background: var(--tp-text-l);
}
.tm-half--light .tm-line--short {
  top: 76%;
  right: 44%;
}
.tm-half--dark .tm-line {
  top: 62%;
  background: var(--tp-text-d);
}

.tm-dots {
  position: absolute;
  right: 7%;
  bottom: 8%;
  display: flex;
  gap: 3px;
}

.tm-mint,
.tm-cinnabar {
  width: 5px;
  height: 5px;
  border-radius: 999px;
}

.tm-mint {
  background: var(--mint);
}

.tm-cinnabar {
  background: var(--cinnabar);
}

.theme-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.theme-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}

.theme-word {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* ---------- 分段控件 ---------- */
/* P1 §8.7：.seg 直角拼接整体退役，换 SegmentedPill（components/SegmentedPill.vue） */

/* ---------- 背档：2×2 缩略卡（05 §9.1 v2） ---------- */

.bg-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.bg-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 8px 6px 7px;
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
  background: var(--bg-primary);
  cursor: pointer;
  transition: border-color var(--dur-2) var(--ease-out), box-shadow var(--dur-2) var(--ease-out);
}

.bg-card:hover {
  border-color: var(--text-faint);
}

.bg-card.on {
  border-color: transparent;
  box-shadow: 0 0 0 2px var(--accent-500);
}

.bg-thumb {
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line);
  background: var(--surface-sunken);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  overflow: hidden;
  position: relative;
}
.bg-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.bg-thumb--texture {
  background-color: var(--paper-bg);
  background-size: 120px 120px;
}
.bg-thumb-mark {
  font-family: var(--font-heading);
  font-size: var(--text-sm);
  color: var(--text-muted);
  opacity: 0.7;
}

.bg-card-name {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

/* ---------- 原生控件 token 皮肤（05 §9.1；纯 webkit 伪元素，零 JS 库） ---------- */

/* range：surface-sunken 全圆轨道 + accent 圆点（elev-1 语义=line 边+sm 影） */
.bg-veil input[type='range'] {
  -webkit-appearance: none;
  appearance: none;
  width: 92px;
  height: 4px;
  border-radius: 999px;
  background: var(--surface-sunken);
  outline: none;
  cursor: pointer;
}
.bg-veil input[type='range']::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: var(--accent-500);
  border: 1px solid var(--line);
  box-shadow: var(--elev-1-shadow);
  cursor: pointer;
}
.bg-veil input[type='range']::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: var(--accent-500);
  border: 1px solid var(--line);
  box-shadow: var(--elev-1-shadow);
  cursor: pointer;
}

/* color：swatch 壳（line 边 + radius-md） */
.bg-extra input[type='color'] {
  -webkit-appearance: none;
  appearance: none;
  width: 34px;
  height: 24px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: none;
  cursor: pointer;
}
.bg-extra input[type='color']::-webkit-color-swatch-wrapper {
  padding: 0;
}
.bg-extra input[type='color']::-webkit-color-swatch {
  border: none;
  border-radius: calc(var(--radius-md) - 1px);
}
.bg-extra input[type='color']::-moz-color-swatch {
  border: none;
  border-radius: calc(var(--radius-md) - 1px);
}

/* checkbox：未选=surface-float+line 边；选中=accent 底 + bg-canvas 勾（C6 范式） */
.check-row input[type='checkbox'] {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  margin: 1px 0 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-xs);
  background: var(--surface-float);
  cursor: pointer;
  position: relative;
  transition: background var(--dur-1) var(--ease-out), border-color var(--dur-1) var(--ease-out);
}
.check-row input[type='checkbox']:checked {
  background: var(--accent-500);
  border-color: var(--accent-500);
}
.check-row input[type='checkbox']:checked::after {
  content: '';
  position: absolute;
  left: 4.5px;
  top: 1px;
  width: 4px;
  height: 8px;
  border: solid var(--bg-canvas);
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

/* ---------- 背档附加行 ---------- */

.bg-extra {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 8px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.bg-veil {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.link-btn {
  border: none;
  background: none;
  padding: 0;
  color: var(--accent-500);
  font-size: var(--text-xs);
  cursor: pointer;
  text-decoration: underline;
}

.texture-chip {
  padding: 4px 12px;
  font-size: var(--text-xs);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  background: none;
  color: var(--text-secondary);
  cursor: pointer;
}

.texture-chip.on {
  border-style: solid;
  border-color: var(--accent-500);
  color: var(--accent-500);
}

/* ---------- 动效勾选行 ---------- */

.check-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-primary);
  cursor: pointer;
}

/* 底部 hint（05 §9.1）：--text-sm + --line-faint 实线分隔（退役 11px+虚线） */
.ap-hint {
  margin: 4px 0 0;
  font-size: var(--text-sm);
  line-height: var(--lh-normal);
  color: var(--text-muted);
  border-top: 1px solid var(--line-faint);
  padding-top: 10px;
}
</style>
