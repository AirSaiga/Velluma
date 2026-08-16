import Mention from '@tiptap/extension-mention'
import { PluginKey } from '@tiptap/pm/state'
import type { Editor } from '@tiptap/vue-3'
import { characterApi } from '../services/api/domain'
import { assetApi } from '../services/api/domain/asset.api'
import { worldApi } from '../services/api/domain/world.api'

/**
 * NLE-ADF 2.0 行内极速 Hook（三级输入体系第二级）。
 *
 * 画布打字时 `@` 唤起角色建议、`#` 唤起资产建议：
 *   - 选中已有实体 → 插入行内提及胶囊
 *   - 无匹配时 → 「创建」项：直接在世界页建实体（M4 后世界页为设定唯一写主）
 *
 * M4 变更：建议列表与创建均 world 优先（世界页无实体时回退旧表）；
 * 「静默绑定到本章」已退役——本章在场由世界页事件按叙事时刻推演
 * （docs/world-unified-settings.md §8），不再写 chapter_entities/chapter_assets。
 *
 * 自包含在通用组件层（components/ 不受 features 分层约束）；
 * bookId/chapterId 以 getter 注入（编辑器实例一次创建，章节切换不换扩展）。
 */

interface MentionEntityItem {
  id: string
  name: string
  /** true = 「创建」项（query 无精确匹配时追加） */
  create?: boolean
}

interface EntityMentionContext {
  getBookId: () => string | null
  getChapterId: () => string | number | null
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
        btn.textContent = item.create ? `＋ 创建「${item.name}」` : item.name
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

/** 构建提及建议列表：世界页实体优先（含别名匹配），无世界数据回退旧表 */
export function buildEntityMentionExtensions(ctx: EntityMentionContext) {
  const makeItems =
    (kind: 'character' | 'asset') =>
    async ({ query }: { query: string }): Promise<MentionEntityItem[]> => {
      const bookId = ctx.getBookId()
      if (!bookId) return []
      const q = (query || '').trim()
      try {
        let list: MentionEntityItem[] = []
        const worldEnts = await worldApi
          .listEntities(bookId, kind)
          .catch(() => null as any[] | null)
        if (worldEnts && worldEnts.length) {
          list = worldEnts
            .filter(
              (e: any) =>
                e?.name &&
                (!q ||
                  String(e.name).includes(q) ||
                  (e.aliases || []).some((a: any) => String(a).includes(q))),
            )
            .slice(0, 5)
            .map((e: any) => ({ id: String(e.id), name: String(e.name) }))
        } else {
          const legacy: any[] =
            kind === 'character' ? await characterApi.getAll(bookId) : await assetApi.getAll(bookId)
          list = (legacy || [])
            .filter((c: any) => c?.name && (!q || String(c.name).includes(q)))
            .slice(0, 5)
            .map((c: any) => ({ id: String(c.id), name: String(c.name) }))
        }
        if (q && !list.some((c) => c.name === q)) {
          list.push({ id: '__create__', name: q, create: true })
        }
        return list
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
        // 世界页为设定唯一写主：@/# 创建的实体直接落 world_entities（失败静默告警）
        void (async () => {
          const bookId = ctx.getBookId()
          if (!bookId) return
          try {
            const created: any = await worldApi.createEntity(bookId, {
              entity_type: kind,
              name: item.name,
            })
            if (created?.id) {
              insertMention(String(created.id), item.name)
            }
          } catch (e) {
            console.warn(`[entity-mention] 创建${kind === 'character' ? '角色' : '资产'}失败`, e)
          }
        })()
        return
      }
      insertMention(item.id, item.name)
    }

  const charMention = Mention.extend({ name: 'charMention' }).configure({
    HTMLAttributes: { class: 'entity-mention entity-mention--character' },
    renderText: ({ node }) => node.attrs.label ?? '',
    suggestion: {
      char: '@',
      pluginKey: new PluginKey('charMention'),
      // 中文正文无词间空格：默认要求 @ 前是空格/行首会让建议在汉字后永不触发
      // （测试实测 0 次激活）。null = 任意前缀均可（小说场景无邮箱类干扰，可接受）
      allowedPrefixes: null,
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
      allowedPrefixes: null,
      items: makeItems('asset'),
      command: makeCommand('asset', 'assetMention'),
      render: _makePopupRenderer(),
    },
  })

  return [charMention, assetMention]
}
