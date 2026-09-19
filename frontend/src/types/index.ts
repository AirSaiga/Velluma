export interface Book {
  id: string
  title: string
  genre: string
  core_motifs_taboos?: string
}

export interface ApiConfig {
  api_key: string
  base_url: string
  model: string
  reasoning_model?: string  // 高逻辑模型（用于 Scene Intent / Subconscious / Review）
  creative_model?: string   // 高创意模型（用于 Prose Draft），如未设置则使用 model
  proxy_enabled?: boolean
  proxy_url?: string
  // 默认模型的推理模式配置
  reasoning_enabled?: boolean
  reasoning_effort?: ReasoningEffortLevel
  reasoning_exclude?: boolean
  // 逻辑推理模型的推理模式配置
  reasoning_model_reasoning_enabled?: boolean
  reasoning_model_reasoning_effort?: ReasoningEffortLevel
  reasoning_model_reasoning_exclude?: boolean
  // 创意生成模型的推理模式配置
  creative_model_reasoning_enabled?: boolean
  creative_model_reasoning_effort?: ReasoningEffortLevel
  creative_model_reasoning_exclude?: boolean
}

export type PacingStyle = 'slow_burn' | 'balanced' | 'fast_paced'

// 推理模式努力程度类型
export type ReasoningEffortLevel = 'xhigh' | 'high' | 'medium' | 'low' | 'minimal' | 'none'

// 推理模式配置接口
export interface ReasoningConfig {
  enabled: boolean
  effort: ReasoningEffortLevel
  max_tokens?: number
  exclude: boolean
}

export interface Character {
  id: string
  name: string
  static_prompt: string
  dynamic_state: string
  dynamic_state_history?: Array<{ state: string; updated_at: string }>
  importance_level: number
}

export interface Chapter {
  id: string
  chapter_number: number
  chapter_name?: string
  title: string
  outline_text: string
  content_text: string
  draft_text?: string
  summary?: string
  tension_level: number
  pacing_style: PacingStyle
  status: string
  character_ids?: string[]
  chapter_assets_schema?: string
  creative_intents?: string[]
  chapter_goals?: string[]
  selected_plan_type?: string
  user_overrides?: Record<string, any>
  word_count?: number
  author_intent?: string
}

export interface LegacyAsset {
  id: string
  name: string
  category: string
  description: string
  visual_features?: string
  functional_features?: string
  origin_story?: string
  current_owner_id?: string
  status?: string
}

export interface ChapterAssetLink {
  chapter_id: string
  asset_id: string
}

export interface Relationship {
  id?: string
  source_char_id: string
  target_char_id: string
  relation_type: string
  affinity_score: number
  interaction_prompt: string
}

export interface GenerateChapterRequest {
  chapter_id: string
  api_key: string
  base_url?: string
  model?: string
  reasoning_model?: string  // 高逻辑模型
  creative_model?: string   // 高创意模型
}

export interface GenerateChapterAgenticPayload extends GenerateChapterRequest {
  // === 编辑模式（已统一为意图驱动）===
  editor_mode?: 'intent'
  
  // === V3.8 高层语义参数（基础模式推荐）===
  memory_strategy?: 'recent_only' | 'balanced_reference' | 'deep_dive'
  creativity_level?: 'strict_prompt' | 'balanced_creation' | 'wild_imagination'
  refinement_depth?: 'light' | 'standard' | 'deep'
  
  word_count: number
  max_iterations: number
  rag_top_k: number
  rag_alpha: number
  rag_beta: number
  rag_gamma: number
  rag_lambda: number
  fast_mode?: boolean
  skip_minor_refine?: boolean
  author_intent?: string
  tension_level?: number
  pacing_style?: PacingStyle
  force_parallel_prose?: boolean
  // 单模型模式的推理模式配置
  reasoning_config?: ReasoningConfig
  // 双模型模式的推理模式配置
  reasoning_model_reasoning_config?: ReasoningConfig
  creative_model_reasoning_config?: ReasoningConfig
}

export interface GenerateChapterAgenticPayloadWithBeats extends GenerateChapterAgenticPayload {
  beats: ConfirmedStoryBeat[]
}

export interface ConfirmedStoryBeat {
  position: number
  beat_id?: string
  summary: string
  location?: string
  pov_character?: string
  pov_mode?: 'single' | 'ensemble' | 'omniscient'  // V3.6
  pov_characters?: string[]                          // V3.6
  pov_aperture?: string                              // V3.5
  action_summary?: string
  worldbuilding_instruction?: string
  entry_state?: string
  exit_state?: string
  red_lines: string[]
  word_count_target: number
  target_words: number
  hook_ids: string[]
}

