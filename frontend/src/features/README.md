# features 分层约束

## 目录职责

- `*/containers`：页面或业务容器，负责状态整合与事件编排。
- `*/presentation`：展示组件层，负责渲染与交互事件抛出。
- `index.ts`：模块导出入口，仅暴露稳定对外接口。

## 依赖方向

- 允许：`presentation -> 容器 props / emits`
- 允许：`containers -> services/domain`、`containers -> shared/*`
- 禁止：`presentation -> services/transport`、`presentation -> services/stream`

## 命名规范

- Feature 目录使用 kebab-case。
- 容器组件文件以 `*Container` 结尾。
- 展示组件文件以 `*View` 或 `*Panel` 结尾。
