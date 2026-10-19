import { streamSse } from '../stream'
import { requestJson, requestRaw } from '../transport'

export const bookApi = {
  getAll: () => requestJson('/books'),
  create: (data: any) => requestJson('/books', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => requestJson(`/books/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => requestJson(`/books/${id}`, { method: 'DELETE' }),
  getWorldview: (id: string) => requestJson(`/books/${id}/worldview`),
  updateWorldview: (id: string, data: any) =>
    requestJson(`/books/${id}/worldview`, { method: 'PATCH', body: JSON.stringify(data) }),
  getGoldenSnippets: (id: string) => requestJson(`/books/${id}/golden-snippets`),
  /** 书级备份下载（34 表 + 底图 + 台账，单 JSON 文件）；返回 Blob 供 a[download] 落盘 */
  backup: async (id: string): Promise<Blob> => {
    const res = await requestRaw(`/books/${id}/backup`)
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '备份失败' }))
      throw new Error(err.detail || '备份失败')
    }
    return res.blob()
  },
  /** 从备份文件还原一本书（原 ID 直复；书架已有同 ID 书后端 409） */
  restoreBackup: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return requestJson('/books/restore', { method: 'POST', body: form })
  },
  // 双写收敛（任务包 B）：updateGoldenSnippets / GET+PUT style-blacklist 通道已删——
  // 黄金片段只写文风样本库（styleApi.createSample），负面清单唯一入口是 style-card。
}

export const characterApi = {
  // 旧表写路由已删（2026-09-04 死代码清理：旧表冻结、唯一编辑源在世界页）；
  // 仅保留读回退（entityMention / useAppStore 兜底用）
  getAll: (bookId: string) => {
    const url = bookId ? `/books/${bookId}/characters` : '/characters'
    return requestJson(url)
  },
}

export const chapterApi = {
  getAll: (bookId: string) => {
    const url = bookId ? `/books/${bookId}/chapters` : '/chapters'
    return requestJson(url)
  },
  get: (id: string) => requestJson(`/chapters/${id}`),
  create: (data: any) => requestJson(`/books/${data.book_id}/chapters`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => requestJson(`/chapters/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => requestJson(`/chapters/${id}`, { method: 'DELETE' }),
  getEntities: (chapterId: string) => requestJson(`/chapters/${chapterId}/entities`),
  /** 书级批量：全部章的实体关联 ID 映射（替代逐章 N+1；无关联=空映射） */
  getBookChapterEntityIds: (bookId: string) => requestJson(`/books/${bookId}/chapter-entity-ids`),
  updateEntities: (chapterId: string, entityIds: any) =>
    requestJson(`/chapters/${chapterId}/entities`, { method: 'PUT', body: JSON.stringify(entityIds) }),
  /** NLE-ADF 2.0 深度清脂（Alt+Shift+↓）：LLM 重洗当前段落（AI 味密度超阈值才调 LLM） */
  defatSelection: (data: { text: string; must_keep?: string[]; chapter_id?: string; book_id?: string }) =>
    requestJson('/defat_selection', { method: 'POST', body: JSON.stringify(data) }),
  publish: (chapterId: string, data: any) =>
    requestJson(`/chapters/${chapterId}/publish`, { method: 'PATCH', body: JSON.stringify(data || {}) }),
}

export const relationshipApi = {
  getAll: (bookId: string) => {
    const url = bookId ? `/relationships?book_id=${bookId}` : '/relationships'
    return requestJson(url)
  },
}

export const generateApi = {
  optimizeSelection: async (data: any) => {
    const response = await requestRaw('/optimize_selection', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`优化请求失败: ${response.status} ${response.statusText}`)
    }

    return response.json()
  },

  formatText: async (data: { text: string }) => {
    const response = await requestRaw('/format_text', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`格式整理请求失败: ${response.status} ${response.statusText}`)
    }

    return await response.json()
  },

  generateInspiration: async (data: {
    book_id: string
    chapter_id: string
    chapter_title?: string
    current_context_snippet: string
    active_character_ids: string[]
    author_intent?: string
  }) => {
    const response = await requestRaw('/generate_inspiration', {
      method: 'POST',
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      throw new Error(`点子启发请求失败: ${response.status} ${response.statusText}`)
    }

    return await response.json()
  },
}

// ============================================================
// 模型设置（设置面板）
// ============================================================

/** LLM profile（reasoning / creative / wash），api_key 永远为掩码形式 */
export interface LLMProfileConfig {
  api_key_masked: string
  has_api_key: boolean
  base_url: string
  model: string
  enabled: boolean
  effort: string
  /** 仅 wash 槽返回：是否已配置独立洗涤模型（false = 跟随创意模型） */
  configured?: boolean
}

/** deai 去AI味小模型配置（deai/ 子项目；effective_* = 兜底后的实际生效值） */
export interface DeaiConfig {
  api_key_masked: string
  has_api_key: boolean
  base_url: string
  effective_base_url: string
  model: string
  effective_model: string
  enabled: boolean
  configured: boolean
}

export interface ModelConfig {
  llm: {
    reasoning: LLMProfileConfig
    creative: LLMProfileConfig
    /** UI 已隐藏 wash 槽；GET 仍可能返回，类型层标记为非必需 */
    wash?: LLMProfileConfig
  }
  embedding: {
    api_key_masked: string
    has_api_key: boolean
    /** 自管连接的 Base URL（follow_llm=true 时被忽略，仅作保留值） */
    base_url: string
    model: string
    dimensions: number
    /** true=连接（Key/Base URL）跟随文本模型槽，与文本模型保持一致 */
    follow_llm: boolean
    /** 跟随模式下实际生效的连接预览（creative 优先、缺 Key 回退 reasoning） */
    inherited: {
      source: 'creative' | 'reasoning' | null
      base_url: string
      has_api_key: boolean
    }
  }
  /** 去 AI 味小模型（未配置时后端也返回该节；旧后端可能缺省） */
  deai?: DeaiConfig
  proxy: {
    enabled: boolean
    url: string
  }
}

/** 更新载荷：api_key 留空表示保持不变 */
export interface ModelConfigUpdatePayload {
  reasoning?: Partial<Pick<LLMProfileConfig, 'base_url' | 'model' | 'enabled' | 'effort'>> & { api_key?: string }
  creative?: Partial<Pick<LLMProfileConfig, 'base_url' | 'model' | 'enabled' | 'effort'>> & { api_key?: string }
  wash?: Partial<Pick<LLMProfileConfig, 'base_url' | 'model' | 'enabled' | 'effort'>> & { api_key?: string }
  embedding?: { api_key?: string; base_url?: string; model?: string; dimensions?: number; follow_llm?: boolean }
  deai?: { enabled?: boolean; api_key?: string; model?: string; base_url?: string }
  proxy?: { enabled: boolean; url: string }
}

/** 厂商能力目录条目（GET /system/model-catalog；2026-08-28 五厂商调研） */
export interface VendorCatalogEntry {
  id: string
  label: string
  base_url: string
  docs_url: string
  notes: string[]
  models: { id: string; label: string; note: string }[]
}

export interface ModelCatalog {
  vendors: VendorCatalogEntry[]
}

/** 模型价目（元/百万 token）；cached_input 可缺省=按 input 全价（保守） */
export interface ModelPriceEntryPayload {
  input: number
  cached_input?: number
  output: number
}

export type ModelPriceTable = Record<string, ModelPriceEntryPayload>

/** 模型配置预设条目（GET /system/model-presets；Key 只回掩码） */
export interface ModelPresetItem {
  id: string
  name: string
  /** manual=用户点名保存 / auto=覆盖前自动存档 */
  source: 'manual' | 'auto'
  model: string
  base_url: string
  enabled: boolean
  effort: string
  has_api_key: boolean
  api_key_masked: string
}

/** 预设保存载荷：copy_from_role=以该槽已保存配置为底（含槽内 Key），显式字段覆盖 */
export interface ModelPresetSavePayload {
  name: string
  model?: string
  base_url?: string
  /** 留空=沿用 copy_from_role 槽内已存 Key */
  api_key?: string
  enabled?: boolean
  effort?: string
  copy_from_role?: 'reasoning' | 'creative'
}

export interface ModelPresetList {
  presets: ModelPresetItem[]
}

export const systemApi = {
  /**
   * 获取模型配置（LLM / Embedding / 代理）
   * 后端从 model_config.json 读取，API Key 以掩码返回
   */
  getModelConfig: async (): Promise<ModelConfig> => {
    return requestJson('/system/model-config')
  },

  /**
   * 读模型价目表（成本核算，元/百万 token；空表=全部未计价）
   */
  getModelPrices: async (): Promise<{ prices: ModelPriceTable }> => {
    return requestJson('/system/model-prices')
  },

  /**
   * 整表覆写模型价目并持久化（空对象=清空回到未计价态）；保存后立即生效
   */
  updateModelPrices: async (prices: ModelPriceTable): Promise<{ prices: ModelPriceTable }> => {
    return requestJson('/system/model-prices', {
      method: 'PUT',
      body: JSON.stringify({ prices })
    })
  },

  /**
   * 厂商能力目录：选厂商自动填 base_url + 模型候选 + 能力提示。
   * 静态档案（vendor_profiles.py），失败不阻塞设置面板（回退自由输入）。
   */
  getModelCatalog: async (): Promise<ModelCatalog> => {
    return requestJson('/system/model-catalog')
  },

  /**
   * 读模型配置预设池（快速切换下拉；Key 只回掩码，切换走 applyModelPreset）
   */
  getModelPresets: async (): Promise<ModelPresetList> => {
    return requestJson('/system/model-presets')
  },

  /**
   * 保存/覆盖预设（同名覆盖）。copy_from_role 以该槽已保存配置为底，
   * 表单 Key 框留空也能把槽内 Key 连整套连接存进预设（明文不经前端往返）
   */
  saveModelPreset: async (payload: ModelPresetSavePayload): Promise<ModelPresetList & { overwrote: boolean }> => {
    return requestJson('/system/model-presets', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },

  /**
   * 删预设（幂等），返回最新预设池
   */
  deleteModelPreset: async (id: string): Promise<ModelPresetList> => {
    return requestJson(`/system/model-presets/${id}`, { method: 'DELETE' })
  },

  /**
   * 预设切回：整卡写入指定槽位立即生效；旧值由服务端先行自动存档
   * （auto_captured 回存档名，null=同签名已存档/旧值不完整，无需存）。
   * config 为最新模型配置，按槽就地刷新表单（不牵连另一槽的未保存改动）
   */
  applyModelPreset: async (
    id: string,
    role: 'reasoning' | 'creative'
  ): Promise<ModelPresetList & {
    config: ModelConfig
    applied: { id: string; name: string }
    auto_captured: string | null
  }> => {
    return requestJson(`/system/model-presets/${id}/apply`, {
      method: 'POST',
      body: JSON.stringify({ role })
    })
  },

  /**
   * 保存模型配置（写回 model_config.json）
   * LLM/代理保存后立即生效；embedding 维度变更需重启后端且会重建向量列
   */
  updateModelConfig: async (payload: ModelConfigUpdatePayload): Promise<ModelConfig> => {
    return requestJson('/system/model-config', {
      method: 'PUT',
      body: JSON.stringify(payload)
    })
  },

  /**
   * 测试模型连接（LLM 测已保存配置；embedding 用表单实时值探测，未保存也能测）
   * @param embedding 向量模型表单的当前值（api_key 留空表示沿用已保存 Key）
   * @returns 测试结果
   */
  testModel: async (embedding?: {
    model?: string
    base_url?: string
    dimensions?: number
    follow_llm?: boolean
    api_key?: string
  }): Promise<{
    success: boolean
    message: string
    model_info?: {
      reasoning_model?: string
      creative_model?: string
      reasoning_success?: boolean
      creative_success?: boolean
      embedding_configured?: boolean
      embedding_model?: string
      embedding_success?: boolean
      embedding_dimensions_returned?: number | null
      embedding_dimensions_expected?: number | null
    }
    reasoning_supported?: boolean
    reasoning_message?: string
    response_time_ms?: number
  }> => {
    return requestJson('/system/test-model', {
      method: 'POST',
      body: JSON.stringify(embedding ? { embedding } : {})
    })
  },

  /**
   * deai 去AI味小模型「试一试」（表单实时值探测，未保存也能测）
   * 走后端全链路，含契约§6 事实闸保底——保底回退不算失败（闸门在工作）
   */
  testDeai: async (payload?: {
    text?: string
    model?: string
    api_key?: string
    base_url?: string
  }): Promise<{
    success: boolean
    message: string
    input_text: string
    output_text: string
    applied: boolean
    skipped: boolean
    fallback_reason: string
    warnings: string[]
    model: string
    elapsed_ms: number
  }> => {
    return requestJson('/system/deai/test', {
      method: 'POST',
      body: JSON.stringify(payload ?? {})
    })
  }
}

// ============================================================
// deai 子项目（去AI味小模型）：写作台手动配对收集（docs/deai-integration.md §5a）
// ============================================================

export const deaiApi = {
  /**
   * 存一对训练样本（bad=卡片舱生成原样文本，good=作者改定版）
   * 落本地 data/deai_pairs.jsonl（零上报）；返回 id 供 6 秒撤销胶囊。
   * source（03 下一阶段）：manual_mark=手动两步 / auto_ghost=书签自动捕获 /
   * capsule=细纲扩写采纳（meta.source 分组统计入库质量用）
   */
  savePair: async (payload: {
    bad: string
    good: string
    book_id?: string
    chapter_id?: string
    source?: 'manual_mark' | 'auto_ghost' | 'capsule'
  }): Promise<{ id: string; total: number }> => {
    return requestJson('/deai/pairs', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },

  /** 撤销一对（写作台撤销胶囊） */
  deletePair: async (id: string): Promise<{ deleted: boolean; total: number }> => {
    return requestJson(`/deai/pairs/${id}`, { method: 'DELETE' })
  }
}

// ============================================================
// CP2.5a 新增：合并闸门 / 文风体系 / 成本报告 API
// ============================================================

import type {
  StyleCard,
  StyleExtractResponse,
  AuthorSample,
  AuthorSampleSceneType,
  StyleFingerprint,
  StyleInboxItem,
  StyleInboxKind,
  StyleScanResult,
  TextureContractItem,
  TextureContractsResponse,
  CostReport,
  QualityReport,
} from '../../../types'

/**
 * 文风体系 API（蓝图 §4.4 + §5.1 + §6.2）。
 */
export const styleApi = {
  /** 获取生效的文风卡（章级覆盖优先，回退书级）。 */
  get: async (bookId: string, chapterId?: string): Promise<StyleCard | null> => {
    const query = chapterId ? `?chapter_id=${chapterId}` : ''
    return requestJson(`/books/${bookId}/style-card${query}`)
  },

  /** 创建/更新书级或章级文风卡。 */
  upsert: async (bookId: string, payload: Partial<StyleCard>): Promise<StyleCard> => {
    return requestJson(`/books/${bookId}/style-card`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },

  /** 从作者样本提炼文风画像（Match My Style）。 */
  extract: async (
    bookId: string,
    samples: string[],
    genre?: string,
  ): Promise<StyleExtractResponse> => {
    return requestJson(
      `/books/${bookId}/style-card/extract`,
      {
        method: 'POST',
        body: JSON.stringify({ samples, genre }),
      },
      300000,  // 5 分钟超时
    )
  },

  /** 列出书籍的作者样本。 */
  listSamples: async (
    bookId: string,
    sceneType?: string,
  ): Promise<AuthorSample[]> => {
    const query = sceneType ? `?scene_type=${sceneType}` : ''
    return requestJson(`/books/${bookId}/samples${query}`)
  },

  /** 创建作者样本（保存时自动向量化；scope 默认 book）。 */
  createSample: async (
    bookId: string,
    payload: { content: string; scene_type?: string; chapter_id?: string; source?: string; era?: string; scope?: 'book' | 'global' },
  ): Promise<AuthorSample> => {
    return requestJson(`/books/${bookId}/samples`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  /** 删除作者样本。 */
  deleteSample: async (bookId: string, sampleId: string): Promise<void> => {
    await requestRaw(`/books/${bookId}/samples/${sampleId}`, { method: 'DELETE' })
  },

  /** 样本局部更新：时期/收藏/场景类型/正文/归属（scope=转入笔迹库·收回本书）。 */
  patchSample: async (
    bookId: string,
    sampleId: string,
    patch: { era?: 'recent' | 'early'; favorite?: boolean; scene_type?: AuthorSampleSceneType; content?: string; scope?: 'book' | 'global' },
  ): Promise<AuthorSample> => {
    return requestRaw(`/books/${bookId}/samples/${sampleId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }).then((r: any) => r.json())
  },

  /** 外来样本收回本书：当前书创建 book 作用域副本，原书 global 行不动（409=已收回过）。 */
  recallSample: async (bookId: string, sampleId: string): Promise<AuthorSample> => {
    return requestJson(`/books/${bookId}/samples/${sampleId}/recall`, { method: 'POST' })
  },

  /** 黄金片段（旧表）一键导入文风样本库（按内容去重）。 */
  createSamplesFromGolden: async (bookId: string): Promise<AuthorSample[]> => {
    return requestJson(`/books/${bookId}/samples/from-golden`, { method: 'POST' })
  },

  /** 可逆学习（呈现平面 P1）：作者明示保留被洗词——该禁忌降为提醒档。 */
  washPreferOriginal: async (bookId: string, pattern: string): Promise<void> => {
    await requestRaw(`/books/${bookId}/style/wash-prefer-original`, {
      method: 'POST',
      body: JSON.stringify({ pattern }),
    })
  },

  /** P5 采纳幽灵收编池：作者采纳过的幽灵草稿（文风页「收为样本」用）。 */
  listAdoptedGhosts: async (
    bookId: string,
  ): Promise<Array<{ ts: string; source: string; wash_hits: number; text: string }>> => {
    return requestJson(`/books/${bookId}/style/adopted-ghosts`)
  },

  /** 系统陈词库列表（全局层，负面清单区折叠展示用）。 */
  listSystemCliches: async (): Promise<Array<{ id: string; pattern: string; alternative?: string | null; severity: string }>> => {
    return requestJson('/system/cliches?enabled_only=true')
  },

  /** 系统陈词库本书豁免列表。 */
  getClicheExemptions: async (bookId: string): Promise<string[]> => {
    const data = await requestJson(`/books/${bookId}/cliche-exemptions`)
    return data?.patterns || []
  },

  /** 设置系统陈词库本书豁免（整体覆盖）。 */
  putClicheExemptions: async (bookId: string, patterns: string[]): Promise<void> => {
    await requestJson(`/books/${bookId}/cliche-exemptions`, {
      method: 'PUT',
      body: JSON.stringify({ patterns }),
    })
  },

  /** 写作规矩（质感契约按书覆盖，2026-09 收编批）：本书生效视图。 */
  getTextureContracts: async (bookId: string): Promise<TextureContractsResponse> => {
    return requestJson(`/books/${bookId}/texture-contracts`)
  },

  /** 写作规矩整体覆盖写：{key: {body|disabled_rules}}；空=恢复默认；{}=全部恢复。 */
  putTextureContracts: async (
    bookId: string,
    overrides: Record<string, { body?: string | null; disabled_rules?: string[] }>,
  ): Promise<TextureContractsResponse> => {
    return requestJson(`/books/${bookId}/texture-contracts`, {
      method: 'PUT',
      body: JSON.stringify({ overrides }),
    })
  },

  /** 文风使用埋点（本地 JSONL，fire-and-forget，绝不阻塞业务）。 */
  logStyleEvent: (bookId: string, kind: string, detail?: string): void => {
    requestRaw(`/books/${bookId}/style/events`, {
      method: 'POST',
      body: JSON.stringify({ kind, detail }),
    }).catch(() => {})
  },

  /** 文风指纹：语料聚合 + 逐样本 + 可选章指纹（纯 code 测量，0 LLM）。 */
  getFingerprint: async (
    bookId: string,
    withChapters = false,
    chapterLimit = 50,
  ): Promise<StyleFingerprint> => {
    const query = `?with_chapters=${withChapters}&chapter_limit=${chapterLimit}`
    return requestJson(`/books/${bookId}/style-fingerprint${query}`)
  },

  /** 从已发布章节一键收编作者样本（零状态坡道兜底）；chapter_id=单章收编
   *  （2026-09-14 装填通道：写作台检查分区体检报告末「收本章为范例」一键动作，不限发布状态）。 */
  createSamplesFromChapters: async (
    bookId: string,
    opts?: { chapter_id?: string; max_chapters?: number; excerpt_chars?: number },
  ): Promise<AuthorSample[]> => {
    return requestJson(`/books/${bookId}/samples/from-chapters`, {
      method: 'POST',
      body: JSON.stringify(opts || {}),
    })
  },

  /** 删除章级文风覆盖（本章恢复继承书级）。 */
  deleteChapterOverride: async (bookId: string, chapterId: string): Promise<void> => {
    await requestRaw(`/books/${bookId}/style-card?chapter_id=${chapterId}`, { method: 'DELETE' })
  },

  // ---- 文风收件箱（S3）----

  /** 收件箱待过目候选列表。 */
  listInbox: async (bookId: string): Promise<StyleInboxItem[]> => {
    return requestJson(`/books/${bookId}/style/inbox`)
  },

  /** 投递候选（写作台「这不像我」等入口；候选不直接生效）。 */
  addInboxItem: async (
    bookId: string,
    kind: StyleInboxKind,
    payload: Record<string, unknown>,
    source = 'writing_desk',
  ): Promise<StyleInboxItem> => {
    return requestJson(`/books/${bookId}/style/inbox`, {
      method: 'POST',
      body: JSON.stringify({ kind, payload, source }),
    })
  },

  /** 确认候选（✓）：负面候选入负面清单，样本候选入库。
   *  overrides（Phase 3 可选）：收件箱就地编辑后的词块覆盖——后端 confirm 端点
   *  支持可选 word/alternative 字段，仅带上显式有值的键；不带则维持原候选入清单。 */
  confirmInboxItem: async (
    bookId: string,
    itemId: string,
    overrides?: { word?: string; alternative?: string | null },
  ): Promise<StyleInboxItem> => {
    const body: Record<string, unknown> = {}
    if (overrides?.word) body.word = overrides.word
    if (overrides?.alternative != null) body.alternative = overrides.alternative
    return requestJson(`/books/${bookId}/style/inbox/${itemId}/confirm`, {
      method: 'POST',
      ...(Object.keys(body).length > 0 ? { body: JSON.stringify(body) } : {}),
    })
  },

  /** 忽略候选（✗）。 */
  dismissInboxItem: async (bookId: string, itemId: string): Promise<StyleInboxItem> => {
    return requestJson(`/books/${bookId}/style/inbox/${itemId}/dismiss`, { method: 'POST' })
  },

  /** 禁词扫描（三层合并 → 命中清单；替换由作者逐条确认后应用）。 */
  scanNegative: async (
    bookId: string,
    target: { chapter_id?: string; text?: string },
  ): Promise<StyleScanResult> => {
    return requestJson(`/books/${bookId}/style/scan-negative`, {
      method: 'POST',
      body: JSON.stringify(target),
    })
  },

  /** 试听（试衣间，SSE 打字机）：给定段落 + 文风配置 → 真实注入管线改写。
   *  bare=true = 裸奔基线（验枪靶场栏①：跳过画像与样本，只留系统基座）。 */
  audition: (
    bookId: string,
    data: {
      text: string
      style_override?: Partial<StyleCard> | null
      use_samples?: boolean
      bare?: boolean
      target_chars?: number
      chapter_id?: string
    },
    handlers: { onChunk?: (delta: string) => void; onDone?: (text: string) => void; onError?: (msg: string) => void },
    signal?: AbortSignal,
  ): Promise<void> => {
    return streamSse(`/books/${bookId}/style/audition`, data, {
      onPayload: (payload: any) => {
        if (payload.event === 'AUDITION_CHUNK' && payload.delta) handlers.onChunk?.(payload.delta)
        else if (payload.event === 'AUDITION_DONE' && payload.text) handlers.onDone?.(payload.text)
        return false
      },
      onError: (msg: string) => handlers.onError?.(msg),
    }, signal)
  },
}

/**
 * 成本报告 API（Phase 0 观测层，T1.6）。
 */
export const costReportApi = {
  /** 获取章级成本报告（分阶段 token 计量）。 */
  get: async (chapterId: string, runId?: string): Promise<CostReport> => {
    const query = runId ? `?run_id=${runId}` : ''
    return requestJson(`/chapters/${chapterId}/cost-report${query}`)
  },
}

/**
 * 质量报告 API（Phase 2 CP3.1c 双层审计）。
 */
export const qualityReportApi = {
  /** 获取本章最新质量报告（含 metrics / findings / verdict / degraded）。 */
  get: async (chapterId: string, runId?: string): Promise<QualityReport> => {
    const query = runId ? `?run_id=${runId}` : ''
    return requestJson(`/chapters/${chapterId}/quality-report${query}`)
  },
}

// ============================================================
// 已剥离：detonationApi / unifiedApi
// ============================================================
// V3.0 Detonation 与 V3.1 Unified 引擎后端已整体剥离，
// 端点 GET /detonation-chain 与 POST /generate 均不存在，前端死代码一并删除。

export type Tier = 'auto' | 'climax' | 'turn' | 'progress' | 'transition'

// ============================================================
// V3.2 ADF（Anchor-Driven Flow）引擎 API（adfApi）
// ============================================================
// 端点（前缀 /api/chapters/{chapter_id}）：
// - POST /generate-adf  ADF 生成（参数 tier + target_word_count + max_segments）
//
// SSE v3.2 事件序列（设计文档 §7）：
// - ADF_STAGE / ADF_SPINE_BUILT / ADF_ANCHOR_DESIGNED / TIER_DECIDED /
//   ADF_PROGRESS / ADF_PRECONDITION_LANDED / ADF_AUDIT / ADF_METADATA /
//   DEGRADED / UNIFIED_METRIC / TEXT_CHUNK / COMPLETE / ERROR

export type AdfEngine = 'v3.1' | 'v3.2'

export interface AdfEmotionSample {
  progress: number
  register: string
  energy: number
}

export interface AdfAnchorDesigned {
  climax_intensity: number
  climax_description: string
  setup_point_count: number
  emotion_flow_samples: AdfEmotionSample[]
}

export interface AdfAuditResult {
  verdict: 'pass' | 'needs_refinement' | 'fail' | 'unaudited'
  missing_setup_points: string[]
  emotion_mismatches: string[]
  structure_issues: string[]
  climax_score?: number | null
  fix_targets: string[]
}

// ============================================================
// V4.2 对话式介入点 1：章节规划建议
// ============================================================

export interface PlanSuggestionQuestion {
  id: string
  type: 'confirm' | 'expectation_action' | 'hooks' | 'free_text'
  question: string
  default?: string
  options?: string[]
  option_labels?: Record<string, string>
  expectation_id?: string
  hook_ids?: string[]
}

export interface PlanSuggestionResponse {
  chapter_id: string
  chapter_number: number
  outline: string
  reader_mirror_plan: any | null
  active_expectations: Array<{
    id: string
    type: string
    description: string
    current_tension: number
    recommended_action: string
  }>
  open_hooks: Array<{
    id: string
    label: string
    strength: number
    expected_reveal_chapter: number | null
  }>
  canon_summary_excerpt: string
  suggested_questions: PlanSuggestionQuestion[]
}

// BS-ADF 引擎 API 已随引擎归档整体移除（2026-08-29，backend/_deprecated）
//
// SSE 事件序列（设计文档）：
// - BSADF_STAGE / ADF_STAGE / BEAT_SLOTS_BUILT（Track B 暂停点）/
//   BEAT_RENDER_PROGRESS / BEAT_DOWNGRADED / TEXT_CHUNK / COMPLETE / ERROR

/** 槽位卡：每一段的写作契约（Track B 作者可编辑，DDE-BS 重构后 13 字段瘦身版） */
export interface BeatSlot {
  beat_id: string
  segment_index: number
  beat_type: string
  target_word_count: number
  /** 本段必须发生的剧情转折（物理硬契约） */
  core_plot_event: string
  /** 画面必现硬焦点（物理动作/名词词，coverage 校验） */
  key_anchors: string[]
  /** 锚定本段的一句对白/铭文 */
  text_carrier: string
  /** 本段大纲节拍（UI 只读展示） */
  outline_beat?: string
  /** 作者选定的剧情分支走向（DDE 注入，渲染约束，UI 只读展示） */
  branch_directive?: string
  /** 排他禁忌（DDE 否定约束；内部渲染约束，UI 不展示） */
  negative_bounds?: string[]
  sentence_rhythm: string
  emotion_register: string
  emotion_energy: number
  landed_preconditions: string[]
  shot_type: string
  transition: string
  status: string
  edit_count: number
  render_attempts: number
  edited: boolean
}

// ============================================================
// DDE 章节级剧情分叉（ChapterDecisionSet，新 schema）
// ============================================================

/** DDE 单个剧情分支选项（走向级，非物理动作级） */
export interface BranchOption {
  option_id: string
  /** 走向标签（≤20字），如「忍辱负重并暗中破坏设备」 */
  label: string
  /** 剧情后果说明（只给作者看） */
  plot_impact: string
}

/** DDE 单个剧情分叉节点（挂在某个 beat 上的一道走向选择题） */
export interface StoryBranch {
  beat_id: string
  /** 如「面对工头恶意挑衅，林尘的应对分支」 */
  node_title: string
  /** 2~3 个互斥走向选项 */
  options: BranchOption[]
  /** 默认 option_id（最顺大纲的主路径） */
  default_option: string
  /**
   * 节点来源：dde=LLM 判出的真实岔路（缺省）；loop1_gap=大纲自检缺口提示
   * （单选项提示节点，前端显示补充输入框，仅作者自定义文本才会注入 directive）
   */
  source?: 'dde' | 'loop1_gap'
}

/** 全章剧情分叉决策集（DDE 单次 LLM 调用的产出，节点硬上限 2 个） */
export interface ChapterDecisionSet {
  /** False = 全章无岔路，自动放行（常态） */
  has_story_branch: boolean
  decision_nodes: StoryBranch[]
}

/** 救援标记：审计判核心转折未落地且补写未救回的节拍（路线 C 降级救援） */
export interface RescueNeededItem {
  beat_id: string
  segment_index: number
  outline_beat: string
  core_plot_event: string
  reason: string  // core_plot_event_not_landed
}

/** 渲染进度事件：每个 beat 渲染完成时推送 */
export interface RenderProgress {
  beat_id: string
  segment_index: number
  status: string  // rendering | rendered | degraded
  word_count: number
  reason?: string
  /** 软指标：未出现在正文中的槽位词（方案书对齐——槽位词是扩展种子，
   *  缺失不参与降级判定，仅上报展示） */
  coverage_missing?: string[]
  /** 软指标：末段（结局段）超字数预算豁免截断（结局完整性 > 字数预算） */
  word_overflow?: boolean
}

/** 降级事件：某 beat 多次失败后降级 */
export interface DegradedBeat {
  beat_id: string
  segment_index: number
  reason: string  // ai_smell | coverage_fail | gate_fail | llm_error
  attempts: number
}

/** BS-ADF 生成完成结果 */
export interface BSAdfCompleteResult {
  text: string
  engine: 'bsadf'
  tier: string
  reason?: string
  target_word_count?: number
  segment_count: number
  climax_score: number | null
  audit_verdict: string | null
  generation_run_id: string
  stats: Record<string, any>
  degraded_count: number
  /** Track A 完成时随 COMPLETE 下发的槽位卡（Track B 前端已持有，不重复用） */
  beat_slots?: BeatSlot[]
  /** 救援标记：核心转折未落地的节拍（路线 C 内联救援卡） */
  rescue_needed?: RescueNeededItem[]
  /** 降级节拍清单（步进模式不发 BEAT_DOWNGRADED，这是 done 态降级复查的唯一来源） */
  degraded_beats?: { beat_id: string; segment_index: number; reason: string; attempts?: number }[]
  /** 审校结论（步进后处理 ADF_AUDIT 事件的丢帧兜底） */
  audit?: { verdict: string; missing_setup_points?: any[]; missing_beats?: any[]; climax_score?: number | null }
}


// ============================================================
// 伏笔账本 API（V3.1 F4 新增）
// ============================================================
// 后端 PlotLedger 表的 REST 暴露：GET /api/books/{id}/ledgers（已实现）。
// 保留 404 降级为空数组的容错，防御端点不可用场景。

export interface PlotLedgerEntry {
  id: string
  book_id: string
  chapter_id?: string | null
  ledger_key: string
  hook_id?: string | null
  entry_type: string
  content: string
  status: 'open' | 'closed' | 'dropped'
  created_at_chapter?: number | null
  resolved_in_chapter_id?: string | null
  world_time_planted?: number | null
  world_time_resolved?: number | null
  meta?: Record<string, any>
}

export interface PlotLedgerCreateInput {
  ledger_key: string
  content: string
  hook_id?: string | null
  entry_type?: string
  status?: 'open' | 'closed' | 'dropped'
  created_at_chapter?: number | null
  world_time_planted?: number | null
  world_time_resolved?: number | null
  meta?: Record<string, any>
}

export interface PlotLedgerUpdateInput {
  ledger_key?: string
  content?: string
  hook_id?: string | null
  entry_type?: string
  status?: 'open' | 'closed' | 'dropped'
  created_at_chapter?: number | null
  resolved_in_chapter_id?: string | null
  world_time_planted?: number | null
  world_time_resolved?: number | null
  meta?: Record<string, any>
}

export const plotLedgerApi = {
  /** 列出书籍的全部伏笔。后端 404 时降级为空列表。 */
  listByBook: async (bookId: string): Promise<PlotLedgerEntry[]> => {
    try {
      return await requestJson<PlotLedgerEntry[]>(`/books/${bookId}/ledgers`)
    } catch {
      // 后端 404 时降级为空列表
      return []
    }
  },
  /** 手动创建伏笔。后端要求 body 带 book_id（以路径为准覆盖）。 */
  create: (bookId: string, data: PlotLedgerCreateInput): Promise<PlotLedgerEntry> =>
    requestJson<PlotLedgerEntry>(`/books/${bookId}/ledgers`, {
      method: 'POST',
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),
  /** 更新伏笔（仅传需要变更的字段）。 */
  update: (ledgerId: string, data: PlotLedgerUpdateInput): Promise<PlotLedgerEntry> =>
    requestJson<PlotLedgerEntry>(`/ledgers/${ledgerId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  /** 删除伏笔（物理删除；不再需要建议改 status=dropped）。 */
  remove: (ledgerId: string): Promise<{ ok: boolean }> =>
    requestJson<{ ok: boolean }>(`/ledgers/${ledgerId}`, { method: 'DELETE' }),
}
