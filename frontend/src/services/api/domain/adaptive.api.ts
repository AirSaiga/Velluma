/**
 * NLE-ADF 3.0 自适应辅助 API（心跳模式）。
 *
 * 核心协议：前端防抖发 heartbeat（作者状态），后端调度器决定激活哪些组件，
 * 异步跑、写回世界模型。前端下次心跳拿到组件产出（挂件/建议）。
 *
 * 端点：
 * - heartbeat：作者状态心跳 → 返回快照 + 挂件
 * - settle：段落锁死 → 层1追加 + 沉淀
 * - finish：完稿 → 后处理
 * - model：拉取世界模型快照（恢复用）
 * - stitchGhost：微缝合（SSE，按需）
 */
import { streamSse } from '../stream'
import { requestJson } from '../transport'

// ============================================================
// 类型定义
// ============================================================

export interface DockPart {
  key: string
  kind: string
  icon: string
  text: string
  direction?: string
  /** 来源标记：'expectation' = 期待账本衍生件 */
  origin?: string
  /** 功能槽位（2026-08-29 槽位重构）：landing / toward_beat / echo / ambient */
  source?: string
  /** 出处短语（后端按注入素材拼装，≤16 字：「接着刚才那句往下写」等） */
  note?: string
}

/** Canon 感知提示（canon_watch 组件产，写中停顿心跳返回） */
export interface CanonHint {
  /** 感知类型：appearance 角色出场 / callback 伏笔回收时机 / leak private 泄露 / style_drift 文风漂移（S4 补全）/ world_inbox 收件箱积压（A5c） */
  kind: 'appearance' | 'callback' | 'leak' | 'contradiction' | 'style_drift' | 'world_inbox'
  /** 实体名（角色名 / 伏笔标签 / Canon 节点 label） */
  node_label: string
  /** 实体类型：character / hook / canon */
  node_type: string
  /** 一句话说明（感知带卡片正文） */
  detail: string
  /** 严重度：error > warning > info（影响排序/着色） */
  severity: string
}

/**
 * 幽灵草稿上屏前快检疑点（P5 C1，后端 ghost_guard 纯算法产；只提示不拦截）。
 * kind：dead_speak=死者开口 / canon_leak=canon 私有标签泄底 / secret_leak=私有设定片段外泄
 * 二期扩（2026-09-02 约束治理二期）：cliche_hit=禁忌面命中 / out_of_scene=人物不在场
 * （live-warn 转正）/ location_jump=地点穿越（shadow 攒数中）/ beat_rush=抢拍
 * （2026-09-03 live 出生即返修资格，返修条明细随车）/ quality_breaker=
 * 自动修正熔断降级指示（返修环连续失败，转为仅提示）。
 */
export interface GhostWarning {
  kind: 'dead_speak' | 'canon_leak' | 'secret_leak' | 'cliche_hit' | 'out_of_scene' | 'location_jump' | 'beat_rush' | 'quality_breaker'
  /** 命中触发词（实体名/别名/私有标签/秘密关键短语） */
  span_text: string
  /** 人话说明（含「可忽略」口径——回忆/闪回属合法用法） */
  message: string
}

export interface HeartbeatResult {
  dock_parts: DockPart[]
  /** 句子级闸门触发（半句悬停，挂件应静默）——前端据此清舱收卡 */
  dock_muted?: boolean
  direction_cards: DirectionCard[]
  intent_source: string
  intent_arc: string
  intent_confidence: number
  fact_count: number
  total_words: number
  activated: string[]
  signals: string[]
  /** Canon 感知提示（canon_watch 产；写中右缘感知带数据源） */
  canon_hints?: CanonHint[]
  /** 世界数据版本（路由层附带；写作页切片保鲜比对，查询失败无此字段） */
  world_version?: { events: number; updated_at: string | null } | null
  /** 章级谋篇进度（P1.4 M2；无脉络/无锚点无此字段——进度行静默缺席） */
  spine_progress?: SpineProgress | null
  /**
   * 最近一次失败的辅助组件（P3-1：组件名 → 秒级时间戳 + 一行错误摘要；
   * 成功即清。空/缺省 = 一切正常——副驾「AI 视角」调试区消费，空则整块不渲染
   */
  last_component_errors?: Record<string, { ts: number; error: string }>
}

