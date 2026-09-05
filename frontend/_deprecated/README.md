# 前端已归档功能清单（2026-08-29 全量审查后弃置）

> 审查报告见 `docs/frontend-audit-2026-08-29.md`。本目录只留清单不留代码——
> 代码在 git 历史（按提交号可回溯）。归档原则：用户拍板「所有旧的东西全部
> 弃置归档，不要让它们干扰主代码」。

## useGenerationSession.ts 步进链路尸体群（-~900 行）

| 符号 | 死因 |
|---|---|
| `currentTask` computed（120 行） | 唯一消费者 CurrentTaskBar 已随 BS-ADF UI 删除 |
| `handleBsadfEvent` / `mapBsadfStageToLabel` | BS-ADF SSE 分发机零调用者 |
| `_syncEnhancedCards` / `_pollSteppingReady` / `_resyncSteppingRun` / `_stopSteppingPoll` / `_noteSteppingActivity` | fetch 已删除的 `/stepping-run/{id}/state` 端点 |
| `setReadySegmentText` / `revertReadySegment` / `acceptReadySegment` / `lockAuthoringBeat` / `scrubToFragment` / `mergeAutoCut` / `autoCutNotice` / `_sedimentTick` / `_autoLockCurrentBeat` | stage 机器态（beat_stepping/beat_authoring）在 adaptive 流下不可达 |
| `_rollbackFromBeat` / `_clearSegmentText` / `_handleBeatChunk` / `_rebuildStreamTextFromSegments` / `upsertRenderProgress` / `_finalizeDoneFromPoll` / `_onBeatAuthoringOpen` / `_applyEnhancedCards` | 仅被上述死群调用 |
| `applyTierDecision` / `applyAdfAudit` / ADF 产物 ref（tierDecision/climaxScore/adfAnchor/adfPreconditions/adfEmotionCurve/adfAudit/auditFindings/auditVerdict/inflightEvents/degraded） | 零外部消费者；快照恢复侧同步清除 |
| `_cancelSteppingRun`（空壳）/ 8 处调用点 | BS-ADF 归档时的防连锁妥协，随本批彻底移除 |

## api 层 BS-ADF SSE 分发机（domain/index.ts ~160 行）

`BsadfStreamCallbacks` / `_dispatchEvent` / `BSADF_TERMINAL_EVENTS`——零调用者（`bsadfApi` 导出不存在）。

## 零散僵尸

| 项 | 位置 | 死因 |
|---|---|---|
| 「Ctrl + Backspace 回退上一步」 | ShortcutsCheatsheet.vue:33 | BS-ADF back 机制已删，全工程无此键位处理 |
| `shared/constants/degradation.ts` | 整文件 | 唯一消费点在 currentTask（已删） |
| InspectorPanel「检查结论·结构检查」块 | 820-836 | 读 `session.adfAudit`——新流程下永无新数据 |
| InspectorPanel「出场角色」卡 | 523-541 | 读旧 `chapter.character_ids` 表（世界页在场推演取代） |
| InsightsView「兜底记录」面板 | 393-405 + 汇总卡 + PanelKey | 数据源=旧整章管线 degraded 上报，adaptive 流不产数据 |
| WorkspaceView `pendingSaveText` watch | 297-316 | rerender-beat 信号源已删 |

## 文档谎言修正

「规划本章」`startBeat` 入口实际已不存在——6 处注释声称保留、AGENTS.md 同谎，本批全部改为「旧 step 路径已归档，adaptive 是唯一写作路径」。

## 设定中心页整体退役（2026-09-05，global_sys_prompt 死线）

> 审计发现：「创作笔记」写入 `books.global_sys_prompt`，页面承诺「可在全局提示词中使用」——
> 实际 adaptive 主线（settings_bundle）完全不读该字段；消费方全部不在活路（后端同批归档，
> 见 `backend/_deprecated/README.md` 2026-09-05 节）。用户拍板退役整条线。本节只留清单，
> 代码在 git 历史。

| 项 | 位置 | 死因 |
|---|---|---|
| `features/bible/` 整目录（BibleView + WorldRedirectCard） | 已删除 | 页面唯一真实编辑面=笔记；其余六分区早已是世界页跳转卡，纯导航化石 |
| `components/NotesPanel.vue` | 已删除 | 写 `books.global_sys_prompt`，零活消费方 |
| AppRail「设定」项 + `/bible/:bookId` 路由 | 已删除 | 页面退役；路由改 redirect → 世界页（canon 先例） |
| 建书快速表单「全局提示词」字段 | LibraryView | 死写同上 |
| 向导「写作风格指南」字段（styleGuide + 6 预设 styleHint） | novel-wizard | 映射到 global_sys_prompt，虚假承诺「会在所有章节生成中生效」；文风意图正道=文风页 |
| `Book.global_sys_prompt` 类型字段 | types/index.ts | 后端 schema 同步摘除 |

零变化说明：未在笔记/向导填过内容的书行为不变；填过的历史内容仍在 DB（`books.global_sys_prompt`
冻结列），不再有任何代码读写。
