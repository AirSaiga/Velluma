# 统一配置对象参数映射表

本文档详细说明前端参数如何映射到后端统一配置对象。

## 1. 参数分类总览

| 分类 | 配置对象 | 说明 |
|------|----------|------|
| 故事语义层 | `StoryConfig` | 风格、主题、禁忌等跨章节稳定配置 |
| 章节规划层 | `ChapterPlan` | 单章创作意图、张力、节奏等 |
| 模型配置层 | `LLMConfig` | API 连接、模型选择、推理配置 |
| 检索策略层 | `RAGPolicy` | 向量记忆检索参数 |
| 工作流策略层 | `WorkflowPolicy` | 迭代、双轨、并行策略 |
| 校验策略层 | `ValidationPolicy` | 质检规则、Fail-Fast 机制 |
| 功能开关 | `FeatureFlags` | 实验性功能开关 |

---

## 2. 详细参数映射表

### 2.1 StoryConfig - 故事语义层

| 前端参数名 | 后端字段名 | 来源 | 自动推导 | 默认值 | 校验 |
|------------|------------|------|----------|--------|------|
| - | `genre` | Book.genre | ❌ | "" | - |
| `styleGuide` | `style_guide` | Book.global_sys_prompt | ❌ | "" | - |
| `themesAndTaboos` | `themes_and_taboos` | Book.core_motifs_taboos | ❌ | "" | - |
| `worldviewSettings` | `worldview_settings` | Book.worldview_settings | ❌ | {} | - |
| `goldenSnippets` | `golden_snippets` | Book.golden_snippets | ❌ | [] | - |
| `styleBlacklist` | `style_blacklist` | Book.style_blacklist | ❌ | [] | - |
| - | `style_complexity` | - | ✅ 计算风格复杂度 | 0.5 | 0-1 |

---

### 2.2 ChapterPlan - 章节规划层

| 前端参数名 | 后端字段名 | 来源 | 自动推导 | 默认值 | 校验 |
|------------|------------|------|----------|--------|------|
| `chapterNumber` | `chapter_number` | Chapter.chapter_number | ❌ | - | ≥1 |
| `title` | `title` | Chapter.title | ❌ | "" | - |
| `outline` | `outline` | Chapter.outline_text | ❌ | "" | - |
| `authorIntent` | `author_intent` | 请求传入 | ❌ | "" | - |
| `targetWordCount` | `target_word_count` | 请求传入 | ❌ | 3000 | 500-20000 |
| `tensionLevel` | `tension_level` | 请求/Chapter | ❌ | 3 | 1-5 |
| `pacingStyle` | `pacing_style` | 请求/Chapter | ❌ | "balanced" | 枚举 |
| `forbiddenContent` | `forbidden_content` | 请求传入 | ❌ | "" | - |
| - | `workflow_tier` | - | ✅ 张力等级映射 | "TIER_2_STANDARD" | 枚举 |
| - | `expected_iterations` | - | ✅ 层级映射 | 2 | 1-5 |

**张力等级 → 工作流层级映射：**

| tension_level | workflow_tier | 说明 |
|---------------|---------------|------|
| 1-2 | TIER_1_FAST | 疾速流，单次生成 |
| 3 | TIER_2_STANDARD | 均衡流，标准迭代 |
| 4-5 | TIER_3_FORTRESS | 堡垒流，深度精修 |

---

### 2.3 LLMConfig - 模型配置层

| 前端参数名 | 后端字段名 | 来源 | 自动推导 | 默认值 | 校验 |
|------------|------------|------|----------|--------|------|
| `apiKey` | `api_key` | 请求传入 | ❌ | - | 必填 |
| `baseUrl` | `base_url` | 请求传入 | ❌ | None | - |
| `model` | `default_model` | 请求传入 | ❌ | "gpt-4o-mini" | - |
| `reasoningModel` | `reasoning_model` | 请求传入 | ❌ | None | - |
| `creativeModel` | `creative_model` | 请求传入 | ❌ | None | - |
| `reasoningConfig` | `default_reasoning_config` | 请求传入 | ❌ | ReasoningSettings() | - |
| `reasoningModelReasoningConfig` | `reasoning_model_config` | 请求传入 | ❌ | ReasoningSettings(effort="high") | - |
| `creativeModelReasoningConfig` | `creative_model_config` | 请求传入 | ❌ | ReasoningSettings(effort="low") | - |

