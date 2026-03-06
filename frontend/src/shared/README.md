# shared 约束

## 目录职责

- `types`：跨 feature 复用的稳定类型。
- `utils`：纯函数工具，不依赖运行时业务状态。
- `index.ts`：共享模块统一导出入口。

## 使用约束

- shared 不依赖 features。
- shared 不直接依赖 services/domain 业务动作。
