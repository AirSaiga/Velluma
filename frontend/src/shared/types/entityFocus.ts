/**
 * 编辑器实体焦点事件载荷（RichTextEditor → WorkspaceView 贯通链的契约）。
 *
 * W2 情境浮卡的数据入口：source=mention（点击 @/# 提及，带实体 id 直取）与
 * source=selection（选中文本 1-12 字，按名字/别名解析）；source=cursor（光标
 * 周边词，供高亮类消费方）不触发浮卡，并用于关闭在屏浮卡。
 */
export interface EntityFocusPayload {
  keyword: string
  source: 'cursor' | 'selection' | 'mention'
  /** 视口坐标（浮卡锚点；cursor 来源可空） */
  x?: number
  y?: number
  /** 提及节点携带的世界实体 id（legacy 旧表 id 后端解析不中 → 浮卡静默缺席） */
  entityId?: string | null
  entityKind?: 'character' | 'asset' | null
}