// Beat 编辑器状态（UI 层扩展字段）
export interface BeatEditorItem extends ConfirmedStoryBeat {
  openingState: string
  stoppingState: string
  forbiddenEventsText: string
}

export interface GenerateChapterAgenticPreviewResponse {
  beats: ConfirmedStoryBeat[]
}

export interface GenerateChapterAgenticWithBeatsPayload extends GenerateChapterAgenticPayload {
  beats: ConfirmedStoryBeat[]
}

export interface AgenticFormState {
  word_count: number
  memory_span: 'recent_only' | 'balanced_reference' | 'deep_dive'
  creativity_level: 'strict_prompt' | 'balanced_creation' | 'wild_imagination'
  progression_preference: 'focus_scene_action' | 'push_mainline'
  refinement_depth: 'light' | 'standard' | 'deep'
  rag_lambda: number
  author_intent: string
  tension_level: number
  pacing_style: PacingStyle
  force_parallel_prose: boolean
}

export type InspirationIdeaType = 'plot_twist' | 'key_conflict' | 'new_hook' | 'smooth_narrative'

export interface InspirationIdea {
  idea_type: InspirationIdeaType
  title: string
  description: string
  impact: string
}

export interface InspirationResponse {
  inspirations: InspirationIdea[]
}

export interface InspirationRequest {
  book_id: string
  chapter_id: string
  current_context_snippet: string
  active_character_ids: string[]
  temperature: number
  api_key: string
  base_url?: string
  model?: string
}

// === 大纲澄清相关相关类型 (Clarification Agent) ===

// 新增：澄清问题选项接口
export interface ClarificationOption {
  label: string
  value: string
}

// 新增：结构化澄清问题接口
export interface ClarifyingQuestion {
  id: string
  question: string
  options: ClarificationOption[]
}

export interface ClarifyOutlineRequest {
  chapter_id: string
  ambiguous_text: string
  api_key: string
  base_url?: string
  model?: string
  author_intent?: string
  user_instruction?: string  // 新增：用户针对系统澄清问题的补充说明或回答
  previous_issues?: string[] // 新增：上一轮识别出的问题列表
}

export interface ClarifyOutlineResponse {
  is_ambiguous: boolean              // 是否存在歧义或信息缺失
  identified_issues?: string[]       // 识别到的具体问题列表
  clarifying_questions?: ClarifyingQuestion[] // 新增：需要用户回答的结构化澄清问题
  clarification_suggestions?: string[] // 提供给用户的澄清建议/问题
  refined_text?: string              // AI修正后的大纲文本
  error?: string                     // 解析异常时的错误信息
}

// === 双轨生成架构相关类型 (Dual Track Architecture V3.5) ===

export interface DualTrackGenerationRequest extends GenerateChapterAgenticPayload {
  beats?: ConfirmedStoryBeat[]
  enable_sketch_track?: boolean
  enable_adversarial_alignment?: boolean
  use_sketch_for_refinement?: boolean
  alignment_threshold?: number
  sketch_ratio?: number
  sketch_model?: string
}

export interface BeatDraftResult {
  beat_id: string
  beat_index: number
  scene_intent: Record<string, any>
  subconscious_thought: string
  draft_chunk: string
  prompts?: any[]
  mcts_rollout?: any[]
}

export interface SketchSegment {
  beat_index: number
  beat_id?: string
  text: string
  transition_to_next?: string
}

export interface SketchEmotionPoint {
  beat_index?: number
  emotion?: string
  intensity?: number
  [key: string]: any
}

export interface SketchResult {
  sketch_text: string
  word_count: number
  prompts?: any[]
  // CP4.2：速写骨架分段（蓝图 §4.5），供 SketchEditorPanel 展示 + 编辑
  segments?: SketchSegment[]
  emotion_arc?: SketchEmotionPoint[]
}

// CP4.2：SKETCH_DONE SSE 事件的 segments payload（与 SketchSegment 对齐，但字段都可选）
export interface SketchDonePayload {
  segments_count: number
  segments?: SketchSegment[]
  emotion_arc?: SketchEmotionPoint[]
  sketch_text_preview?: string
}

export interface AdjustmentPlan {
  alignment_score: number
  analysis_prompts?: any[]
  [key: string]: any
}

export interface DualTrackResult {
  final_text: string
  beat_drafts: BeatDraftResult[]
  stitched_draft: string
  sketch_result?: SketchResult
  adjustment_plan?: AdjustmentPlan
  stats: Record<string, any>
  debug_info: Record<string, any>
}

// === 人物提取相关类型 (Character Extraction V3.7) ===

export interface ExtractedCharacterInfo {
  name: string
  is_new: boolean
  existing_id?: string
  description: string
  role_type: 'protagonist' | 'antagonist' | 'supporting' | 'minor'
  aliases: string[]
  first_appearance: boolean
  importance_level: number
}

