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
  importance_level: number
}

export interface Chapter {
  id: string
  chapter_number: number
  title: string
  outline_text: string
  content_text: string
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
