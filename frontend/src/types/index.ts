export interface Book {
  id: string
  title: string
  genre: string
  global_sys_prompt: string
}

export type PacingStyle = 'slow_burn' | 'balanced' | 'fast_paced'

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
}

export interface ConfirmedStoryBeat {
  position: number
  beat_id?: string
  summary: string
  location?: string
  pov_character?: string
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
  author_intent?: string
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