export interface InferredRelationshipInfo {
  source_name: string
  target_name: string
  relation_type: string
  description: string
  affinity_score: number
  is_new: boolean
}

export interface CharacterExtractionSummary {
  extracted_characters: ExtractedCharacterInfo[]
  new_characters_count: number
  existing_characters_count: number
  inferred_relationships: InferredRelationshipInfo[]
  chapter_entity_links: string[]
}

export interface PublishChapterResponse {
  chapter_id: string
  status: string
  summary?: string
  character_updates: Array<{
    character_id: string
    character_name: string
    old_state: string
    new_state: string
  }>
  world_snapshot?: Record<string, any>
  character_extraction?: CharacterExtractionSummary
}

// ============================================================
// CP2.5 新增类型 - Phase 1 合并闸门 + 文风体系
// ============================================================

// ---- 章节卡（ChapterCard，合并闸门核心）----

export interface MustHitEvent {
  event: string
  emotion?: string | null
  must: boolean
}

export interface InvolvedCharacter {
  name: string
  entry?: string | null
  exit?: string | null
}

export interface ForeshadowOp {
  action: 'plant' | 'advance' | 'payoff' | 'drop'
  ledger_id?: string | null
  note: string
}

export interface ChapterCardContinuity {
  from_chapter?: number | null
  time_gap?: string | null
  location?: string | null
}

export interface ChapterCard {
  id?: string
  book_id?: string
  chapter_id?: string | null
  chapter_number: number
  purpose?: string | null
  must_hit_events: MustHitEvent[]
  involved_characters: InvolvedCharacter[]
  foreshadow_ops: ForeshadowOp[]
  continuity: ChapterCardContinuity
  word_target: number
  pacing: 'fast' | 'medium' | 'slow'
  tension: number
  style_override_id?: string | null
  status?: 'draft' | 'confirmed' | 'generating' | 'done'
}

// ---- Plan 联合预览/确认 ----

export interface PlanPreviewResponse {
  chapter_card: ChapterCard
  beats: ConfirmedStoryBeat[]
  degraded?: { reason: string; action: string; detail?: string } | null
  debug_prompt?: any
}

export interface PlanConfirmRequest {
  chapter_card_fields: Partial<ChapterCard>
  beats: ConfirmedStoryBeat[]
  word_count?: number
}

// ---- 文风卡（StyleCard）----

export interface NegativeItem {
  word: string
  alternative?: string | null
  /** 禁令档位：warning=提醒（默认，仅提示与统计） / blocker=硬禁（检查命中即判不通过）；缺省按 warning 兜底 */
  severity?: 'warning' | 'blocker'
}

export interface StyleCard {
  id?: string
  book_id?: string
  chapter_id?: string | null
  positive_profile: Record<string, string>
  negative_list: NegativeItem[]
  dialogue_ratio_target?: number | null
  paragraph_rhythm?: string | null
  notes?: string | null
  /** 意图旋钮档位（S4）：{rhythm|register|density|warmth: 1-5}，缺键=自动档 */
  style_knobs?: Record<string, number> | null
  /** 画像字段锁：被锁字段不被「从样本提炼」覆盖 */
  locked_keys?: string[] | null
  created_at?: string
  updated_at?: string
}

export type StyleKnobKey = 'rhythm' | 'register' | 'density' | 'warmth'

export interface StyleExtractResponse {
  positive_profile: Record<string, string>
  negative_list: NegativeItem[]
  dialogue_ratio_target?: number | null
  paragraph_rhythm?: string | null
  degraded?: { reason: string; action: string; detail?: string } | null
}

// ---- 作者样本（AuthorSample）----

export type AuthorSampleSceneType = 'dialogue' | 'action' | 'lyrical' | 'suspense' | 'general'

export interface AuthorSample {
  id: string
  book_id: string
  chapter_id?: string | null
  scene_type: AuthorSampleSceneType
  content: string
  word_count: number
  source: string
  /** 时期标记：recent=近期（进语料聚合）/early=早期（仅存档） */
  era?: 'recent' | 'early' | string
  /** 收藏（检索兜底流优先） */
  favorite?: boolean
  created_at: string
}


// ---- 文风指纹（S1 测量层，docs/style-module-redesign.md §7.2）----

