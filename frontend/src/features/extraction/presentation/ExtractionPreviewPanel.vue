<script setup lang="ts">
/**
 * 正文逆向提取预览面板（分类标签 + 逐条勾选）。
 *
 * 职责：纯展示——渲染 analyze 返回的提取结果，用户按类别查看并勾选确认。
 * 通过 emits 将确认子集上抛容器。
 */
import { ref, computed, reactive } from 'vue'
import Icon from '../../../components/Icon.vue'
import type {
  ExtractionResult,
  ExtractedCharacter,
  ExtractedRelationship,
  ExtractedLocation,
  ExtractedAsset,
  ExtractedForeshadow,
} from '../../../services/api/domain/extraction.api'

const props = defineProps<{
  result: ExtractionResult
}>()

const emit = defineEmits<{
  confirm: [confirmed: {
    characters: ExtractedCharacter[]
    relationships: ExtractedRelationship[]
    locations: ExtractedLocation[]
    assets: ExtractedAsset[]
    foreshadows: ExtractedForeshadow[]
  }]
  cancel: []
}>()

type Tab = 'characters' | 'relationships' | 'locations' | 'assets' | 'foreshadows'
const activeTab = ref<Tab>('characters')

// 每类一个勾选状态 Set（用 index 作为 key）
const checked = reactive<Record<Tab, Set<number>>>({
  characters: new Set(),
  relationships: new Set(),
  locations: new Set(),
  assets: new Set(),
  foreshadows: new Set(),
})

// 默认全选（用户可取消不需要的）
function initChecked() {
  for (let i = 0; i < props.result.characters.length; i++) checked.characters.add(i)
  for (let i = 0; i < props.result.relationships.length; i++) checked.relationships.add(i)
  for (let i = 0; i < props.result.locations.length; i++) checked.locations.add(i)
  for (let i = 0; i < props.result.assets.length; i++) checked.assets.add(i)
  for (let i = 0; i < props.result.foreshadows.length; i++) checked.foreshadows.add(i)
}
initChecked()

const tabs = computed(() => [
  { key: 'characters' as Tab, label: '角色', count: props.result.characters.length },
  { key: 'relationships' as Tab, label: '关系', count: props.result.relationships.length },
  { key: 'locations' as Tab, label: '地点', count: props.result.locations.length },
  { key: 'assets' as Tab, label: '资产', count: props.result.assets.length },
  { key: 'foreshadows' as Tab, label: '伏笔', count: props.result.foreshadows.length },
])

const totalChecked = computed(() =>
  checked.characters.size +
  checked.relationships.size +
  checked.locations.size +
  checked.assets.size +
  checked.foreshadows.size,
)

function toggleCheck(tab: Tab, idx: number) {
  const set = checked[tab]
  if (set.has(idx)) set.delete(idx)
  else set.add(idx)
  // 触发响应式（Set mutation 需重新赋值）
  checked[tab] = new Set(set)
}

function toggleAllTab(tab: Tab) {
  const items = props.result[tab]
  const set = checked[tab]
  if (set.size === items.length) {
    checked[tab] = new Set()
  } else {
    checked[tab] = new Set(items.map((_, i) => i))
  }
}

function handleConfirm() {
  emit('confirm', {
    characters: props.result.characters.filter((_, i) => checked.characters.has(i)),
    relationships: props.result.relationships.filter((_, i) => checked.relationships.has(i)),
    locations: props.result.locations.filter((_, i) => checked.locations.has(i)),
    assets: props.result.assets.filter((_, i) => checked.assets.has(i)),
    foreshadows: props.result.foreshadows.filter((_, i) => checked.foreshadows.has(i)),
  })
}

const roleTypeLabel: Record<string, string> = {
  protagonist: '主角',
  antagonist: '反派',
  supporting: '配角',
  minor: '龙套',
}
</script>

