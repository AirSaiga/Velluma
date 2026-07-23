# 前端 UI 适配最新后端生成流 + 剔除无用界面 — 执行文档

> 本文档是**自包含的执行手册**，交给执行 agent 后无需重新调研。所有结论已逐一对照当前工作区代码核实（2026-07-21）。
> 执行时若发现行号与本文档有偏差（代码漂移），以符号名为准全局搜索定位。

---

## 0. 背景事实（执行依据，勿再质疑）

### 0.1 后端生成流真实现状

AGENTS.md 中"双轨是生成主流程"的描述**已过时**。实际并存的链路：

| 链路 | 端点（前缀 `/api/chapters`） | 后端状态 | 前端消费方 |
|---|---|---|---|
| V3.2 ADF（**默认引擎**） | `POST /{id}/generate-adf` | 活跃 | `useGenerationSession.startAdf` |
| V3.1 统一引擎 | `POST /{id}/generate` | 活跃 | `useGenerationSession.startUnified` |
| V4.1 精修 | `/{id}/refinery/diagnose`、`/{id}/refinery/confirm`、`/{id}/reader-feedback` | 活跃 | `useGenerationSession`、`InspectorPanel.vue` |
| ADF 规划建议 | `/{id}/plan-suggestion` | 活跃 | `InspectorPanel.fetchPlanAndShow` |
| V4.0 双轨 | `/{id}/generate-chapter` | **deprecated**，后端可用 | **前端无调用方**；且前端 `streamDualTrackFn` 等 `COMPLETE` 事件、后端双轨发 `DONE`，协议已失配 |
| V3.0 引爆链 | `/{id}/card-v3`、`/detonation-chain*`、`/payload/*`、`/generate-v3` 等 | 部分 deprecated，后端可用 | 唯一消费方 `features/detonation-gate/` 无任何入口（死 feature）；仅 `detonationApi.getChain` 被 `useGenerationSession.ts:487` 复用 |

活跃进度 UI（`useGenerationSession.mapStageToLabel` / `mapAdfStageToLabel` / GenerationStepper / GenerationFlowView / RefineryProgress）与后端 SSE 事件**已匹配良好，不需要重做**。

### 0.2 用户已确认的决策

1. 清理范围：**仅前端**，后端一切不动（含 deprecated 端点与后端死代码）。
2. `features/detonation-gate/`：**整体删除**。
3. 断链功能（主编指导、整章优化）：**删除入口**，不做接线修复。

### 0.3 范围边界（明确不做）

- 不修改 `backend/` 任何文件。
- 不重做生成进度 UI。
- 不处理 `components/` 直接 import services 的架构违规（活跃功能，无收益）。
- 不删除 `extensions/AuditHighlightMark.ts`（审校高亮，独立于 CritiqueMark，有活跃用途）。

---

## 1. 删除清单 A：整个目录/文件删除

删除前对每个符号全局 grep 确认零引用（命令见 §5），确认后删除：

| 对象 | 说明 |
|---|---|
| `frontend/src/features/detonation-gate/` | 整个目录（约 10 文件：DetonationGateContainer、useDetonationGate、ChainTreeView、ChainNodeList、PayloadCandidatePanel、PayloadReviewPanel、DetonationQualityReport、Stat、StepPill、index.ts） |
| `frontend/src/features/character-panel/` | 整个目录（CharacterPanelContainer、CharacterPanelView 等；BibleView 实际用的是 `components/CharacterPanel.vue`） |
| `frontend/src/features/app/containers/useAppState.ts` | 死 composable |
| `frontend/src/features/app/containers/useBookManager.ts` | 死 composable |
| `frontend/src/features/app/containers/useBookNotes.ts` | 死 composable |
| `frontend/src/features/app/containers/useChapterManager.ts` | 死 composable（含唯一 `generateEmbedding` 调用） |
| `frontend/src/features/app/containers/useCharacterManager.ts` | 死 composable |
| `frontend/src/features/app/containers/useEntityFocus.ts` | 死 composable |
| `frontend/src/features/app/containers/useZenMode.ts` | 死 composable |
| `frontend/src/features/app/containers/useCritique.ts` | 死 composable（含唯一 `critiqueChapter` 调用包装） |
| `frontend/src/components/CritiquePanel.vue` | 死组件 |
| `frontend/src/components/DebugPromptWindow.vue` | 死组件 |
| `frontend/src/components/GoldenSnippetsManager.vue` | 死组件（金句快捷添加已内嵌 RichTextEditor） |
| `frontend/src/features/chapter-editor/presentation/SketchEditorPanel.vue` | 死组件 |
| `frontend/src/features/chapter-editor/presentation/ChapterConfigPanel.vue` | 死组件（与 novel-wizard 的同名面板不同，注意别删错） |
| `frontend/src/features/generation/presentation/SetupGraphView.vue` | 仅被 InspectorPanel import 未渲染 |
| `frontend/src/features/generation/presentation/PayloadCompareView.vue` | 仅被 InspectorPanel import 未渲染 |
| `frontend/src/types/intentDriven.ts` | 死类型文件 |
| `frontend/src/composables/useChapterGenerator.ts` | 整文件删除（其唯一活跃用途 optimizeChapter 在 §3 一并删除） |
| `frontend/src/extensions/CritiqueMark.ts` | 随主编指导功能删除（见 §3.1） |

