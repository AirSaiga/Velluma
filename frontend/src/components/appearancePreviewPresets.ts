/**
 * 主题预览卡色值唯一权威（05-visual-modernization-plan §9.1 THEME_PREVIEW_PRESETS 集中）。
 *
 * 5 主题 × 明暗 × {paper, canvas, accent, text, muted}，与 style.css 十主题块
 * **同源维护**——十块头注释已标明本文件（改主题实色两边一起改）。
 *
 * 豁免说明：本文件色值属「预览场景示意」，渲染面仅限 AppearancePanel 主题卡
 * 缩略图；真实换肤消费 style.css token，应用内任何其他组件不得 import 本文件。
 */
export interface ThemePreviewShade {
  /** 纸面色（--paper-bg 预览示意） */
  paper: string
  /** 桌面/卡面色（--bg-primary 预览示意） */
  canvas: string
  /** 主题 accent（--accent-500） */
  accent: string
  /** 主文字（--text-primary） */
  text: string
  /** 次级文字（--text-secondary） */
  muted: string
}

export interface ThemePreviewEntry {
  name: string
  word: string
  light: ThemePreviewShade
  dark: ThemePreviewShade
}

/** 五主题展示序（与 AppRail/01 §3 序一致） */
export const THEME_ORDER: ReadonlyArray<string> = ['paper', 'minimal', 'soft', 'pro', 'anime']

export const THEME_PREVIEW_PRESETS: ReadonlyArray<ThemePreviewEntry> = [
  {
    name: '暖纸',
    word: '默认',
    light: { paper: '#fefdfb', canvas: '#f7f4ed', accent: '#7c6aad', text: '#2c2c2c', muted: '#6b6560' },
    dark: { paper: '#26231e', canvas: '#1a1815', accent: '#a78bfa', text: '#ede8df', muted: '#bfb8ab' },
  },
  {
    name: '极简',
    word: '校样',
    light: { paper: '#ffffff', canvas: '#f4f4f2', accent: '#3b62d8', text: '#161616', muted: '#4f4f4f' },
    dark: { paper: '#191919', canvas: '#0e0e0e', accent: '#94b4f8', text: '#ececec', muted: '#b3b3b3' },
  },
  {
    name: '柔和',
    word: '奶油',
    light: { paper: '#fdfaf4', canvas: '#f5f0e8', accent: '#b77e8d', text: '#4b423b', muted: '#7d7166' },
    dark: { paper: '#2d2822', canvas: '#221d19', accent: '#d9a7b0', text: '#ece2d6', muted: '#c3b6a6' },
  },
  {
    name: '专业',
    word: '审校',
    light: { paper: '#ffffff', canvas: '#eef1f5', accent: '#2f6db3', text: '#20262e', muted: '#525c68' },
    dark: { paper: '#1a222b', canvas: '#10151b', accent: '#82b3e5', text: '#e3e9ef', muted: '#b0bac5' },
  },
  {
    name: '二次元',
    word: '樱',
    light: { paper: '#fffdfd', canvas: '#fff2f6', accent: '#ef5390', text: '#43304e', muted: '#7d6586' },
    dark: { paper: '#221a2c', canvas: '#17101f', accent: '#ffa5c8', text: '#f3eafd', muted: '#cbb8dd' },
  },
]

/** 主题卡缩略图用的极低剂量 grain（独立于 useAppearance TEXTURES——那对拍契约勿动） */
export const PREVIEW_GRAIN_URI =
  'url("data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' width=\'120\' height=\'120\'><filter id=\'g\'><feTurbulence type=\'fractalNoise\' baseFrequency=\'0.9\' numOctaves=\'2\'/><feColorMatrix values=\'0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.05 0\'/></filter><rect width=\'120\' height=\'120\' filter=\'url(%23g)\'/></svg>")'