<template>
  <div class="preview-panel">
    <!-- 统计概览 -->
    <div class="stats-overview">
      <span>共提取 {{ result.stats.characters + result.stats.relationships + result.stats.locations + result.stats.assets + result.stats.foreshadows }} 项 · 已选 {{ totalChecked }}</span>
    </div>

    <!-- 标签页 -->
    <div class="tabs-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }} <span class="tab-count">{{ tab.count }}</span>
      </button>
    </div>

    <!-- 列表区 -->
    <div class="list-area">
      <!-- 角色 -->
      <template v-if="activeTab === 'characters'">
        <div v-if="result.characters.length === 0" class="empty-tab">未提取到角色</div>
        <template v-else>
          <div class="list-header">
            <button class="select-all-btn" @click="toggleAllTab('characters')">
              {{ checked.characters.size === result.characters.length ? '取消全选' : '全选' }}
            </button>
          </div>
          <div
            v-for="(ch, idx) in result.characters"
            :key="idx"
            class="item-card"
            :class="{ checked: checked.characters.has(idx) }"
            @click="toggleCheck('characters', idx)"
          >
            <span class="checkbox" :class="{ checked: checked.characters.has(idx) }">
              <Icon v-if="checked.characters.has(idx)" name="check" :size="14" />
            </span>
            <div class="item-body">
              <div class="item-title">{{ ch.name }}</div>
              <div class="item-desc">{{ ch.description }}</div>
              <div class="item-tags">
                <span v-if="ch.role_type" class="tag">{{ roleTypeLabel[ch.role_type] || ch.role_type }}</span>
                <span class="tag">重要性 {{ ch.importance_level }}</span>
                <span v-for="alias in ch.aliases" :key="alias" class="tag alias">{{ alias }}</span>
              </div>
            </div>
          </div>
        </template>
      </template>

      <!-- 关系 -->
      <template v-else-if="activeTab === 'relationships'">
        <div v-if="result.relationships.length === 0" class="empty-tab">未提取到关系</div>
        <template v-else>
          <div class="list-header">
            <button class="select-all-btn" @click="toggleAllTab('relationships')">
              {{ checked.relationships.size === result.relationships.length ? '取消全选' : '全选' }}
            </button>
          </div>
          <div
            v-for="(rel, idx) in result.relationships"
            :key="idx"
            class="item-card"
            :class="{ checked: checked.relationships.has(idx) }"
            @click="toggleCheck('relationships', idx)"
          >
            <span class="checkbox" :class="{ checked: checked.relationships.has(idx) }">
              <Icon v-if="checked.relationships.has(idx)" name="check" :size="14" />
            </span>
            <div class="item-body">
              <div class="item-title">{{ rel.source_name }} → {{ rel.target_name }}</div>
              <div class="item-desc">{{ rel.description }}</div>
              <div class="item-tags">
                <span class="tag">{{ rel.relation_type }}</span>
                <span class="tag" :class="rel.affinity_score >= 0 ? 'positive' : 'negative'">
                  亲密度 {{ rel.affinity_score }}
                </span>
              </div>
            </div>
          </div>
        </template>
      </template>

      <!-- 地点 -->
      <template v-else-if="activeTab === 'locations'">
        <div v-if="result.locations.length === 0" class="empty-tab">未提取到地点</div>
        <template v-else>
          <div class="list-header">
            <button class="select-all-btn" @click="toggleAllTab('locations')">
              {{ checked.locations.size === result.locations.length ? '取消全选' : '全选' }}
            </button>
          </div>
          <div
            v-for="(loc, idx) in result.locations"
            :key="idx"
            class="item-card"
            :class="{ checked: checked.locations.has(idx) }"
            @click="toggleCheck('locations', idx)"
          >
            <span class="checkbox" :class="{ checked: checked.locations.has(idx) }">
              <Icon v-if="checked.locations.has(idx)" name="check" :size="14" />
            </span>
            <div class="item-body">
              <div class="item-title">{{ loc.name }}</div>
              <div class="item-desc">{{ loc.description }}</div>
            </div>
          </div>
        </template>
      </template>

      <!-- 资产 -->
      <template v-else-if="activeTab === 'assets'">
        <div v-if="result.assets.length === 0" class="empty-tab">未提取到资产</div>
        <template v-else>
          <div class="list-header">
            <button class="select-all-btn" @click="toggleAllTab('assets')">
              {{ checked.assets.size === result.assets.length ? '取消全选' : '全选' }}
            </button>
          </div>
          <div
            v-for="(asset, idx) in result.assets"
            :key="idx"
            class="item-card"
            :class="{ checked: checked.assets.has(idx) }"
            @click="toggleCheck('assets', idx)"
          >
            <span class="checkbox" :class="{ checked: checked.assets.has(idx) }">
              <Icon v-if="checked.assets.has(idx)" name="check" :size="14" />
            </span>
            <div class="item-body">
              <div class="item-title">{{ asset.name }}</div>
              <div class="item-desc">{{ asset.description }}</div>
              <div class="item-tags">
                <span class="tag">重要性 {{ asset.importance_level }}</span>
              </div>
            </div>
          </div>
        </template>
      </template>

      <!-- 伏笔 -->
      <template v-else-if="activeTab === 'foreshadows'">
        <div v-if="result.foreshadows.length === 0" class="empty-tab">未提取到伏笔</div>
        <template v-else>
          <div class="list-header">
            <button class="select-all-btn" @click="toggleAllTab('foreshadows')">
              {{ checked.foreshadows.size === result.foreshadows.length ? '取消全选' : '全选' }}
            </button>
          </div>
          <div
            v-for="(fs, idx) in result.foreshadows"
            :key="idx"
            class="item-card"
            :class="{ checked: checked.foreshadows.has(idx) }"
            @click="toggleCheck('foreshadows', idx)"
          >
            <span class="checkbox" :class="{ checked: checked.foreshadows.has(idx) }">
              <Icon v-if="checked.foreshadows.has(idx)" name="check" :size="14" />
            </span>
            <div class="item-body">
              <div class="item-title">{{ fs.content }}</div>
              <div class="item-tags">
                <span class="tag">{{ fs.entry_type }}</span>
                <span class="tag" :class="fs.status === 'open' ? 'positive' : 'negative'">{{ fs.status === 'open' ? '开放' : '已闭合' }}</span>
                <span class="tag">强度 {{ fs.strength }}</span>
              </div>
            </div>
          </div>
        </template>
      </template>
    </div>

    <!-- 底部操作 -->
    <div class="panel-footer">
      <button class="btn-secondary" @click="emit('cancel')">取消</button>
      <button
        class="btn-primary"
        :disabled="totalChecked === 0"
        @click="handleConfirm"
      >
        <Icon name="check-badge" :size="15" />
        <span>确认入库 {{ totalChecked }} 项</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.preview-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.stats-overview {
  flex-shrink: 0;
  padding: 0.5rem 0;
  font-size: 0.8125rem;
  color: var(--text-secondary);
}