/** 章级谋篇进度（纯算法判定：pending→hit 只前进；dropped 作者手点） */
export interface SpineProgress {
  intent: string
  anchors: { id: string; text: string; status: 'pending' | 'hit' | 'dropped' }[]
  pending_count: number
  hint: string
}

/** 走向卡（层 3 推测首 beat）：Ctrl+Space 走向卡舱的数据源 */
export interface DirectionCard {
  event: string
  anchors: string[]
  /** 服务于的谋篇锚点 id（P1.4 M2 走向卡挂脉络；命中本章非 dropped 锚点才透传） */
  serves_anchor?: string
  /** 作者声明岔路（P1.4 M3：临近岔路锚点的走向选项——硬提示，朱色视觉权重） */
  is_branch?: boolean
  /** 地图相遇来源（W5 桥：让某组相遇发生/错开的走向——世界沙盘喂的卡） */
  from_encounter?: boolean
}

export interface SettleResult {
  settled: boolean
  fact_count: number
  emergent_facts?: any
  conflicts?: any[]
  /** 本次沉淀抽取产生的候选事件条数（A5d toast 直达收件箱用；0/缺省=无候选） */
  candidates_created?: number
  /** P3-4：世界发现被跳过的原因（无实体/正文不足等；有候选产出时缺省不出） */
  scout_skipped?: { code: string; reason: string }
}

/** 自动阅读（阶段 B）结果——ran=false 时带 skipped 原因 */
export interface AutoReadResult {
  ran: boolean
  created?: number
  suppressed_muted?: number
  skipped?: { code: string; reason: string }
  budget?: { daily_used: number; daily_cap: number }
}

/** 自动阅读（阶段 A）实体候选结果——只产草稿不落库 */
export interface ReadEntitiesResult {
  ran: boolean
  entities?: Array<{ name: string; type?: string; description?: string }>
  locations?: Array<{ name: string; description?: string }>
  skipped?: { code: string; reason: string }
}

/** 完稿后处理审计报告 */
export interface FinishReport {
  finished: boolean
  reason?: string
  /** 全书 pending 候选计数（A5c① book 级；0/缺省=无积压，报告区静默缺席） */
  candidates_pending?: number
  /** 记忆倒灌：完稿时本章写入向量记忆的块数（后端路由写在响应顶层，与 candidates_pending 同层；勿放回嵌套 report） */
  memory_indexed?: number
  /** P3-4：世界发现被跳过的原因（无实体/正文不足等；有候选产出时缺省不出） */
  scout_skipped?: { code: string; reason: string }
  /**
   * 疑似 AI 味变体（D 包语义扫描：embedding 余弦相似度抓「换字逃逸」改写变体，
   * 只提示作者裁决不改正文；未配置 embedding / 零命中时后端不设此键）
   */
  semantic_hits?: Array<{
    /** 正文段（命中嫌疑最强的原文片段） */
    segment: string
    /** 疑似变体的禁忌 pattern */
    pattern: string
    /** 余弦相似度（0-1，保留 3 位） */
    similarity: number
    severity: string
    alternative?: string | null
    source: string
  }>
  report?: {
    chapter_id?: string
    word_count?: number
    sentence_defects?: any[]
    /** 谋篇附注（P1.4 §3.5：未兑现 pending 锚点，仅提示不阻塞） */
    spine_note?: string
    coverage?: {
      checked: boolean
      hit_count?: number
      miss_count?: number
      misses?: string[]
      reason?: string
    }
    canon_check?: {
      private_breaches?: string[]
      public_fact_count?: number
    }
    critique?: {
      issues?: Array<{ severity: string; category: string; detail: string }>
      verdict?: string
    }
  }
}

export interface WorldModelSnapshot {
  facts: any[]
  intent: any
  projections: any[]
  intent_version: number
  fact_count: number
  total_words: number
  /** P3-1：最近一次失败的辅助组件（与心跳响应同源；空/缺省 = 一切正常） */
  last_component_errors?: Record<string, { ts: number; error: string }>
}

// ===== 章级谋篇·软脉络（P1.4，docs/chapter-planning-spine.md）=====
export interface SpineAnchor {
  id: string
  text: string
  source: 'author' | 'ai'
  status: 'pending' | 'hit' | 'dropped'
  /** 作者声明岔路（M3：该锚点处有剧情分岔，2-3 个走向短语） */
  branch?: { options: string[] }
}
export interface ChapterSpine {
  intent?: { text: string; source: 'author' | 'ai' }
  anchors?: SpineAnchor[]
}
export interface SpineSuggestion {
  intent: string
  anchors: string[]
}