**推理配置字段：**

| 字段 | 说明 | 默认值 | 校验 |
|------|------|--------|------|
| `enabled` | 是否启用推理模式 | False | - |
| `effort` | 推理强度 | "medium" | 枚举 |
| `max_tokens` | 推理 token 上限 | None | 100-32000 |
| `exclude_process` | 是否排除推理过程 | False | - |

---

### 2.4 RAGPolicy - 检索策略层

| 前端参数名 | 后端字段名 | 来源 | 自动推导 | 默认值 | 校验 |
|------------|------------|------|----------|--------|------|
| `memoryStrategy` | `memory_strategy` | 请求传入 | ❌ | "balanced_reference" | 枚举 |
| `topK` / `rag_top_k` | `top_k` | 请求/策略推导 | 可覆盖 | 5 | 1-20 |
| `semanticWeight` / `rag_alpha` | `semantic_weight` | 请求/策略推导 | 可覆盖 | 0.6 | 0-1 |
| `timeDecayWeight` / `rag_beta` | `time_decay_weight` | 请求/策略推导 | 可覆盖 | 0.2 | 0-1 |
| `foreshadowingWeight` / `rag_gamma` | `foreshadowing_weight` | 请求/策略推导 | 可覆盖 | 0.2 | 0-1 |
| `decayFactor` / `rag_lambda` | `decay_factor` | 请求/策略推导 | 可覆盖 | 0.1 | ≥0 |
| - | `enable_memory_injection` | - | ✅ | True | - |

**权重约束：** `semantic_weight + time_decay_weight + foreshadowing_weight = 1.0`

**记忆策略预设：**

| 策略 | top_k | semantic | time_decay | foreshadowing | decay |
|------|-------|----------|------------|---------------|-------|
| `recent_only` | 3 | 0.4 | 0.5 | 0.1 | 0.3 |
| `balanced_reference` | 5 | 0.6 | 0.2 | 0.2 | 0.1 |
| `deep_dive` | 10 | 0.5 | 0.15 | 0.35 | 0.05 |

---

### 2.5 WorkflowPolicy - 工作流策略层

| 前端参数名 | 后端字段名 | 来源 | 自动推导 | 默认值 | 校验 |
|------------|------------|------|----------|--------|------|
| `creativityLevel` | `creativity_level` | 请求传入 | ❌ | "balanced_creation" | 枚举 |
| `refinementDepth` | `refinement_depth` | 请求传入 | ❌ | "standard" | 枚举 |
| `maxIterations` | `max_iterations` | 请求/层级推导 | 可覆盖 | 2 | 1-5 |
| `fastMode` | `fast_mode` | 请求传入 | ❌ | False | - |
| `skipMinorRefine` | `skip_minor_refine` | 请求/层级推导 | 可覆盖 | True | - |
| `forceParallelProse` | `force_parallel_prose` | 请求/自由度推导 | 可覆盖 | False | - |
| `semiParallelProse` | `semi_parallel_prose` | 请求/自由度推导 | 可覆盖 | True | - |
| `beatConcurrency` | `beat_concurrency` | 环境变量 | ❌ | 6 | 1-12 |

**创作自由度 → 并行策略映射：**

| creativity_level | parallel_mode | force_parallel | semi_parallel |
|------------------|---------------|----------------|---------------|
| `strict_prompt` | sequential | False | False |
| `balanced_creation` | semi_parallel | False | True |
| `wild_imagination` | full_parallel | True | True |

**DualTrackSettings 子配置：**

| 前端参数名 | 后端字段名 | 来源 | 默认值 | 校验 |
|------------|------------|------|--------|------|
| `enableSketchTrack` | `enable_sketch_track` | 请求/层级推导 | True | - |
| `enableAdversarialAlignment` | `enable_adversarial_alignment` | 请求/层级推导 | True | - |
| `useSketchForRefinement` | `use_sketch_for_refinement` | 请求传入 | True | - |
| `alignmentThreshold` | `alignment_threshold` | 请求/层级推导 | 70.0 | 0-100 |
| `sketchRatio` | `sketch_ratio` | 请求传入 | 0.45 | 0.2-0.7 |

---

### 2.6 ValidationPolicy - 校验策略层

