import Mention from '@tiptap/extension-mention'
import { PluginKey } from '@tiptap/pm/state'
import type { Editor } from '@tiptap/vue-3'
import { characterApi, chapterApi } from '../services/api/domain'
import { assetApi } from '../services/api/domain/asset.api'

/**
 * NLE-ADF 2.0 行内极速 Hook（三级输入体系第二级）。
 *
 * 画布打字时 `@` 唤起角色建议、`#` 唤起资产建议：
 *   - 选中已有实体 → 插入行内提及节点（带底色的小胶囊），并静默绑定到本章
 *     （chapter entities / chapter assets），设定库零打扰更新
 *   - 无匹配时 → 「创建并绑定」项：先建实体再绑定（设定的逆向生长入口之一）
 *
 * 自包含在通用组件层（components/ 不受 features 分层约束，RichTextEditor
 * 已有 bookApi 直调先例）；bookId/chapterId 以 getter 注入（编辑器实例
 * 一次创建，章节切换不换扩展，闭包内必须读最新值）。
 */

interface MentionEntityItem {
  id: string
  name: string
  /** true = 「创建并绑定」项（query 无精确匹配时追加） */
  create?: boolean
}

interface EntityMentionContext {
  getBookId: () => string | null
  getChapterId: () => string | number | null
}

/** 把实体静默绑定到本章（已绑定则跳过；失败仅告警不打断写作） */
async function _bindEntityToChapter(
  ctx: EntityMentionContext,
  kind: 'character' | 'asset',
  entityId: string,
): Promise<void> {
  const chapterId = ctx.getChapterId()
  if (!chapterId) return
  try {
    if (kind === 'character') {
      const cur = await chapterApi.getEntities(String(chapterId))
      const ids: string[] = Array.isArray(cur)
        ? cur.map((x: any) => (typeof x === 'string' ? x : x?.id)).filter(Boolean)
        : []
      if (!ids.includes(entityId)) {
        await chapterApi.updateEntities(String(chapterId), [...ids, entityId])
      }
    } else {
      const cur = await assetApi.getChapterAssets(String(chapterId))
      const ids: string[] = (cur || [])
        .map((a: any) => a?.id ?? a?.asset_id)
        .filter(Boolean)
      if (!ids.includes(entityId)) {
        await assetApi.updateChapterAssets(String(chapterId), [...ids, entityId])
      }
    }
  } catch (e) {
    console.warn(`[entity-mention] 绑定${kind === 'character' ? '角色' : '资产'}失败`, e)
  }
}

/** 提及建议弹层：手写 DOM 渲染（不引 tippy，减少依赖）。
 *  方向键/回车/Esc 由 suggestion 插件的 onKeyDown 接管。 */
function _makePopupRenderer() {
  return () => {
    let root: HTMLDivElement | null = null
    let items: MentionEntityItem[] = []
    let selected = 0
    let command: ((item: MentionEntityItem) => void) | null = null

    const renderItems = () => {
      if (!root) return
      root.innerHTML = ''
      if (!items.length) {
        const empty = document.createElement('div')
        empty.className = 'mention-item mention-item--empty'
        empty.textContent = '无匹配'
        root.appendChild(empty)
        return
      }
      items.forEach((item, i) => {
        const btn = document.createElement('button')
        btn.className = 'mention-item' + (i === selected ? ' mention-item--active' : '')
        btn.textContent = item.create ? `＋ 创建并绑定「${item.name}」` : item.name
        btn.onmousedown = (e) => {
          e.preventDefault()  // 防编辑器失焦吞掉点击
          command?.(item)
        }
        root!.appendChild(btn)
      })
    }

    const place = (clientRect?: (() => DOMRect | null) | null) => {
      const rect = clientRect?.()
      if (root && rect) {
        root.style.top = `${rect.bottom + 6}px`
        root.style.left = `${Math.max(16, rect.left)}px`
      }
    }

    return {
      onStart: (p: any) => {
        items = p.items || []
        command = p.command
        selected = 0
        root = document.createElement('div')
        root.className = 'mention-popup'
        place(p.clientRect)
        renderItems()
        document.body.appendChild(root)
      },
      onUpdate: (p: any) => {
        items = p.items || []
        command = p.command
        selected = 0
        if (!root) {
          root = document.createElement('div')
          root.className = 'mention-popup'
          document.body.appendChild(root)
        }
        place(p.clientRect)
        renderItems()
      },
      onKeyDown: ({ event }: any) => {
        if (!root) return false
        if (event.key === 'ArrowDown') {
          selected = Math.min(selected + 1, items.length - 1)
          renderItems()
          return true
        }
        if (event.key === 'ArrowUp') {
          selected = Math.max(selected - 1, 0)
          renderItems()
          return true
        }
        if (event.key === 'Enter') {
          const item = items[selected]
          if (item && command) command(item)
          return true
        }
        if (event.key === 'Escape') {
          root.remove()
          root = null
          return true
        }
        return false
      },
      onExit: () => {
        root?.remove()
        root = null
      },
    }
  }
}

