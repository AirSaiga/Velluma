<script setup lang="ts">
import { computed } from 'vue'
import type { WorkflowEvent } from '../composables/useChapterGenerator'

interface Props {
  currentEvent: WorkflowEvent | null
  message?: string
  iteration?: number
  revisionCount?: number
}

const props = withDefaults(defineProps<Props>(), {
  message: '',
  iteration: 1,
  revisionCount: 0
})

// 工作流节点定义
interface WorkflowNode {
  id: WorkflowEvent
  label: string
  description: string
  icon: string
}

const workflowNodes: WorkflowNode[] = [
  {
    id: 'ASSEMBLING_CONTEXT',
    label: '组装上下文',
    description: '加载人物卡与关系网',
    icon: 'M4 6h16M4 12h16M4 18h16'
  },
  {
    id: 'PLANNING',
    label: '规划节拍',
    description: '拆分章节剧情节点',
    icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2'
  },
  {
    id: 'DRAFTING',
    label: '起草创作',
    description: '主笔 Agent 生成初稿',
    icon: 'M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z'
  },
  {
    id: 'STITCHING',
    label: '统稿拼接',
    description: '整合各节拍内容',
    icon: 'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10'
  },
  {
    id: 'REVIEWING',
    label: '审阅质检',
    description: '逻辑校验与OOC排查',
    icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z'
  },
  {
    id: 'REFINING',
    label: '精修重写',
    description: '优化逻辑与表达',
    icon: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15'
  },
  {
    id: 'FINAL_TEXT_STREAM',
    label: '输出正文',
    description: '生成最终章节内容',
    icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z'
  }
]

// 判断节点状态
function getNodeStatus(nodeId: WorkflowEvent): 'pending' | 'active' | 'completed' {
  const current = props.currentEvent
  
  if (!current || current === 'DONE' || current === 'TEXT_CHUNK' || current === 'METRICS') {
    // 已完成的判断：如果当前节点在已完成列表中
    const currentIndex = workflowNodes.findIndex(n => n.id === current)
    const nodeIndex = workflowNodes.findIndex(n => n.id === nodeId)
    if (current === 'DONE') {
      return nodeIndex < workflowNodes.length ? 'completed' : 'pending'
    }
    if (currentIndex >= 0 && nodeIndex < currentIndex) {
      return 'completed'
    }
    return 'pending'
  }
  
  if (nodeId === current) {
    return 'active'
  }
  
  // 特殊处理：SCENE_INTENT 属于 DRAFTING 阶段
  if (current === 'SCENE_INTENT' && nodeId === 'DRAFTING') {
    return 'active'
  }
  
  // 判断先后顺序
  const currentIndex = workflowNodes.findIndex(n => n.id === current)
  const nodeIndex = workflowNodes.findIndex(n => n.id === nodeId)
  
  // REFINING 可能循环，需要特殊判断
  if (current === 'REFINING') {
    if (nodeId === 'REFINING') return 'active'
    // REVIEWING 和 REFINING 在循环中都可能被认为是进行中
    if (nodeId === 'REVIEWING') return 'completed'
    if (nodeId === 'STITCHING' || nodeId === 'DRAFTING' || nodeId === 'PLANNING' || nodeId === 'ASSEMBLING_CONTEXT') {
      return 'completed'
    }
  }
  
  if (nodeIndex < currentIndex) {
    return 'completed'
  }
  
  return 'pending'
}

// 获取当前显示的迭代信息
function getIterationText(): string {
  if (props.revisionCount > 0) {
    return `第 ${props.revisionCount + 1} 轮迭代`
  }
  if (props.iteration > 1) {
    return `第 ${props.iteration} 轮迭代`
  }
  return ''
}

