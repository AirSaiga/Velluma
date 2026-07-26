/**
 * 小说创作向导 - 类型定义
 * 
 * 本文件定义了向导流程中所有表单数据的类型结构
 * 采用用户友好的命名，同时保留内部技术字段的映射关系
 */

// ============== 模式定义 ==============

/** 编辑模式：基础模式适合普通用户，专家模式适合高级用户 */
export type EditorMode = 'basic' | 'expert'

/** 向导步骤 */
export type WizardStep = 'story' | 'world' | 'characters' | 'chapter' | 'settings'

// ============== 故事设定 ==============

/** 故事类型预设模板 */
export interface StoryTemplate {
  id: string
  name: string
  genre: string
  styleHint: string
  tensionDefault: number
  pacingDefault: PacingStyle
}

/** 故事基础信息 */
export interface StoryBasics {
  /** 书名 */
  title: string
  /** 故事类型：奇幻、科幻、都市等 */
  genre: string
  /** 写作风格指南（原 global_sys_prompt） */
  styleGuide: string
  /** 核心主题与禁忌（原 core_motifs_taboos）- 仅专家模式 */
  themesAndTaboos: string
}

// ============== 世界观构建 ==============

/** 世界观条目 */
export interface WorldItem {
  id: string
  /** 条目标题 */
  title: string
  /** 详细内容 */
  content: string
  /** 是否折叠 */
  collapsed: boolean
}

/** 地点/场景 */
export interface Location {
  id: string
  name: string
  description: string
  tags?: string[]
}

/** 世界观设定 */
export interface WorldBuilding {
  /** 世界背景（原 worldview_settings） */
  background: WorldItem[]
  /** 地点/场景（原 map_locations） */
  locations: Location[]
  /** 世界规则 - 仅专家模式 */
  rules: WorldItem[]
}

// ============== 角色管理 ==============

/** 角色重要程度 */
export type CharacterImportance = 'normal' | 'important' | 'protagonist' | 'core'

/** 角色信息 */
export interface CharacterInfo {
  id: string
  /** 角色名称 */
  name: string
  /** 重要程度 */
  importance: CharacterImportance
  /** 角色档案（原 static_prompt） */
  profile: string
  /** 当前状态（原 dynamic_state） */
  currentState: string
  /** 此刻状态（原 current_state）- 仅专家模式 */
  instantState: string
}

/** 角色关系 */
export interface CharacterRelationship {
  id: string
  /** 源角色ID */
  sourceId: string
  /** 目标角色ID */
  targetId: string
  /** 关系类型：朋友、敌人、恋人等 */
  relationType: string
  /** 好感度/亲密度 (0-100) */
  affinity: number
  /** 互动模式 - 仅专家模式 */
  interactionPattern: string
}

// ============== 章节配置 ==============

/** 节奏风格 */
export type PacingStyle = 'slow_burn' | 'balanced' | 'fast_paced'

/** 记忆检索策略 */
export type MemoryStrategy = 'recent_only' | 'balanced_reference' | 'deep_dive'

/** 创作自由度 */
export type CreativityLevel = 'strict_prompt' | 'balanced_creation' | 'wild_imagination'

/** 精修深度 */
export type RefinementDepth = 'light' | 'standard' | 'deep'

/** 章节配置 */
export interface ChapterConfig {
  /** 章节编号 */
  chapterNumber: number
  /** 章节标题 */
  title: string
  /** 章节大纲（原 outline_text） */
  outline: string
  /** 出场角色ID列表 */
  characterIds: string[]
  /** 目标字数 */
  targetWordCount: number
  /** 作者意图 */
  authorIntent: string
  /** 戏剧张力 (1-10) - 仅专家模式 */
  tensionLevel: number
  /** 节奏风格 - 仅专家模式 */
  pacingStyle: PacingStyle
  /** 章节禁区 - 仅专家模式 */
  forbiddenContent: string
  /** 记忆检索策略 - 仅专家模式 */
  memoryStrategy: MemoryStrategy
  /** 创作自由度 - 仅专家模式 */
  creativityLevel: CreativityLevel
  /** 精修深度 - 仅专家模式 */
  refinementDepth: RefinementDepth
}

// ============== 专家设置 ==============

/** 推理强度级别 */
export type ReasoningEffort = 'xhigh' | 'high' | 'medium' | 'low' | 'minimal' | 'none'

/** 推理模式配置 */
export interface ReasoningSettings {
  /** 是否启用推理模式 */
  enabled: boolean
  /** 推理强度 */
  effort: ReasoningEffort
  /** 是否排除推理过程 */
  excludeProcess: boolean
}