/** 构建 @ 角色 / # 资产两个提及扩展（RichTextEditor extensions 数组挂载） */
export function buildEntityMentionExtensions(ctx: EntityMentionContext) {
  const makeItems =
    (kind: 'character' | 'asset') =>
    async ({ query }: { query: string }): Promise<MentionEntityItem[]> => {
      const bookId = ctx.getBookId()
      if (!bookId) return []
      const q = (query || '').trim()
      try {
        const list: any[] =
          kind === 'character' ? await characterApi.getAll(bookId) : await assetApi.getAll(bookId)
        const filtered: MentionEntityItem[] = (list || [])
          .filter((c: any) => c?.name && (!q || String(c.name).includes(q)))
          .slice(0, 5)
          .map((c: any) => ({ id: String(c.id), name: String(c.name) }))
        if (q && !filtered.some((c) => c.name === q)) {
          filtered.push({ id: '__create__', name: q, create: true })
        }
        return filtered
      } catch {
        return []
      }
    }

  const makeCommand =
    (kind: 'character' | 'asset', nodeName: string) =>
    ({ editor, range, props: item }: { editor: Editor; range: any; props: MentionEntityItem }) => {
      const insertMention = (id: string, label: string) => {
        editor
          .chain()
          .focus()
          .insertContentAt(range, [
            { type: nodeName, attrs: { id, label } },
            { type: 'text', text: ' ' },
          ])
          .run()
      }
      if (item.create) {
        // 先建实体再插入+绑定（异步；失败静默告警不打断写作）
        void (async () => {
          const bookId = ctx.getBookId()
          if (!bookId) return
          try {
            const created: any =
              kind === 'character'
                ? await characterApi.create({ book_id: bookId, name: item.name })
                : await assetApi.create(bookId, { name: item.name })
            const newId = created?.id
            if (newId) {
              insertMention(String(newId), item.name)
              await _bindEntityToChapter(ctx, kind, String(newId))
            }
          } catch (e) {
            console.warn(`[entity-mention] 创建${kind === 'character' ? '角色' : '资产'}失败`, e)
          }
        })()
        return
      }
      insertMention(item.id, item.name)
      void _bindEntityToChapter(ctx, kind, item.id)
    }

  const charMention = Mention.extend({ name: 'charMention' }).configure({
    HTMLAttributes: { class: 'entity-mention entity-mention--character' },
    renderText: ({ node }) => node.attrs.label ?? '',
    suggestion: {
      char: '@',
      pluginKey: new PluginKey('charMention'),
      items: makeItems('character'),
      command: makeCommand('character', 'charMention'),
      render: _makePopupRenderer(),
    },
  })

  const assetMention = Mention.extend({ name: 'assetMention' }).configure({
    HTMLAttributes: { class: 'entity-mention entity-mention--asset' },
    renderText: ({ node }) => node.attrs.label ?? '',
    suggestion: {
      char: '#',
      pluginKey: new PluginKey('assetMention'),
      items: makeItems('asset'),
      command: makeCommand('asset', 'assetMention'),
      render: _makePopupRenderer(),
    },
  })

  return [charMention, assetMention]
}