/** 单文本指纹（结构与 backend/services/style/fingerprint.py 对齐） */
export interface TextFingerprint {
  char_count: number
  word_count: number
  sentence_count: number
  sentence_len_mean: number
  sentence_len_median: number
  /** 句长起伏（变异系数 CV，与审计 RhythmAuditor 同口径；< 0.35 偏单调） */
  sentence_len_cv: number
  /** ≤5 字碎句占比（句数 <10 时为 0） */
  short_sentence_ratio: number
  sentence_len_histogram: {
    lte5: number
    '6_10': number
    '11_20': number
    '21_30': number
    gt30: number
  }
  /** 对话占比（与审计 DialogueAuditor 同口径） */
  dialogue_ratio: number
  paragraph_count: number
  paragraph_len_mean: number
  short_paragraph_ratio: number
  punctuation: {
    dash_per_1k: number
    ellipsis_per_1k: number
    exclaim_per_1k: number
    question_per_1k: number
  }
  /** 修辞密度（light 模式 / 章指纹为 null） */
  rhetoric: {
    metaphor_per_500: number
    micro_action_per_500: number
    transition_per_500: number
    ai_taste_score: number
  } | null
  /** 词汇丰富度（<30 词时 ttr/mattr 为 null；旧指纹无此键） */
  lexical?: {
    token_count: number
    ttr: number | null
    mattr: number | null
  } | null
  /** 词级重复密度（<50 词时 ratio 为 null；参考性指标不进门禁；旧指纹无此键） */
  repetition?: {
    bigram_repeat_ratio: number | null
    repeated_bigrams_top: [string, number][]
  } | null
}

export interface SampleFingerprint {
  sample_id: string
  fingerprint: TextFingerprint
}

export interface ChapterFingerprint {
  chapter_id: string
  chapter_number: number
  title: string | null
  fingerprint: TextFingerprint
}

export interface StyleFingerprint {
  corpus: TextFingerprint
  samples: SampleFingerprint[]
  sample_count: number
  /** 样本 <3 条，指纹仅供参考（诚实红线） */
  low_confidence: boolean
  chapters?: ChapterFingerprint[] | null
  reference: {
    cv_healthy: [number, number]
    dialogue_target: number | null
  }
  /** 台账化：各负面清单词在近 10 章正文的命中次数（含 0） */
  negative_hit_counts?: Record<string, number>
}

// ---- 文风收件箱 / 禁词扫描（S3 交互环）----

export type StyleInboxKind = 'negative_candidate' | 'sample_candidate'

export interface StyleInboxItem {
  id: string
  book_id: string
  kind: StyleInboxKind
  payload: {
    word?: string
    alternative?: string | null
    source_text?: string
    content?: string
    scene_type?: string
    [key: string]: unknown
  }
  status: 'pending' | 'confirmed' | 'dismissed'
  source: string
  created_at: string
}

export interface StyleScanOccurrence {
  offset: number
  context: string
}

export interface StyleScanHit {
  word: string
  alternative: string
  severity: string
  count: number
  occurrences: StyleScanOccurrence[]
}

export interface StyleScanResult {
  word_count: number
  hit_words: number
  total_hits: number
  hits: StyleScanHit[]
}

// ---- 写作规矩（质感契约按书覆盖，2026-09 白描封杀令收编批）----

export interface TextureRuleItem {
  key: string
  title: string
  enabled: boolean
}

export interface TextureContractItem {
  key: string
  title: string
  modes: string[]
  body: string
  is_default: boolean
  default_body: string
  /** 定制方式：''=默认 / rules=规矩开关 / body=整文编辑 */
  customized_via: string
  rules: TextureRuleItem[]
}

export interface TextureContractsResponse {
  contracts: TextureContractItem[]
}

// ---- 成本报告（CostReport，Phase 0 观测层）----

export interface CostReportStage {
  stage: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  thinking_tokens: number
  latency_ms_avg: number
  degraded_count: number
  model_slots: string[]
}

export interface CostReportTotals {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  thinking_tokens: number
  total_tokens: number
  degraded_count: number
}

export interface CostReport {
  chapter_id: string
  run_id: string
  stages: CostReportStage[]
  totals: CostReportTotals
}

// ---- 质量报告（QualityReport，Phase 2 CP3.1a 双层审计）----

export interface FindingItem {
  severity: 'blocker' | 'warning' | 'info'
  category: 'timeline' | 'characterization' | 'worldview' | 'fact' | 'style'
  quote?: string | null
  offset?: [number, number] | null
  beat_id?: number | null
  detail: string
  suggestion?: string | null
}

export interface MetricsBlock {
  cliche_hits_per_1k?: number
  sentence_len_cv?: number
  dialogue_ratio?: number
  word_achieve_rate?: number
  red_line_violations?: number
  [key: string]: number | undefined
}

export interface DegradedInfo {
  reason: string
  action: string
  detail?: string
}

export interface QualityReport {
  id: string
  chapter_id: string
  run_id?: string | null
  metrics: MetricsBlock
  findings: FindingItem[]
  degraded?: DegradedInfo | null
  verdict?: 'pass' | 'pass_with_fixes' | 'fail' | 'unaudited' | null
  created_at: string
}