死桶文件（先 grep 确认无 `from '.../features'` 或 `from './index'` 形式引用再删）：
- `frontend/src/features/index.ts`
- `frontend/src/features/app/index.ts`
- `frontend/src/features/app/containers/index.ts`（若清单 A 中 composable 删完后只剩它）

---

## 2. 删除清单 B：API 层死函数（`frontend/src/services/api/domain/index.ts`）

逐个函数删除，删除后立即 grep 函数名确认零调用方：

**后端端点已不存在（必删）：**
- `generateApi.stream`（POST /generate_chapter）
- `generateApi.generateSync`（/generate_chapter_sync）
- `generateApi.streamAgentic`（/generate_chapter_agentic + 双轨分支）
- `intentDrivenApi.generateSync`（/intent-driven/generate）

**后端 deprecated 且前端无调用方（必删）：**
- `generateApi.streamDualTrack`（含内部 `streamDualTrackFn`，约 :183-254）
- `detonationApi.streamGenerate`（/generate-v3）
- `detonationApi` 中仅 detonation-gate 使用的函数：`generateCard`、`createChain`、`updateChain`、`growChain`、`writePayload`、`getPayloadText`、`updatePayloadText`、`getReport`、`getState`（⚠ **保留 `getChain`**：`useGenerationSession.ts:487` 在用；若删完整个 detonationApi 只剩 getChain，保留该对象）

**后端存在但前端零调用方（删除）：**
- `intentDrivenApi` 剩余全组（`getTemplates`、`recommend`）→ 整个对象删除
- `planApi` 全组（`preview`、`confirm`，约 :578-610）→ 整个对象删除
- `generateApi.clarifyOutline`（/clarify-outline）
- `generateApi.critiqueChapter`（/critique_chapter，:436-440）
- `chapterApi.testCharacterExtraction`（/debug/character-extraction）
- `chapterApi.generateEmbedding`（/generate-embedding）
- `qualityReportApi.rerun`（保留 `get`，InsightsView 在用）
- `bookApi.getGoldenSnippets`、`updateGoldenSnippets`、`getStyleBlacklist`、`updateStyleBlacklist`（这两组字段实际经 `bookApi.get`/`bookApi.update` 读写）

**prompt 调试通道（整体删除，domain/index.ts:4-67 区域）：**
- `publishPromptData` 函数及其全部调用点（各 streamXxx 包装函数内向 localStorage/BroadcastChannel/electronAPI 写入的语句）。唯一消费方 DebugPromptWindow 已在清单 A 删除。

**删除后 `generateApi` 应只剩**：`optimizeSelection`、`formatText`、`generateInspiration`（这三个是活跃功能）。

---

## 3. 断链入口删除（需要逐文件编辑）

### 3.1 主编指导（critique）功能链

1. `features/chapter-editor/presentation/ChapterEditorView.vue`：
   - 删除「主编指导」按钮（:108-116，`@click="emit('request-critique', ...)"`）
   - 删除 emits 中 `request-critique`（:38）
   - 删除 `critiqueResult` prop（:32）及 watch（:64-69，`setCritiqueData` 调用）
2. `features/chapter-editor/containers/ChapterEditorContainer.vue`：删除 `critiqueResult` prop（:14）、`:critique-result` 传递（:57）、`@request-critique` 转发（:60）、emits 中 `request-critique`（:18）、`scrollToCritique` 暴露（:24）
3. `features/chapter-editor/containers/useChapterEditorContainer.ts`：删除 `scrollToCritique`（:71-80 及 :305 导出）、emit 类型中 `request-critique`（:19）
4. `components/ChapterEditor.vue`：删除 `critiqueResult` prop（:12）、`request-critique` emit（:15、:66）、`scrollToCritique`（:35-37、:48）、`:critique-result` 传递（:61）
5. `components/RichTextEditor.vue`（最大单点编辑，约 370 行）：
   - 删除 `import { CritiqueMark }`（:14）与扩展注册（:346）
   - 删除 :800-1172 区域全部 critique 逻辑：`currentCritique`、`shouldShowCritiqueMenu`、`CRITIQUE_LOOSE_IGNORE_RE`、`normalizeCritiqueQuote`、`buildCritiqueSearchIndex`、`setCritiqueData`、`scrollToCritiqueById`、`scrollToCritiqueByQuote` 及其 defineExpose（:1172-1174）
   - 删除 critique 浮动菜单模板（:1391-1399）
   - 删除 `.critique-highlight` 样式（:1609-1615）
   - ⚠ 只删 CritiqueMark 相关；`AuditHighlightMark` 及其逻辑完整保留