/** RAG 记忆检索配置 */
export interface RAGSettings {
  /** 检索数量 */
  topK: number
  /** 语义相关度权重 (原 rag_alpha) */
  semanticWeight: number
  /** 时间衰减权重 (原 rag_beta) */
  timeDecayWeight: number
  /** 伏笔权重 (原 rag_gamma) */
  foreshadowingWeight: number
  /** 时间衰减系数 (原 rag_lambda) */
  decayFactor: number
}

/** 生成流程配置 */
export interface GenerationSettings {
  /** 最大迭代次数 */
  maxIterations: number
  /** 是否跳过轻微问题的精修 */
  skipMinorRefine: boolean
}

/** 专家设置 */
export interface ExpertSettings {
  /** 生成模型（V4.1: 仅作为前端表单保留，实际从 model_config.json 读取） */
  model: string
  /** 默认模型推理配置 */
  reasoningConfig: ReasoningSettings
  /** RAG 配置 */
  ragConfig: RAGSettings
  /** 生成流程配置 */
  generationConfig: GenerationSettings
}

// ============== 向导整体状态 ==============

/** 向导表单数据 */
export interface WizardFormData {
  /** 编辑模式 */
  mode: EditorMode
  /** 当前步骤 */
  currentStep: WizardStep
  /** 故事设定 */
  story: StoryBasics
  /** 世界观 */
  world: WorldBuilding
  /** 角色列表 */
  characters: CharacterInfo[]
  /** 角色关系 */
  relationships: CharacterRelationship[]
  /** 章节配置 */
  chapter: ChapterConfig
  /** 专家设置 */
  expertSettings: ExpertSettings
  /** 草稿保存状态 */
  draftStatus: 'idle' | 'dirty' | 'saving' | 'saved' | 'error'
}

/** 向导验证错误 */
export interface ValidationError {
  field: string
  message: string
  severity: 'error' | 'warning'
}

// ============== 预设模板 ==============

/** 故事类型预设 */
export const STORY_GENRE_PRESETS: StoryTemplate[] = [
  {
    id: 'fantasy',
    name: '奇幻',
    genre: '奇幻',
    styleHint: '注重世界观构建，描写细腻，适当使用古风表达',
    tensionDefault: 5,
    pacingDefault: 'balanced'
  },
  {
    id: 'scifi',
    name: '科幻',
    genre: '科幻',
    styleHint: '注重逻辑性，描写未来科技与人类冲突',
    tensionDefault: 6,
    pacingDefault: 'fast_paced'
  },
  {
    id: 'urban',
    name: '都市',
    genre: '都市',
    styleHint: '贴近现实生活，对话自然，情感细腻',
    tensionDefault: 4,
    pacingDefault: 'balanced'
  },
  {
    id: 'suspense',
    name: '悬疑',
    genre: '悬疑',
    styleHint: '层层设疑，节奏紧凑，注重心理描写',
    tensionDefault: 7,
    pacingDefault: 'fast_paced'
  },
  {
    id: 'romance',
    name: '言情',
    genre: '言情',
    styleHint: '情感丰富，对话为主，注重心理活动',
    tensionDefault: 3,
    pacingDefault: 'slow_burn'
  },
  {
    id: 'wuxia',
    name: '武侠',
    genre: '武侠',
    styleHint: '江湖气息，动作场面生动，人物性格鲜明',
    tensionDefault: 6,
    pacingDefault: 'balanced'
  }
]

/** 默认向导数据 */
export function createDefaultWizardData(): WizardFormData {
  return {
    mode: 'basic',
    currentStep: 'story',
    story: {
      title: '',
      genre: '',
      styleGuide: '',
      themesAndTaboos: ''
    },
    world: {
      background: [],
      locations: [],
      rules: []
    },
    characters: [],
    relationships: [],
    chapter: {
      chapterNumber: 1,
      title: '',
      outline: '',
      characterIds: [],
      targetWordCount: 3000,
      authorIntent: '',
      tensionLevel: 5,
      pacingStyle: 'balanced',
      forbiddenContent: '',
      memoryStrategy: 'balanced_reference',
      creativityLevel: 'balanced_creation',
      refinementDepth: 'standard'
    },
    expertSettings: {
      model: '',
      reasoningConfig: {
        enabled: false,
        effort: 'medium',
        excludeProcess: false
      },
      ragConfig: {
        topK: 5,
        semanticWeight: 0.6,
        timeDecayWeight: 0.2,
        foreshadowingWeight: 0.2,
        decayFactor: 0.95
      },
      generationConfig: {
        maxIterations: 3,
        skipMinorRefine: false
      }
    },
    draftStatus: 'idle'
  }
}
