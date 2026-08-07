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

  updateChapterAssets: (chapterId: string, assetIds: string[]) => {
    // 空列表时不带 query，避免后端把 ?asset_ids= 解析成 [''] 触发 UUID 校验失败
    const qs = assetIds.length ? `?asset_ids=${assetIds.join('&asset_ids=')}` : ''
    return requestJson<ChapterAsset[]>(`/chapters/${chapterId}/assets${qs}`, {
      method: 'PUT'
    })
  }
}