6. 删除 `extensions/CritiqueMark.ts`（清单 A）

### 3.2 整章优化入口

- `features/chapter-editor/containers/useChapterEditorContainer.ts`：
  - 删除 `handleOptimize`（:154-175）与 `optimizationFeedback` ref 及全部引用
  - 删除 `import { useChapterGenerator }`（:2）与 `const { optimizeChapter } = useChapterGenerator()`（:23）及 :22 注释
- 此后 `useChapterGenerator.ts` 无任何引用 → 整文件删除（清单 A）
- 同时删 `generateApi.optimize`（/optimize_chapter；`generateApi.optimizeSelection` 保留——选区优化是活跃功能）

---

## 4. 适配 / 修复项

### 4.1 引擎选择同步 bug
`features/workspace/containers/WorkspaceView.vue:62` 硬编码 `engineSelection = ref('v3.2')` 传给 `GenerationFlowView`（:308），而真实选择在 `InspectorPanel.vue:392` 的 TierSelector（`v-model:engine="engineSelection"`，InspectorPanel 自己的 :64）。

修法：删除 WorkspaceView 的本地 ref，让 `GenerationFlowView` 的引擎显示改从生成会话读取——`useGenerationSession.start` 已接收 `engine` 参数；执行时先确认 session 状态里是否已存 engine（若无，在 `useGenerationSession` 中补一个 `engine` ref 并在 start 时赋值），WorkspaceView 传 `:engine="session.engine ?? 'v3.2'"`。改动应限于 WorkspaceView.vue、useGenerationSession.ts 两处。

### 4.2 GenerationFlowView 缺失 import
`features/generation/presentation/GenerationFlowView.vue:103` 模板用了 `<Icon name="pencil-square">`，但 script setup（:14-15）未 import → 补 `import Icon from '../../../components/Icon.vue'`（路径以实际 Icon 组件位置为准，grep 其他组件的 Icon import 确认）。

### 4.3 InspectorPanel 残留清理（`features/workspace/containers/InspectorPanel.vue`）
- 删除 import（:26-27）：`SetupGraphView`、`PayloadCompareView`
- 删除 `showPayloadCompare`（:251、:256）
- 删除"结构 tab"残留派生代码（约 :244-302 的 `setupNodes`/`hasSetupGraph`/`sketchLabel` 等）：逐行 grep 模板确认无引用后删
- 更新文件头 docstring（:5-9）：旧描述"本章/结构/审校/速查"四 tab → 实际为「规划/精修/反馈/Canon」（:52-57）

### 4.4 useGenerationSession docstring
`features/generation/composables/useGenerationSession.ts:4` 注释仍写"合并 useChapterGenerator（双轨旧 SSE 事件）与 useDetonationGate（3.0 闸门）" → 按实际职责改写（统一封装 V3.1/V3.2 生成与 V4.1 精修的 SSE 会话状态机）。

### 4.5 AGENTS.md 前端部分更新
- 「项目结构」frontend/src/features 一节按现状重写：实际为 `app/`、`bible/`、`canon/`、`chapter-editor/`、`generation/`、`insights/`、`library/`、`novel-wizard/`、`outline/`、`workspace/`（及 `asset-panel/` 已有 index.ts）；`character-panel/`、`intent-driven/`、`detonation-gate/` 删除后从文档移除
- 「核心架构 → 章节生成主流程」一节顶部加显著标注：双轨描述已过时，实际主流程为 V3.1 `/generate` + V3.2 `/generate-adf` + V4.1 refinery（后端全面校准超出本次范围，仅加标注）

---

## 5. 执行顺序与验证

### 顺序
1. 清单 A 的叶子组件/类型/桶文件 → 2. feature 目录 → 3. 清单 B API 层 → 4. §3 断链编辑 → 5. §4 适配修复 → 6. AGENTS.md

### 每步验证（删除后立即执行）
```bash
cd frontend
# 对被删符号逐个全局 grep（示例）：
grep -rn "useCritique\|CritiquePanel\|DebugPromptWindow\|GoldenSnippetsManager" src/
grep -rn "planApi\|intentDrivenApi\|streamDualTrack\|streamAgentic\|useChapterGenerator" src/
grep -rn "detonation-gate\|character-panel\|SketchEditorPanel\|ChapterConfigPanel" src/
grep -rn "CritiqueMark\|request-critique\|setCritiqueData\|publishPromptData" src/
# 期望：零匹配（被删对象自身除外）
```

### 终验
```bash
cd frontend
npm run typecheck   # 必须全绿
npm run build       # 必须成功
```

### 人工冒烟（执行 agent 完成后由用户或 agent 启动）
`scripts/start-dev.bat` 启动后验证：书架建书 → workspace → V3.2 生成本章（PlanConfirmModal 弹出 → 确认 → SSE 进度 → 正文落盘）→ 精修诊断/确认 → 编辑器选区优化/格式整理/灵感弹窗 → 发布。全程控制台无报错。

### 收尾
`git status` 核对删除范围与本文档清单一致，无意外改动。
