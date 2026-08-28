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