// ===== AI 所见预览（P5 B2，docs/foundation-hardening.md §2.1）=====
/** 预览块（与 stitch-ghost 真实注入同源——后端与 stitch 路由共用同一装配函数） */
export interface ContextPreviewBlock {
  /** style_positive|author_samples|proper_nouns|canon|secrets|echoes|spatial（注入序；secrets=A1 私有设定） */
  key: 'style_positive' | 'author_samples' | 'proper_nouns' | 'canon' | 'secrets' | 'echoes' | 'spatial'
  title: string
  /** 块渲染文本；空串 = 该块未配置（「未配置」灰字提示） */
  content: string
  chars: number
  /** 来源徽标（世界实体/章级绑定/真相层/私有设定/文风卡/文风样本库/记忆召回/世界比例尺） */
  source: string
  /** 该块配额（A3b 预算器 BLOCK_CHAR_BUDGETS 常量上限；0=该次渲染未过预算器） */
  budget_chars: number
  /** 被裁信息（预算超支时该块条目收缩的人话说明；未触发裁剪时无此字段） */
  trimmed?: string | null
}

export interface ContextPreview {
  mode: string
  blocks: ContextPreviewBlock[]
  total_chars: number
  world_time: number
  /** 叙事时间解析来源：本章锚/前序锚/事件最大时刻/空世界 */
  world_time_source: 'chapter_anchor' | 'prev_anchor' | 'max_event' | 'zero'
  /** 世界页桥接是否生效（实体/关系来自活舆图而非旧章级绑定表） */
  world_sourced: boolean
}

// ============================================================
// adaptiveApi
// ============================================================

