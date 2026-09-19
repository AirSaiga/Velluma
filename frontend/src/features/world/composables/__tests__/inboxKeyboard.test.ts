/**
 * 对拍口径：锁「收件箱键盘裁决」纯函数契约（02 候选回流修缮 M3）——
 * 键位映射（↑↓/←→/Enter/Delete/Backspace/Space）、循环移动、空列表 -1、
 * 越界光标归零。组件接线（焦点/高亮/裁决调用）属 UI 胶水，IAB 实机验证。
 */
import { describe, expect, it } from 'vitest'
import {
  inboxNavKey,
  isToggleKey,
  moveInboxIndex,
  verdictFromKey,
} from '../inboxKeyboard'

describe('inboxNavKey', () => {
  it('↑↓ 映射为移动量', () => {
    expect(inboxNavKey('ArrowUp')).toBe(-1)
    expect(inboxNavKey('ArrowDown')).toBe(1)
  })
  it('其他键一律 0（不拦截）', () => {
    expect(inboxNavKey('ArrowLeft')).toBe(0)
    expect(inboxNavKey('Enter')).toBe(0)
    expect(inboxNavKey('a')).toBe(0)
    expect(inboxNavKey('')).toBe(0)
  })
})

describe('moveInboxIndex', () => {
  it('常规移动', () => {
    expect(moveInboxIndex(0, 1, 5)).toBe(1)
    expect(moveInboxIndex(3, 1, 5)).toBe(4)
    expect(moveInboxIndex(4, -1, 5)).toBe(3)
  })
  it('首尾循环（首行 ↑ 到末行 / 末行 ↓ 回首行）', () => {
    expect(moveInboxIndex(0, -1, 5)).toBe(4)
    expect(moveInboxIndex(4, 1, 5)).toBe(0)
  })
  it('空列表返回 -1（无光标态）', () => {
    expect(moveInboxIndex(0, 1, 0)).toBe(-1)
    expect(moveInboxIndex(2, -1, 0)).toBe(-1)
  })
  it('越界/负数光标先归零再移动（裁决后列表变短的场景）', () => {
    expect(moveInboxIndex(9, 1, 3)).toBe(1)
    expect(moveInboxIndex(-1, -1, 3)).toBe(2)
  })
  it('单条列表移动恒为 0', () => {
    expect(moveInboxIndex(0, 1, 1)).toBe(0)
    expect(moveInboxIndex(0, -1, 1)).toBe(0)
  })
})

describe('verdictFromKey', () => {
  it('→/Enter = 采纳', () => {
    expect(verdictFromKey('ArrowRight')).toBe('accept')
    expect(verdictFromKey('Enter')).toBe('accept')
  })
  it('←/Delete/Backspace = 丢弃', () => {
    expect(verdictFromKey('ArrowLeft')).toBe('reject')
    expect(verdictFromKey('Delete')).toBe('reject')
    expect(verdictFromKey('Backspace')).toBe('reject')
  })
  it('其他键 null（不拦截，编辑器按键不受扰）', () => {
    expect(verdictFromKey('ArrowUp')).toBe(null)
    expect(verdictFromKey(' ')).toBe(null)
    expect(verdictFromKey('Escape')).toBe(null)
  })
})

describe('isToggleKey', () => {
  it('只有空格是勾选键', () => {
    expect(isToggleKey(' ')).toBe(true)
    expect(isToggleKey('Spacebar')).toBe(false)
    expect(isToggleKey('Enter')).toBe(false)
  })
})
