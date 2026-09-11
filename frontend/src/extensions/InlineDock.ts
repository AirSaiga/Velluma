import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import type { Editor } from '@tiptap/core'
import { h, render, watch } from 'vue'
import InlineDockHost from '../features/generation/presentation/InlineDockHost.vue'
import {
  sparkDockVisible,
  attachedParts,
  sparkAnchorPos,
} from '../features/generation/composables/useSparkDock'
import { ghostActive } from '../features/generation/composables/useGhostDraft'

/**
 * 行间推挤式卡片舱（2026-09-09 布局重构：浮层覆盖 → Inline Block Expansion）。
 *
 * 旧 CursorLayer 绝对定位浮窗在 FIM 中插写时遮正文后文 5~6 行；现把 SparkDock
 * 挂进 ProseMirror WidgetDecoration——装饰锚在光标段后，展开时下方正文被
 * 平滑推开（~200px），光标行/卡舱/后文同屏，0% 遮挡。
 *
 * 选型（红队裁定）：
 * - WidgetDecoration 而非 NodeView——后者进文档 schema/undo 历史/落库序列化；
 *   Decoration 纯视图层，文档模型与 getHTML 零触碰，位置随事务自动映射。
 * - widget DOM contenteditable=false + stopEvent→true + ignoreSelection——
 *   舱内点击/输入框键入 PM 概不接手，选区状态安居 PM state。
 * - 关沿不在此摘装饰：Host 高度收折 transitionend 后调
 *   requestInlineDockRemoval()（带重开竞态守卫 + 安全超时），杜绝
 *   「舱没了、幽灵还没来」的空窗帧（舱在光标行下方，收折只上拉下方
 *   内容——幽灵流入的光标行从头到尾不动）。
 */

export const inlineDockKey = new PluginKey('vellumaInlineDock')

/**
 * 事件桥：widget 内 SparkDock → WorkspaceView。
 * 旧链路经 CursorLayer 的 props/emits 逐层透传；widget 是 PM 管的 DOM 岛，
 * 改为容器 onMounted 时 bindInlineDockBridge 绑定（模块单例，随装随换书重绑）。
 */
export const inlineDockBridge: {
  customStitch: (text: string) => void
  guestRegister: (name: string) => void
} = {
  customStitch: () => {},
  guestRegister: () => {},
}

export function bindInlineDockBridge(b: Partial<typeof inlineDockBridge>): void {
  if (b.customStitch) inlineDockBridge.customStitch = b.customStitch
  if (b.guestRegister) inlineDockBridge.guestRegister = b.guestRegister
}

interface DockPluginState {
  anchor: number | null
  deco: DecorationSet
}

let _widgetSeq = 0

function _makeWidget(anchor: number): Decoration {
  const dom = document.createElement('div')
  dom.className = 'velluma-inline-dock-widget'
  dom.setAttribute('contenteditable', 'false')
  // Vue 岛：render 挂载/destroy 卸载（Host 组件只依赖模块级单例状态，
  // 不用 app 级 provide/inject，无 appContext 也能完整工作）
  render(h(InlineDockHost), dom)
  return Decoration.widget(anchor, dom, {
    side: 1,
    key: `velluma-inline-dock-${_widgetSeq++}`,
    stopEvent: () => true,
    ignoreSelection: true,
    destroy: (el: HTMLElement) => render(null, el),
  })
}

function _setAnchor(editor: Editor, anchor: number | null): void {
  const tr = editor.view.state.tr.setMeta(inlineDockKey, { anchor })
  editor.view.dispatch(tr)
}

/** Host 收折动画完成后请求摘除装饰；重开竞态守卫：快速 Esc→Tab 时新锚已立，旧动画收尾不误伤 */
export function requestInlineDockRemoval(editor: Editor): void {
  const open = (sparkDockVisible.value || attachedParts.value.length > 0) && !ghostActive.value
  if (open) return
  _setAnchor(editor, null)
}

export const InlineDock = Extension.create({
  name: 'vellumaInlineDock',

  addProseMirrorPlugins() {
    const editor = this.editor
    // 舱可见性（模块单例 ref）→ 装饰锚。开沿/换锚沿直接立锚；关沿交给
    // Host 的收折动画收尾。热重载/编辑器销毁时停 watch。
    const stopWatch = watch(
      [sparkDockVisible, attachedParts, ghostActive, sparkAnchorPos],
      () => {
        const open =
          (sparkDockVisible.value || attachedParts.value.length > 0) && !ghostActive.value
        if (open && sparkAnchorPos.value != null) {
          _setAnchor(editor, sparkAnchorPos.value)
        }
      },
    )
    ;(this as unknown as { _stopInlineDockWatch?: () => void })._stopInlineDockWatch = stopWatch

    return [
      new Plugin({
        key: inlineDockKey,
        state: {
          init: (): DockPluginState => ({ anchor: null, deco: DecorationSet.empty }),
          apply(tr, value: DockPluginState): DockPluginState {
            const meta = tr.getMeta(inlineDockKey) as { anchor: number | null } | undefined
            if (meta && 'anchor' in meta) {
              return meta.anchor == null
                ? { anchor: null, deco: DecorationSet.empty }
                : {
                    anchor: meta.anchor,
                    deco: DecorationSet.create(tr.doc, [_makeWidget(meta.anchor)]),
                  }
            }
            if (value.anchor == null || !tr.docChanged) return value
            // 打字只做位置映射：widget 对象原样保留（Vue 岛/动画状态不重建）；
            // assoc=-1 → 插入正好落在锚点（段末边界）时贴住原段
            return {
              anchor: tr.mapping.map(value.anchor, -1),
              deco: value.deco.map(tr.mapping, tr.doc),
            }
          },
        },
        props: {
          decorations(state) {
            return inlineDockKey.getState(state)?.deco ?? DecorationSet.empty
          },
        },
      }),
    ]
  },

  onDestroy() {
    ;(this as unknown as { _stopInlineDockWatch?: () => void })._stopInlineDockWatch?.()
  },
})

export default InlineDock