.tabs-bar {
  display: flex;
  gap: 0.25rem;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 0.5rem;
  margin-bottom: 0.5rem;
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.375rem 0.75rem;
  font-size: 0.8125rem;
  font-weight: 500;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid transparent;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tab-btn:hover {
  background: var(--hover-bg);
}

.tab-btn.active {
  background: rgba(var(--accent-500-rgb, 124, 58, 237), 0.1);
  color: var(--accent-500);
  border-color: rgba(var(--accent-500-rgb, 124, 58, 237), 0.2);
}

.tab-count {
  font-size: var(--text-xs);
  background: var(--bg-tertiary);
  padding: 0.0625rem 0.3125rem;
  border-radius: 0.625rem;
  color: var(--text-muted);
}

.tab-btn.active .tab-count {
  background: rgba(var(--accent-500-rgb, 124, 58, 237), 0.15);
  color: var(--accent-500);
}

.list-area {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-right: 0.25rem;
}

.list-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 0.375rem;
}

.select-all-btn {
  font-size: var(--text-xs);
  color: var(--text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
  text-decoration: underline;
}

.select-all-btn:hover {
  color: var(--accent-500);
}

.empty-tab {
  padding: 2rem;
  text-align: center;
  font-size: 0.8125rem;
  color: var(--text-muted);
}

.item-card {
  display: flex;
  gap: 0.625rem;
  padding: 0.625rem;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  margin-bottom: 0.375rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.item-card:hover {
  background: var(--hover-bg);
}

.item-card.checked {
  border-color: rgba(var(--accent-500-rgb, 124, 58, 237), 0.3);
  background: rgba(var(--accent-500-rgb, 124, 58, 237), 0.04);
}

.checkbox {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.125rem;
  height: 1.125rem;
  border: 1.5px solid var(--border-color);
  border-radius: 0.1875rem;
  background: var(--bg-canvas);
  color: white;
  flex-shrink: 0;
  margin-top: 0.0625rem;
  transition: all 0.15s ease;
}

.checkbox.checked {
  border-color: var(--accent-500);
  background: var(--accent-500);
}

.item-body {
  flex: 1;
  min-width: 0;
}

.item-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.1875rem;
}

.item-desc {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 0.3125rem;
}

.item-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.tag {
  display: inline-flex;
  align-items: center;
  padding: 0.0625rem 0.375rem;
  font-size: var(--text-xs);
  background: var(--bg-tertiary);
  color: var(--text-muted);
  border-radius: 0.25rem;
  white-space: nowrap;
}

.tag.positive {
  background: rgba(5, 150, 105, 0.08);
  color: #059669;
}

.tag.negative {
  background: rgba(220, 38, 38, 0.08);
  color: var(--danger);
}

.tag.alias {
  font-style: italic;
}

.panel-footer {
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color);
  margin-top: 0.5rem;
}

.btn-primary,
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  font-size: 0.8125rem;
  font-weight: 500;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}

.btn-primary {
  background: var(--accent-500);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-600);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--bg-canvas);
  color: var(--text-primary);
  border-color: var(--border-color);
}

.btn-secondary:hover {
  background: var(--hover-bg);
}
</style>
