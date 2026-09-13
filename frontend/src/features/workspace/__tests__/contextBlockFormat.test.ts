// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Velluma Contributors
/**
 * 保字排版解析器对拍测试（docs/design/ux-redesign/09-ai-view-redesign.md §5.5）。
 *
 * 核心契约=保字不变式：normalize(解析摊平文本) === normalize(原文)——
 * 解析只允许把结构标记（#/-、行首缩进、｜、：分隔符、空白）转成排版结构，
 * 其余字符一个都不许丢。样例全部取自后端真实产出的字面格式
 * （knowledge_plane.py / adaptive_prompts.py / consistency.py 核实）。
 */
import { describe, expect, it } from 'vitest'
import {
  SEGMENT_TITLES,
  flattenNodes,
  friendlySource,
  inlineParse,
  markTone,
  normalizeForInvariant,
  parseBlockContent,
  segmentOfKey,
} from '../presentation/contextBlockFormat'

/** 保字不变式断言（所有样例块共用） */
function expectInvariant(content: string, key = ''): void {
  const flat = flattenNodes(parseBlockContent(content, key))
  expect(normalizeForInvariant(flat)).toBe(normalizeForInvariant(content))
}

// ===== 后端真实字面格式样例（逐格式对拍） =====

const ENTITIES = `
# 在场与相关人物·物件（事实层，档案为作者录入原文，一字未删）
- 周砚〔在场〕【此刻·t=2177·农舍客厅】（别名：老周、周师傅）
  档案（作者录入，未删节）： 五十六岁，木匠出身，左手三根断指。
  早年丧妻，独自把女儿拉扯大。
- 王阿婆【已死亡·不得出场、不得开口】
- 锈铁盒（物件）：周砚随身携带的铁盒，从不上锁。
注：条目内【此刻】由事件推演得出；与档案描述冲突时，以【此刻】为准。`

const SCENE = `
# 场景身份（事实层，生成以此为准）
本章场景：农舍客厅（作者钉定）｜地点档案：北岸要塞：河东最大据点；农舍客厅：周家的堂屋｜叙事时刻：t=2177（本章锚）`

const WARM = `
# 本章打算（作者定的方向，软约束）
本章打算：送别之后回城，试探工头的口风
非写不可的情节：周砚交还钥匙；明姐留饭被拒`

const CANON = `
# 作者脑中世界图谱（Canon）
## 作者脑中的真相 [private] ★ 绝不许在正文直接写出
- 周砚·左手：义手（揭示计划：第15章饭桌戏揭开）
  → 写作时可作为角色隐藏动机，但绝不能用对话/叙述/心理独白直接说出
## 必须遵守的已建立事实 [public]
- 明姐身份：北岸要塞的后厨管事`

const SECRETS = `
# 作者私有设定（你知晓以下秘密以协助铺垫与暗示，但绝不能直接写出）
- 周砚：知道女儿还活着，装作不知`

const ECHOES = `
# 前情回响（作者更早章节写过的片段）
以下片段用于保持细节一致、自然呼应前情，禁止大段复述原文：
- 第3章：周砚在渡口把伞塞给女儿，自己淋雨回去
- 第7章：工头提过一句「南桥的账不对」`

const SAMPLES = `
# 作者笔迹示范（学其语感、节奏与用词习惯——只学写法，禁止复制内容或意象）
【示范 1】
他把茶碗放下，没有看明姐。灶上的水开了，没人去提。
【示范 2】
风从北边来。晾衣绳上那件旧褂子鼓了一下，又瘪下去。
（以上是这位作者亲笔写的字。你接下来写的每一句，都应该像同一个人写的。）`

const PROPER_NOUNS = `
# 实体称呼（硬约束）
正文若写到下列名称，必须与此处完全一致，禁止改名、缩写或生造昵称；这只是称呼规范，不是登场清单——不要为了用上某个名字而安排情节：
周砚、明姐、北岸要塞、锈铁盒`

