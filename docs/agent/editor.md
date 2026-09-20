# 编辑器本体优化（领域档案）

> 2026-09-19 自 `docs/agent/nle-adf.md` 拆出（编辑器 TipTap 扩展与生成引擎零耦合，独立成档）；写作台/生成侧契约见 `docs/agent/nle-adf.md`。

编辑器自有的输入规范化、粘贴净化、查找替换与排版契约。全部为纯前端 TipTap 扩展层，不依赖任何后端端点。

## 中文标点规范化（`extensions/chineseTypography.ts`）

- 判据铁律=**只在中日韩上下文动手**（`3.5`/`1,000`/`Mr. Smith`/`Hello... world` 一律原样）。
- 输入侧 InputRules 打字即正：`...`→`……`、`--`→`——`、半角 `,.?!:;()` 前一位是中文时转全角、直双引号按段内左右引号数判开闭；正则一律**零宽后顾**（range 只覆盖标点本身，不重建前一个汉字的文本节点）。
- 批处理侧 `normalizeDocumentPunctuation`（⋯ 菜单「整理标点」，零 LLM/零 API Key，单事务一次 Ctrl+Z 反悔，**保留命中处行内格式**）。
- 两消费面共用逐字符单遍扫描的 `punctuationEdits`（**按位置升序返回是契约**——引号规则会先记右引号的账，不排会让拼接错位）。

## 粘贴净化 + 清除外来样式（`extensions/foreignStyles.ts`）

- `transformPastedHTML` 剥长相类样式 color/background/font-family/font-size（粗斜下划线等排版意图保留）。
- ⋯ 菜单「清除外来样式」治存量——**带预检**（区间内真有无外来标记）决定提示语；整篇清理靠 selectAll 后**必须还原原选区**（否则作者回正文一打字替换整章）。

## 查找替换

- `extensions/editorFind.ts`（插件：搜索态 + Decoration 纯视图命中高亮，未搜索零成本短路）+ `composables/useEditorFind.ts`（状态机）+ `presentation/EditorFindBar.vue`（纸面右上浮出单行条，Esc 走全局 Esc 栈不自行处理）。
- 块内扫描不跨段、原子节点占位挡住、跨文本节点命中位置映射走共享 `extensions/blockTextMap.ts`（与标点归一同一底座）。
- 替换逐条独立事务、全部替换单事务；跳转只移选区不抢焦点（**查找条开着时屏蔽选区浮窗**）；替换走 JSON 内容/裸 `tr.insertText`（字符串会被当 HTML 解析）。
- **关条焦点用 `ed.view.focus()` 而非 `commands.focus()`**（后者把 view.focus() 推迟进 rAF，窗口不可见时 rAF 被节流→焦点停在 body）。

## 排版

- `RichTextEditor.vue` 的 scoped `:deep(.ProseMirror)` 不重复声明 font-family/size/line-height——排版唯一权威= `--editor-*` token。
- `--editor-font-family` 栈底补 `SimSun`（栈里一个中文衬线都命中不到时，`“”…` 会被 Georgia 先抓走致字与标点对不齐）。

## 入口与对拍

⋯ 章节动作菜单「查找替换（Ctrl+F）/整理标点/清除外来样式」+ 快捷键速查表补 Ctrl+F。对拍 `extensions/__tests__/{chineseTypography,editorFind,foreignStyles}.test.ts`（34 项）。
