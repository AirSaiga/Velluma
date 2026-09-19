import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

/**
 * 幽灵未审标记扩展（03 下一阶段 M3）。
 *
 * 转正后的幽灵段以细虚线 Decoration 标记（= 书签可视化），持续到作者首次
 * 编辑该段（碰过即消）——服务「过会儿来改」场景；标记随事务 map。
 * 书签位置映射（M1）不在本扩展：它由编辑器 onUpdate 事务钩子调
 * useGhostPairTracker.mapTrackedPositions 完成（扩展层不 import feature 层）。
 */
export const ghostTrackKey = new PluginKey('ghostTrack')

interface TrackMeta {
  add?: { from: number; to: number }
}

/** 给指定范围挂未审标记（采纳瞬间调用；与书签同一事务流生效）。 */
export function addUnreviewedMark(editor: any, from: number, to: number): void {
  if (!editor?.view || to <= from) return
  editor.view.dispatch(editor.state.tr.setMeta(ghostTrackKey, { add: { from, to } } as TrackMeta))
}

interface TrackState {
  deco: DecorationSet
  /** decoId → 加标记时的文本（docChanged 后比对，变了=碰过即消） */
  texts: Map<string, string>
}

export const GhostTrack = Extension.create({
  name: 'ghostTrack',

  addProseMirrorPlugins() {
    return [
      new Plugin<TrackState>({
        key: ghostTrackKey,
        state: {
          init(): TrackState {
            return { deco: DecorationSet.empty, texts: new Map() }
          },
          apply(tr, value, _oldState, newState): TrackState {
            let deco = value.deco
            const texts = value.texts
            if (tr.docChanged) {
              deco = deco.map(tr.mapping, tr.doc)
              const kept: any[] = []
              const keptTexts = new Map<string, string>()
              for (const d of deco.find()) {
                const tid = String((d as any).spec?.tid || '')
                const text = newState.doc.textBetween(d.from, d.to, '\n\n')
                if (!tid || texts.get(tid) === text) {
                  kept.push(d)
                  if (tid) keptTexts.set(tid, text)
                }
              }
              deco = DecorationSet.create(newState.doc, kept)
              texts.clear()
              for (const [k, v] of keptTexts) texts.set(k, v)
            }
            const meta = tr.getMeta(ghostTrackKey) as TrackMeta | undefined
            if (meta?.add && meta.add.to > meta.add.from) {
              const tid = `t-${meta.add.from}-${Date.now()}`
              const d = Decoration.inline(meta.add.from, meta.add.to, {
                class: 'ghost-unreviewed',
              }, { tid })
              deco = deco.add(tr.doc, [d as any])
              texts.set(tid, tr.doc.textBetween(meta.add.from, meta.add.to, '\n\n'))
            }
            return { deco, texts }
          },
        },
        props: {
          decorations(state) {
            return ghostTrackKey.getState(state)?.deco || DecorationSet.empty
          },
        },
      }),
    ]
  },
})

export default GhostTrack