const NEGATIVE = `
# 本书禁词（提醒档，尽量避开）
眼底闪过一丝、嘴角勾起、不禁`

const SPATIAL = `
# 空间常识（比例尺粗估，数字天然带「约」）
北岸要塞→南桥渡口：步行约三小时（约十二里）；雨季涨水要绕上游浅滩`

const PROSE = `
# 白描契约与假感官封杀令（最高优先级）
一、情绪不走人物内心，走物件：写他难过，先写他手里的东西。`

const RECENT_PIN = `【此刻·切记】在场：周砚、明姐｜已死亡（不得出场）：王阿婆｜场景：农舍客厅｜t=2177`

describe('contextBlockFormat 保字不变式', () => {
  it('全部真实格式样例：解析摊平后归一文本与原文相等', () => {
    expectInvariant(ENTITIES, 'entities')
    expectInvariant(SCENE, 'scene')
    expectInvariant(WARM, 'warm')
    expectInvariant(CANON, 'canon')
    expectInvariant(SECRETS, 'secrets')
    expectInvariant(ECHOES, 'echoes')
    expectInvariant(SAMPLES, 'author_samples')
    expectInvariant(PROPER_NOUNS, 'proper_nouns')
    expectInvariant(NEGATIVE, 'negative')
    expectInvariant(SPATIAL, 'spatial')
    expectInvariant(PROSE, 'anti_pseudo_sensory')
    expectInvariant(RECENT_PIN)
  })

  it('任意兜底文本（未预期格式）也逐字保留', () => {
    expectInvariant('random ==== :::: 无匹配行\n另一行【杂mark】〔x〕尾')
    expectInvariant('单行无结构')
  })
})

describe('contextBlockContent 节点形态', () => {
  it('entities：heading + item（marks 原样）+ profile 档案体 + note 尾注', () => {
    const nodes = parseBlockContent(ENTITIES, 'entities')
    expect(nodes[0]).toEqual({ type: 'heading', text: '在场与相关人物·物件（事实层，档案为作者录入原文，一字未删）' })
    const item = nodes[1]
    expect(item.type).toBe('item')
    if (item.type === 'item') {
      expect(item.text).toContain('周砚〔在场〕【此刻·t=2177·农舍客厅】（别名：老周、周师傅）')
    }
    const profiles = nodes.filter((n) => n.type === 'profile')
    expect(profiles).toHaveLength(2)
    if (profiles[0].type === 'profile') {
      expect(profiles[0].text).toContain('档案（作者录入，未删节）：')
    }
    expect(nodes[nodes.length - 1]?.type).toBe('note')
  })

  it('scene：｜ 切段成 kv 行，段内字符保留', () => {
    const nodes = parseBlockContent(SCENE, 'scene')
    const kvs = nodes.filter((n) => n.type === 'kv')
    expect(kvs.length).toBeGreaterThanOrEqual(3)
    if (kvs[0].type === 'kv') {
      expect(kvs[0].k).toBe('本章场景')
      expect(kvs[0].v).toBe('农舍客厅（作者钉定）')
    }
  })

  it('canon：## 段头识别为 heading；"→ " 缩进行归 profile', () => {
    const nodes = parseBlockContent(CANON, 'canon')
    const headings = nodes.filter((n) => n.type === 'heading')
    expect(headings).toHaveLength(3)
    if (headings[1].type === 'heading') {
      expect(headings[1].text).toContain('[private]')
    }
    const arrow = nodes.find((n) => n.type === 'profile' && n.text.startsWith('→'))
    expect(arrow).toBeTruthy()
  })

  it('样本块：【示范 N】识别为 sample 节点，散文行走 plain（衬线渲染）', () => {
    const nodes = parseBlockContent(SAMPLES, 'author_samples')
    const samples = nodes.filter((n) => n.type === 'sample')
    expect(samples).toHaveLength(2)
    const plains = nodes.filter((n) => n.type === 'plain')
    expect(plains.length).toBeGreaterThanOrEqual(3)
  })

  it('recency 钉：【此刻·切记】前缀并入首段 k，其余段各自成行', () => {
    const nodes = parseBlockContent(RECENT_PIN)
    const kvs = nodes.filter((n) => n.type === 'kv')
    if (kvs[0].type === 'kv') {
      expect(kvs[0].k).toBe('【此刻·切记】在场')
      expect(kvs[0].v).toBe('周砚、明姐')
    }
    if (kvs[1].type === 'kv') {
      expect(kvs[1].k).toBe('已死亡（不得出场）')
    }
    expect(nodes.some((n) => n.type === 'plain' && n.text === 't=2177')).toBe(true)
  })

  it('通用 kv：短 k（≤12 字且无句读）切分，含句读的长行落 plain', () => {
    const nodes = parseBlockContent(WARM, 'warm')
    expect(nodes.filter((n) => n.type === 'kv')).toHaveLength(2)
    // proper_nouns 说明句（逗号早现）不得被误切 kv
    const pn = parseBlockContent(PROPER_NOUNS, 'proper_nouns')
    expect(pn.filter((n) => n.type === 'kv')).toHaveLength(0)
  })

  it('空串 / 纯空白 → 空节点数组', () => {
    expect(parseBlockContent('', 'entities')).toEqual([])
    expect(parseBlockContent('\n\n  \n', 'entities')).toEqual([])
  })
})

