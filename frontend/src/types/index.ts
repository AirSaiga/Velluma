export interface Book {
  id: string
  title: string
  genre: string
  global_sys_prompt: string
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
}

export interface ConfirmedStoryBeat {
  position: number
  beat_id?: string
  summary: string
  location?: string
  pov_character?: string
  action_summary?: string
  worldbuilding_instruction?: string
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
  max_iterations: number
  rag_top_k: number
  rag_alpha: number
  rag_beta: number
  rag_gamma: number
  rag_lambda: number
}
