export interface Asset {
  id: string
  book_id: string
  name: string
  aliases: string[]
  static_description: string | null
  current_state: string | null
  importance_level: number
  created_at: string
}

export interface AssetCreate {
  name: string
  aliases?: string[]
  static_description?: string | null
  current_state?: string | null
  importance_level?: number
}

export interface AssetUpdate {
  name?: string
  aliases?: string[]
  static_description?: string | null
  current_state?: string | null
  importance_level?: number
}

export interface ChapterAsset {
  id: string
  chapter_id: string
  asset_id: string
  asset: Asset
}
