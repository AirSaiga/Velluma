/**
 * 拼音检索（二期：外部抽屉三面板共用）。
 *
 * 用 pinyin-pro 官方 match：一次覆盖 原文子串 ∪ 全拼 ∪ 首字母 ∪ 部分音节 ∪
 * 中文+拼音混输（探针实证：'linchen'/'lc'/'linc'/'林c'/'LINCHEN' 均 [0,1] 命中、
 * 中位 'cunzhuang' 命中「村庄」、拉丁透传）。pinyin-pro 体积可观（数百 KB），
 * 动态 import 懒加载——任一抽屉搜索框有输入才拉取（WorldView 侧 watch 触发
 * ensurePinyin）；加载完成前退化为子串匹配（=一期行为），pinyinReady 置位后
 * 依赖它的 computed 自动重算。
 */
import { ref } from 'vue'

/** 拼音引擎就绪（reactive：matchesQuery 内读取，调用方 computed 据此自动重算） */
export const pinyinReady = ref(false)

type MatchFn = (text: string, pinyin: string) => number[] | null
let matchFn: MatchFn | null = null
let loading: Promise<void> | null = null

/** 懒加载拼音引擎；失败静默（搜索永远退化为子串匹配，不报错不打断） */
export function ensurePinyin(): Promise<void> {
  if (matchFn) return Promise.resolve()
  if (loading) return loading
  loading = import('pinyin-pro')
    .then((m) => {
      matchFn = m.match as unknown as MatchFn
      pinyinReady.value = true
    })
    .catch(() => {
      /* 拉取失败：保持子串匹配 */
    })
  return loading
}

/** 任一字段命中即真；空查询恒真 */
export function matchesQuery(
  query: string,
  ...texts: (string | null | undefined)[]
): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  void pinyinReady.value // 依赖收集：就绪后调用方 computed 自动重算
  for (const t of texts) {
    if (!t) continue
    const lower = t.toLowerCase()
    if (lower.includes(q)) return true
    if (matchFn && matchFn(lower, q)) return true
  }
  return false
}
