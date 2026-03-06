# services 分层约束

## 目录职责

- `transport`：底层请求能力与基础地址解析。
- `stream`：SSE/流式协议读取与事件分发。
- `domain`：面向业务语义的 API 适配与组合。

## 依赖方向

- `domain -> stream`
- `domain -> transport`
- `stream -> transport`
- 上层容器只依赖 `domain`，不直接调用 `transport` 与 `stream`。
