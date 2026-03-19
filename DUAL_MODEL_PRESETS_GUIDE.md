# 双模型预设与服务商联动机制

## 问题背景

双模型预设中的模型名是特定于服务商的。例如：
- `gpt-4o` 是 OpenAI 的模型名
- `claude-3-haiku-20240307` 是 Anthropic 的模型名
- `moonshotai/kimi-k2.5` 是 OpenRouter 格式的模型名

如果用户选择了阿里云服务商，但预设里配的是 OpenAI 的模型名，调用会失败。

## 解决方案

### 1. 按服务商分类的预设配置

```javascript
const DUAL_MODEL_PRESETS_BY_PROVIDER = {
  openrouter: {
    gpt4o_haiku: {
      label: 'GPT-4o + Claude 3 Haiku（推荐）',
      reasoning: 'openai/gpt-4o',                    // OpenRouter 格式
      creative: 'anthropic/claude-3-haiku-20240307'
    },
    kimi_k2_flash: {
      label: 'Kimi K2.5 + Gemini Flash',
      reasoning: 'moonshotai/kimi-k2.5',
      creative: 'google/gemini-2.0-flash-001'
    }
  },
  aliyun: {
    qwen_max_plus: {
      label: 'Qwen-Max + Qwen-Plus（推荐）',
      reasoning: 'qwen-max',    // 阿里云格式
      creative: 'qwen-plus'
    }
  },
  custom: {
    // 自定义服务商不提供预设
  }
}
```

### 2. 动态获取当前服务商的预设

```javascript
const DUAL_MODEL_PRESETS = computed(() => {
  return DUAL_MODEL_PRESETS_BY_PROVIDER[formData.value.provider] 
    || DUAL_MODEL_PRESETS_BY_PROVIDER.custom
})

const availablePresets = computed(() => {
  const presets = DUAL_MODEL_PRESETS.value
  return Object.entries(presets)
    .filter(([key]) => key !== 'same')
    .reduce((acc, [key, value]) => { acc[key] = value; return acc }, {})
})
```

### 3. 服务商切换时的处理

```javascript
function handleProviderChange() {
  // ... 切换服务商的基础逻辑 ...
  
  // 切换服务商时，重置双模型预设（因为不同服务商的预设不兼容）
  if (enableDualModel.value) {
    selectedPreset.value = 'same'
    formData.value.reasoning_model = ''
    formData.value.creative_model = ''
    showToast('切换服务商后，请重新选择双模型预设', 'info')
  }
}
```

## 使用流程

### 场景 1：用户首次启用双模型

1. 用户选择服务商（如 OpenRouter）
2. 用户开启"双模型架构"开关
3. 默认显示"自定义配置"
4. 用户从预设列表选择（如 "GPT-4o + Claude 3 Haiku"）
5. 系统自动填充对应的模型名

### 场景 2：用户切换服务商

1. 用户当前使用 OpenRouter + GPT-4o/Haiku
2. 用户切换到阿里云
3. 系统自动：
   - 清空双模型配置
   - 重置预设为"自定义配置"
   - 显示提示："切换服务商后，请重新选择双模型预设"
4. 用户选择阿里云的双模型预设（如 "Qwen-Max + Qwen-Plus"）

### 场景 3：自定义服务商

1. 用户选择"自定义 / Custom"
2. 双模型预设区域显示"自定义配置"选项
3. 用户手动输入模型名

## 预设配置列表

### OpenRouter 预设

| 预设 | Reasoning | Creative | 说明 |
|-----|-----------|----------|------|
| gpt4o_haiku | openai/gpt-4o | anthropic/claude-3-haiku | 高质量 + 低成本（推荐） |
| claude_sonnet_haiku | anthropic/claude-3-5-sonnet | anthropic/claude-3-haiku | 全 Claude 生态 |
| kimi_k2_flash | moonshotai/kimi-k2.5 | google/gemini-2.0-flash | 国产 + 国际 |
| qwen_glm | qwen/qwen3.5-plus | z-ai/glm-5 | 全国产模型 |

### 阿里云预设

| 预设 | Reasoning | Creative | 说明 |
|-----|-----------|----------|------|
| qwen_max_plus | qwen-max | qwen-plus | 最强 + 标准 |
| qwen_same | qwen-max | qwen-max | 单模型模式 |

## 向后兼容

- 旧版本保存的配置只有 `model` 字段，没有双模型字段
- 打开设置面板时，如果 `reasoning_model` 或 `creative_model` 为空，自动显示"单模型模式"
- 用户可以手动开启双模型并选择预设

## 调用流程

```
用户选择预设
    ↓
handlePresetChange() 读取 DUAL_MODEL_PRESETS.value[selectedPreset]
    ↓
自动填充 formData.reasoning_model 和 formData.creative_model
    ↓
用户点击保存
    ↓
emit('save', formData) 到父组件
    ↓
存储到 localStorage
    ↓
API 调用时传入 reasoning_model 和 creative_model
```