// 计算进度宽度
const progressWidth = computed(() => {
  const currentIndex = workflowNodes.findIndex(n => 
    n.id === props.currentEvent || 
    (props.currentEvent === 'SCENE_INTENT' && n.id === 'DRAFTING')
  )
  const percentage = Math.max(0, currentIndex * (100 / (workflowNodes.length - 1)))
  return `calc(${percentage}%)`
})
</script>

<template>
  <div class="workflow-progress-graph">
    <!-- 标题区域 -->
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-sm font-semibold text-slate-700">生成进度</h3>
      <span v-if="getIterationText()" class="text-xs px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full">
        {{ getIterationText() }}
      </span>
    </div>
    
    <!-- 节点流程图 -->
    <div class="relative">
      <!-- 连接线 -->
      <div class="absolute top-6 left-8 right-8 h-0.5 bg-slate-200 -translate-y-1/2 z-0"></div>
      
      <!-- 已完成的连接线 -->
      <div 
        class="absolute top-6 left-8 h-0.5 bg-indigo-500 -translate-y-1/2 z-0 transition-all duration-500"
        :style="{ width: progressWidth }"
      ></div>
      
      <!-- 节点列表 -->
      <div class="relative z-10 flex justify-between">
        <div 
          v-for="(node, index) in workflowNodes" 
          :key="node.id"
          class="flex flex-col items-center"
          :class="{ 'flex-1': index < workflowNodes.length - 1 }"
        >
          <!-- 节点圆圈 -->
          <div 
            class="w-12 h-12 rounded-full flex items-center justify-center transition-all duration-300 border-2"
            :class="{
              // 已完成状态
              'bg-indigo-500 border-indigo-500': getNodeStatus(node.id) === 'completed',
              // 进行中状态
              'bg-white border-indigo-500 shadow-lg shadow-indigo-200 scale-110': getNodeStatus(node.id) === 'active',
              // 待处理状态
              'bg-white border-slate-300': getNodeStatus(node.id) === 'pending'
            }"
          >
            <!-- 完成图标 -->
            <svg 
              v-if="getNodeStatus(node.id) === 'completed'"
              class="w-6 h-6 text-white"
              fill="none" 
              stroke="currentColor" 
              viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            </svg>
            
            <!-- 进行中动画 -->
            <template v-else-if="getNodeStatus(node.id) === 'active'">
              <div class="absolute inset-0 rounded-full border-2 border-indigo-500 animate-ping opacity-30"></div>
              <svg 
                class="w-5 h-5 text-indigo-500 animate-spin"
                fill="none" 
                viewBox="0 0 24 24"
              >
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            </template>
            
            <!-- 待处理图标 -->
            <svg 
              v-else
              class="w-5 h-5 text-slate-400"
              fill="none" 
              stroke="currentColor" 
              viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="node.icon" />
            </svg>
          </div>
          
          <!-- 节点标签 -->
          <div class="mt-2 text-center">
            <div 
              class="text-xs font-medium transition-colors duration-300"
              :class="{
                'text-indigo-600': getNodeStatus(node.id) === 'active',
                'text-slate-600': getNodeStatus(node.id) === 'completed',
                'text-slate-400': getNodeStatus(node.id) === 'pending'
              }"
            >
              {{ node.label }}
            </div>
            <div 
              v-if="getNodeStatus(node.id) === 'active' && message"
              class="text-[10px] text-slate-500 mt-0.5 max-w-[80px] truncate"
              :title="message"
            >
              {{ message }}
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <!-- 当前状态信息 -->
    <div 
      v-if="currentEvent && currentEvent !== 'DONE' && currentEvent !== 'TEXT_CHUNK'"
      class="mt-4 p-3 bg-indigo-50 rounded-lg border border-indigo-100"
    >
      <div class="flex items-center gap-2">
        <div class="w-2 h-2 rounded-full bg-indigo-500 animate-pulse"></div>
        <span class="text-xs text-indigo-700 font-medium">
          {{ workflowNodes.find(n => n.id === currentEvent)?.description || message }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflow-progress-graph {
  width: 100%;
}
</style>
