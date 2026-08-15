import type { Timestamp } from './types'

/**
 * 时间戳 ↔ 架空历法（解耦）。
 *
 * 内部存连续日计数（Timestamp=number，以创世为元年），显示层才转年月日。
 * 换架空历法只改本文件（默认：1 年 = 365 日，1 月 = 30 日，创世元年）。
 */
const DAYS_PER_YEAR = 365
const DAYS_PER_MONTH = 30

export interface YMD {
  year: number
  month: number
  day: number
}

export function breakdownTime(t: Timestamp): YMD {
  let remaining = Math.max(0, Math.floor(t))
  const year = Math.floor(remaining / DAYS_PER_YEAR) + 1
  remaining -= (year - 1) * DAYS_PER_YEAR
  const month = Math.floor(remaining / DAYS_PER_MONTH) + 1
  remaining -= (month - 1) * DAYS_PER_MONTH
  const day = remaining + 1
  return { year, month, day }
}

export function fromYMD(year: number, month: number, day: number): Timestamp {
  const y = Math.max(1, year)
  const m = Math.min(12, Math.max(1, month))
  const d = Math.min(30, Math.max(1, day))
  return (y - 1) * DAYS_PER_YEAR + (m - 1) * DAYS_PER_MONTH + (d - 1)
}

export function formatTime(t: Timestamp): string {
  const { year, month, day } = breakdownTime(t)
  return `第${year}年${month}月${day}日`
}

/** 年份（时间轴年粒度刻度用） */
export function yearOf(t: Timestamp): number {
  return breakdownTime(t).year
}
