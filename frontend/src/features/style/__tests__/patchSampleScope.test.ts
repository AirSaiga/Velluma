/**
 * 转移操作（转入笔迹库 / 收回本书）API 层单测：patchSample 的 scope 键透传
 * + 外来样本收回独立端点 recallSample（mock transport）。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('../../../services/api/transport', () => ({
  requestJson: vi.fn().mockResolvedValue({}),
  requestRaw: vi.fn().mockResolvedValue({
    json: () => Promise.resolve({ id: 's1', scope: 'global' }),
  }),
}))

import { requestJson, requestRaw } from '../../../services/api/transport'
import { styleApi } from '../../../services/api/domain'

const mockedRaw = vi.mocked(requestRaw)
const mockedJson = vi.mocked(requestJson)

describe('styleApi.patchSample 转移操作', () => {
  beforeEach(() => {
    mockedRaw.mockClear()
  })

  it('scope=global 透传为 PATCH body 的 scope 键（转入笔迹库）', async () => {
    const res = await styleApi.patchSample('b1', 's1', { scope: 'global' })
    expect(mockedRaw).toHaveBeenCalledWith(
      '/books/b1/samples/s1',
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ scope: 'global' }) }),
    )
    expect(res.scope).toBe('global')
  })

  it('scope=book 透传（收回本书），且不夹带其他键', async () => {
    await styleApi.patchSample('b1', 's1', { scope: 'book' })
    const [, init] = mockedRaw.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toEqual({ scope: 'book' })
  })
})

describe('styleApi.recallSample 外来样本收回', () => {
  beforeEach(() => {
    mockedJson.mockClear()
  })

  it('POST /books/{id}/samples/{sid}/recall，无 body（外来行走独立端点，PATCH 书域闸会恒 404）', async () => {
    await styleApi.recallSample('b1', 's1')
    expect(mockedJson).toHaveBeenCalledWith('/books/b1/samples/s1/recall', { method: 'POST' })
  })
})
