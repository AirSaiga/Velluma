export interface Book {
  id: string
  title: string
  genre: string
  global_sys_prompt: string
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