| 前端参数名 | 后端字段名 | 来源 | 自动推导 | 默认值 | 校验 |
|------------|------------|------|----------|--------|------|
| `enableFailFast` | `enable_fail_fast` | feature_flags | ❌ | True | - |
| `failFastMaxAttempts` | `fail_fast_max_attempts` | feature_flags | ❌ | 2 | 1-3 |
| `failFastTemperatureStep` | `fail_fast_temperature_step` | feature_flags | ❌ | 0.2 | 0-0.5 |
| `enableEmotionalScratchpad` | `enable_emotional_scratchpad` | feature_flags | ❌ | True | - |
| - | `quality_threshold` | - | ✅ 精修深度映射 | 0.7 | 0-1 |
| - | `consistency_threshold` | - | ✅ | 0.8 | 0-1 |

**精修深度 → 质量阈值映射：**

| refinement_depth | quality_threshold |
|------------------|-------------------|
| `light` | 0.6 |
| `standard` | 0.7 |
| `deep` | 0.85 |

---

### 2.7 FeatureFlags - 功能开关

| 前端参数名 | 后端字段名 | 来源 | 默认值 |
|------------|------------|------|--------|
| `enableWhisperMemory` | `enable_whisper_memory` | feature_flags | False |
| - | `enable_worldbuilding_injection` | 请求 | True |
| - | `enable_cross_chapter_validation` | 请求 | True |
| - | `enable_dynamic_state_update` | 请求 | True |

---

## 3. 推导规则详解

### 3.1 张力等级推导链

```
tension_level (前端传入)
    │
    ├──→ workflow_tier (自动映射)
    │       ├── 1-2 → TIER_1_FAST
    │       ├── 3 → TIER_2_STANDARD
    │       └── 4-5 → TIER_3_FORTRESS
    │
    └──→ 影响:
            ├── max_iterations
            ├── dual_track.enable_sketch_track
            ├── dual_track.enable_adversarial_alignment
            ├── validation.enable_fail_fast
            └── validation.quality_threshold
```

### 3.2 记忆策略推导链

```
memory_strategy (前端传入)
    │
    └──→ RAG 参数预设
            ├── recent_only: top_k=3, decay_factor=0.3
            ├── balanced_reference: top_k=5, decay_factor=0.1
            └── deep_dive: top_k=10, decay_factor=0.05
```

### 3.3 创作自由度推导链

```
creativity_level (前端传入)
    │
    └──→ 并行策略
            ├── strict_prompt: sequential (force_parallel=False, semi_parallel=False)
            ├── balanced_creation: semi_parallel (force_parallel=False, semi_parallel=True)
            └── wild_imagination: full_parallel (force_parallel=True, semi_parallel=True)
```

---

## 4. 使用示例

### 4.1 从请求构建配置

```python
from backend.config import derive_config, GenerationConfig

# 方式1：便捷函数
config = derive_config(request, chapter, book)

# 方式2：手动构建
config = GenerationConfig.from_request(request, chapter, book)
config.derive_all()
config.validate_all()
```

### 4.2 访问配置字段

```python
# 章节配置
word_count = config.chapter.target_word_count
tension = config.chapter.tension_level
tier = config.chapter.workflow_tier

# LLM 配置
api_key = config.llm.api_key
reasoning_model = config.llm.get_effective_reasoning_model()

# RAG 配置
top_k = config.rag.top_k

# 工作流配置
iterations = config.workflow.max_iterations
enable_dual_track = config.workflow.dual_track.enable_sketch_track
```

### 4.3 向后兼容

```python
from backend.config import adapt_request_to_config, config_to_legacy_dict

# 适配旧版请求
config = adapt_request_to_config(request, chapter, book)

# 转换为旧版字典
legacy_dict = config.to_legacy_format()
```

---

## 5. 参数来源总结

| 来源 | 参数数量 | 说明 |
|------|----------|------|
| 前端直接传入 | ~25 | 用户在表单中设置的参数 |
| 数据库加载 | ~10 | 从 Book/Chapter 实体加载 |
| 自动推导 | ~15 | 根据推导规则自动计算 |
| 环境变量 | 2 | AGENTIC_BEAT_CONCURRENCY, AGENTIC_FORCE_FAST_MODE |

---

*最后更新: 2026-03-28*