describe('inlineParse / markTone', () => {
  it('【】〔〕整段切为 mark，字符逐字保留', () => {
    const spans = inlineParse('周砚〔在场〕【此刻·t=5】（别名：老周）')
    expect(spans.map((s) => s.text).join('')).toBe('周砚〔在场〕【此刻·t=5】（别名：老周）')
    expect(spans.filter((s) => s.mark).map((s) => s.text)).toEqual(['〔在场〕', '【此刻·t=5】'])
  })

  it('markTone：在场/死亡/此刻/其余 分档', () => {
    expect(markTone('〔在场〕')).toBe('present')
    expect(markTone('【已死亡·不得出场、不得开口】')).toBe('dead')
    expect(markTone('【此刻·t=5】')).toBe('moment')
    expect(markTone('【示范 1】')).toBe('neutral')
  })
})

describe('段分组与来源文案', () => {
  it('segmentOfKey：14 个在册 key 归三段，未知 key 落 other', () => {
    expect(segmentOfKey('scene')).toBe('fact')
    expect(segmentOfKey('relations')).toBe('fact')
    expect(segmentOfKey('negative')).toBe('guard')
    expect(segmentOfKey('spatial')).toBe('guard')
    expect(segmentOfKey('author_samples')).toBe('style')
    expect(segmentOfKey('anti_pseudo_sensory')).toBe('style')
    expect(segmentOfKey('future_block')).toBe('other')
    expect(SEGMENT_TITLES.fact).toBe('事实与设定')
  })

  it('friendlySource：黑话映射 + 知识平面前缀剥离', () => {
    expect(friendlySource('知识平面 · 世界实体')).toBe('世界页 · 实体档案')
    expect(friendlySource('知识平面 · 章级绑定')).toBe('章节旧表（未接世界页）')
    expect(friendlySource('打算 tab · spine（章内冻结）')).toBe('打算 tab（章内不变）')
    expect(friendlySource('真相层（含私有）')).toBe('真相账本（含私有）')
    expect(friendlySource('文风样本库 · 对话场景优先')).toBe('文风样本库 · 优先对话段')
    expect(friendlySource('场景钉 + 叙事时刻')).toBe('场景钉 + 时间锚')
    expect(friendlySource('记忆召回')).toBe('记忆召回') // 已是人话的原样透传
  })
})
