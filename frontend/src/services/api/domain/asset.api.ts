import { requestJson } from '../transport'
import type { Asset, AssetCreate, AssetUpdate, ChapterAsset } from '../../../shared/types'

export const assetApi = {
  getAll: (bookId: string) =>
    requestJson<Asset[]>(`/books/${bookId}/assets`),
    
  get: (id: string) =>
    requestJson<Asset>(`/assets/${id}`),
    
  create: (bookId: string, data: AssetCreate) =>
    requestJson<Asset>(`/books/${bookId}/assets`, {
      method: 'POST',
      body: JSON.stringify(data)
    }),
    
  update: (id: string, data: AssetUpdate) =>
    requestJson<Asset>(`/assets/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),
    
  delete: (id: string) =>
    requestJson(`/assets/${id}`, { method: 'DELETE' }),

  getChapterAssets: (chapterId: string) =>
    requestJson<ChapterAsset[]>(`/chapters/${chapterId}/assets`),

  updateChapterAssets: (chapterId: string, assetIds: string[]) =>
    requestJson<ChapterAsset[]>(`/chapters/${chapterId}/assets?asset_ids=${assetIds.join('&asset_ids=')}`, {
      method: 'PUT'
    })
}