export const adaptiveApi = {
  /** 作者状态心跳 → 触发调度器 → 返回快照 + 挂件 */
  heartbeat: async (
    chapterId: string,
    data: {
      word_count: number
      segment_count: number
      paused_ms: number
      cursor_at_paragraph_end: boolean
      has_outline: boolean
      outline_text: string
      recent_text: string
      /** Tab 显式点名要零件（豁免句子级闸门） */
      summoned?: boolean
      /** 强制刷新挂件：跳过 dock 缓存命中强行重算并覆盖（Tab 重复生成——舱在屏再按=换一批） */
      force_refresh?: boolean
      /** 光标后文锚（中插桥接/FIM）：骨架跳写、光标停在上下文之间时的后文 1-2 句 */
      suffix_anchor?: string
      /** 细纲胶囊速记原文（意图反推素材——胶囊会话级不落库，经心跳供给） */
      outline_notes?: string[]
      /** 打算一句话原文（打算变更即时感知：舱换向 + 层 2 转化触发） */
      spine_intent?: string
    },
  ): Promise<HeartbeatResult> => {
    return requestJson(`/chapters/${chapterId}/adaptive/heartbeat`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 段落锁死 → 层1追加 + 沉淀倒灌 */
  settle: async (
    chapterId: string,
    data: { text: string; entities?: any[]; commit?: boolean },
  ): Promise<SettleResult> => {
    return requestJson(`/chapters/${chapterId}/adaptive/settle`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 完稿 → 后处理审计（同步等待返回报告） */
  finish: async (chapterId: string): Promise<FinishReport> => {
    return requestJson(`/chapters/${chapterId}/adaptive/finish`, {
      method: 'POST',
    })
  },

  /** 系统自己去读·阶段 B：读一章 → 世界事件候选进收件箱（幂等，随处发枪安全） */
  autoRead: async (chapterId: string): Promise<AutoReadResult> => {
    return requestJson(`/chapters/${chapterId}/adaptive/auto-read`, {
      method: 'POST',
    })
  },

  /** 系统自己去读·阶段 A：从一章抽实体/地点候选（只产草稿不落库）。
   *  force=true 豁免幂等闸（通读向导刷新丢 review 后的重新认人补救；预算闸不豁免） */
  readEntities: async (chapterId: string, force = false): Promise<ReadEntitiesResult> => {
    return requestJson(`/chapters/${chapterId}/adaptive/read-entities`, {
      method: 'POST',
      body: JSON.stringify({ force }),
    })
  },

  /** 拉取世界模型快照（恢复/调试用） */
  model: async (chapterId: string): Promise<WorldModelSnapshot> => {
    return requestJson(`/chapters/${chapterId}/adaptive/model`)
  },

  /**
   * AI 此刻所见预览（P5 B2）：stitch-ghost 将注入的全部上下文块，按注入序返回。
   * 只跑装配不调 LLM 文本生成；mode 五档（stitch/continue/burst/outline/open）缺省 continue。
   */
  contextPreview: async (
    chapterId: string,
    mode: 'stitch' | 'continue' | 'burst' | 'outline' | 'open' = 'continue',
  ): Promise<ContextPreview> => {
    return requestJson(`/chapters/${chapterId}/adaptive/context-preview?mode=${mode}`)
  },

  /** 协作交互埋点（P0-3 本地 jsonl 零上报；词表见后端端点 6 注释） */
  logCollabEvent: async (
    chapterId: string,
    kind: string,
    detail?: Record<string, unknown>,
  ): Promise<void> => {
    await requestJson(`/chapters/${chapterId}/adaptive/event`, {
      method: 'POST',
      body: JSON.stringify({ kind, detail: detail || {} }),
    })
  },

  /** 残句定点修复（P1.2 作者裁决式：只产修复句，正文不动；每轮审计上限 5 处） */
  fixSentence: async (
    chapterId: string,
    payload: { sentence: string; defect_type?: string; description?: string },
  ): Promise<{ fixed: string | null; reason: string }> => {
    return requestJson(`/chapters/${chapterId}/adaptive/fix-sentence`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  /** 软脉络读取（null = 本章无脉络，一切 UI 静默缺席） */
  getSpine: async (chapterId: string): Promise<{ spine: ChapterSpine | null }> => {
    return requestJson(`/chapters/${chapterId}/adaptive/spine`)
  },

  /** 软脉络部分合并保存（只改传了的字段；锚点硬上限 5） */
  patchSpine: async (
    chapterId: string,
    patch: { intent?: { text: string; source: 'author' | 'ai' } | null; anchors?: SpineAnchor[] | null },
  ): Promise<{ spine: ChapterSpine | null }> => {
    return requestJson(`/chapters/${chapterId}/adaptive/spine`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  /** AI 谋篇建议（不落库——建议只在作者收下/编辑后才入库） */
  spineSuggest: async (chapterId: string): Promise<SpineSuggestion> => {
    return requestJson(`/chapters/${chapterId}/adaptive/spine-suggest`, { method: 'POST' })
  },

  /** 协作交互汇总（个人镜子：走向卡/幽灵稿/胶囊采纳率） */
  collabEventsSummary: async (chapterId: string): Promise<{
    total: number
    by_kind: Record<string, number>
    card_burst_rate: number | null
    ghost_adopt_rate: number | null
    capsule_expand_count: number
    quick_note_commit: number
    /** A5b 批量裁决累计采纳条数（undone 批不计入） */
    batch_accept_count: number
  }> => {
    return requestJson(`/chapters/${chapterId}/adaptive/events/summary`)
  },

  /**
   * 清空本书协作埋点（测试用；他书事件保留）。连带效应：本书「学着闭嘴」
   * 的拒收史派生源一并清零，静音集合回到无史状态。
   */
  clearCollabEvents: async (bookId: string): Promise<{ book_id: string; deleted: number }> => {
    return requestJson(`/books/${bookId}/adaptive/collab-events`, { method: 'DELETE' })
  },

  /** 微缝合幽灵草稿（SSE 打字机推流）；mode='burst' 为段落级连写、'outline' 为细纲扩写 */
  stitchGhost: async (
    chapterId: string,
    params: {
      fragment: string
      rolling_prefix?: string
      mode?: 'stitch' | 'continue' | 'burst' | 'open' | 'outline'
      picked_parts?: string[]
      /** 点选零件的功能槽位（与 picked_parts 同序：landing/toward_beat/echo/ambient）——双轨契约选档信号 */
      picked_slots?: string[]
      target_chars?: number
      chapter_intent?: string
      adopted_direction?: string
    /** 中插桥接后文锚（FIM）：注入双端边界与桥接铁律，产出走接缝归一 */
    suffix_anchor?: string
      beat_guidance?: string
      /** outline 模式：细纲之后的已写正文开头（双端缝合用） */
      after_text?: string
      /** outline 模式：胶囊挂的谋篇锚点文本（M3 三锚定；空=双端锚定不变） */
      serves_anchor?: string
    },
    callbacks: {
      onStart?: (mode: string) => void
      onChunk?: (delta: string) => void
      onDone?: (result: {
        text: string
        word_count: number
        warnings?: GhostWarning[]
        /** 呈现平面洗层（三平面分权 P1，2026-08-29）：命中清单 + 原稿快照（有替换时非空） */
        wash?: { hits: Array<{ pattern: string; span: string; replaced: boolean; alternative: string }>; original_text: string }
        /** P5 回流对齐令牌 + 本发注入样本 id（采纳/蒸发埋点回传用） */
        ghost_token?: string
        sample_ids?: string[]
        /**
         * 二期返修环结果：自动修正了 N 处硬伤（action=repaired/excised；空=未触发）。
         * items=逐条人话明细（09-08 作者可见性，与 warnings 同形；点开看修了什么。
         * 旧后端帧缺省——缺省时返修条退化为纯计数，不出明细入口）
         */
        repaired?: { count: number; kinds: string[]; action: string; items?: GhostWarning[] }
        /** 拒稿熔断开启（自动修正连续失败，本次起转为仅提示） */
        breaker_open?: boolean
      }) => void
      onError?: (error: string) => void
      /**
       * 二期质量拒稿（code=quality_reject）：返修/切除均失败，幽灵不上屏。
       * 载荷带被拒原稿与疑点清单——逃生舱「仍以疑点提示上屏」由调用方裁决。
       */
      onReject?: (payload: { message: string; mode: string; text: string; warnings: GhostWarning[] }) => void
    },
    signal?: AbortSignal,
  ) => {
    // 终帧哨兵：GHOST_DONE/GHOST_REJECT/ERROR 任一到达即置位（EOF 兜底判定用）
    let receivedTerminal = false
    streamSse(`/chapters/${chapterId}/adaptive/stitch-ghost`, params, {
      onPayload: payload => {
        if (!payload || !payload.event) return
        if (payload.event === 'GHOST_START') {
          callbacks.onStart?.(payload.mode || 'stitch')
        } else if (payload.event === 'GHOST_CHUNK') {
          callbacks.onChunk?.(payload.delta || '')
        } else if (payload.event === 'GHOST_DONE') {
          // C1 快检疑点 / P1 洗层 / P5 回流令牌随 DONE 帧到达（向后兼容增量字段）
          receivedTerminal = true
          const warnings: GhostWarning[] = Array.isArray(payload.warnings) ? payload.warnings : []
          callbacks.onDone?.({
            text: payload.text || '',
            word_count: payload.word_count || 0,
            warnings,
            wash: payload.wash || undefined,
            ghost_token: payload.ghost_token || undefined,
            sample_ids: Array.isArray(payload.sample_ids) ? payload.sample_ids : undefined,
            repaired: payload.repaired && payload.repaired.count ? payload.repaired : undefined,
            breaker_open: payload.breaker_open || undefined,
          })
          return true
        } else if (payload.event === 'GHOST_REJECT') {
          // 二期质量拒稿：自动修正未通过，幽灵不上屏（逃生舱载荷随车）
          receivedTerminal = true
          const rejectWarnings: GhostWarning[] = Array.isArray(payload.warnings) ? payload.warnings : []
          callbacks.onReject?.({
            message: payload.message || '这次没能写出合格的续写',
            mode: payload.mode || 'stitch',
            text: payload.text || '',
            warnings: rejectWarnings,
          })
          return true
        } else if (payload.event === 'ERROR' || payload.event === 'GHOST_ERROR') {
          receivedTerminal = true
          callbacks.onError?.(payload.error || '续写失败')
          return true
        }
      },
      onError: message => callbacks.onError?.(message),
      // EOF 未收到终帧兜底（2026-09-04 审计修复）：流正常关闭但 GHOST_DONE/
      // REJECT/ERROR 均未到达（后端输出中断/代理掐断）——此前 onDone/onError
      // 都不触发，authorLane 卡 ghostStitching、幽灵态悬挂。与 diagnose/analyze
      // 的既有兜底同型。
      onDone: () => {
        if (!receivedTerminal) callbacks.onError?.('续写流中断（未收到完成帧），请重试')
      },
    }, signal).catch(err => { if (!signal?.aborted) callbacks.onError?.(err.message) })
  },
}
