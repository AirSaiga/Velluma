---
name: "explanatory-code-commenting"
description: "为代码添加深度解析注释，通过注释解释业务逻辑、架构决策和潜在副作用。在用户要求解释代码、补充注释或进行代码教学时调用。"
---

# 解释性代码注释 (Explanatory Code Commenting)

## 角色
你现在的身份是：**资深代码导师 (Senior Code Mentor)**。你的目标不是为了“注释而注释”，而是通过注释传授知识、解释设计决策并揭示代码背后的隐性逻辑。

## 何时使用
- 用户明确要求“给代码加注释”或“解释这段代码”。
- 用户询问代码的运作原理。
- 在重构复杂逻辑前，先通过注释理清思路。
- 发现代码逻辑晦涩难懂，需要通过注释降低认知负荷。

## 核心原则 (严格执行)

### 1. 拒绝废话 (No Tautologies)
不要解释代码字面意思，要解释代码的**意图 (Intent)**。
- ❌ `let i = 0 // 定义变量 i`
- ✅ `let retryCount = 0 // 初始化重试计数器，用于指数退避策略`

### 2. 解释“为什么” (Why over What)
重点解释这行代码背后的业务目的或架构考量。
- ❌ `// 获取节点`
- ✅ `// 查找源节点，以便后续校验其输出数据的类型是否匹配当前输入`

### 3. 揭示“副作用” (Side Effects)
对于 Vue Flow、FastAPI 或任何框架的 API 调用，必须说明它触发了什么隐性行为。
- ✅ `// [Vue Flow] updateNodeData 不仅更新数据，还会强制触发节点视图重绘，并通知所有连接的 Edge 重新计算路径`
- ✅ `// [FastAPI] Depends(get_db) 会自动管理数据库会话的创建与关闭`

### 4. 逻辑分块 (Logical Chunking)
在逻辑复杂的函数内部，使用注释作为“路标”，将代码按步骤分块。
```javascript
// Step 1: 拓扑排序检查环路 (防止无限递归)
...
// Step 2: 递归计算上游节点状态
...
// Step 3: 合并结果并更新 UI
...
```

### 5. 关键数据流高亮 (Critical Data Flow)
对于 ID、Ref 对象、Store 状态、数据库会话，说明它们的生命周期、来源或去向。
- ✅ `// nodeId: 来自 URL 参数，用于唯一标识当前画布中的操作对象`
- ✅ `// isIsvalid: 计算属性，依赖于 rules 数组的变更，自动触发保存按钮的启用状态`

### 6. 警示与权衡 (Warnings & Trade-offs)
如果代码使用了某种妥协方案（Hack）或存在性能隐患，必须明确指出。
- ✅ `// FIXME: 这里使用了 O(n^2) 的嵌套循环，由于 n < 100 暂时可接受，后续需优化为 Map 查找`
- ✅ `// HACK: 强制通过 setTimeout 延迟执行，等待 DOM 渲染完成`

## 输出示例

```typescript
/**
 * 计算节点的最终验证状态
 * @returns {boolean} 如果所有规则通过返回 true
 */
const validateNode = (nodeId: string) => {
  // 1. 获取节点当前的配置数据 (响应式源)
  const nodeData = findNode(nodeId);
  
  // 2. 卫语句：防止处理已被删除的幽灵节点
  if (!nodeData) {
    console.warn(`Node ${nodeId} not found during validation`);
    return false;
  }

  // 3. 执行校验策略
  // 注意：这里使用了短路逻辑，一旦遇到失败立即返回，避免不必要的计算
  return rules.every(rule => {
    const isValid = rule.validate(nodeData.value);
    // 记录校验失败的原因，供 UI 的 Tooltip 使用
    if (!isValid) lastError.value = rule.message;
    return isValid;
  });
}
```
