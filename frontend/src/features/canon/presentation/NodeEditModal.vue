<script setup lang="ts">
/**
 * Canon 节点编辑弹窗（V4.0 新建）。
 *
 * 支持创建/编辑/删除节点。
 * 关键字段：
 * - canon_text: 作者脑中的完整真相（private 时不许泄露到正文）
 * - public_text: 读者目前看到的描述
 * - visibility: public / private / partial
 * - 揭示计划 + 预期章节
 * - HOOK 类型特有：strength / status / bury_style
 */
import { ref, computed, watchEffect } from 'vue'
import { useCanon, NODE_TYPE_LABELS, VISIBILITY_LABELS } from '../composables/useCanon'
import type { CanonNode, CanonNodeType, CanonVisibility } from '../../../services/api/domain/canon.api'

const props = defineProps<{
  bookId: string
  node: CanonNode | null
  defaultType: CanonNodeType
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', node: CanonNode): void
}>()

const canon = useCanon()
const isEditing = computed(() => !!props.node)
const saving = ref(false)
const error = ref<string | null>(null)

// 表单状态
const type = ref<CanonNodeType>(props.defaultType)
const label = ref('')
const canon_text = ref('')
const public_text = ref('')
const visibility = ref<CanonVisibility>('public')
const reveal_plan = ref('')
const expected_reveal_chapter = ref<number | null>(null)
const tags = ref<string[]>([])
const tagsInput = ref('')
// HOOK 特有
const hookStrength = ref(5)
const hookStatus = ref<'open' | 'callback' | 'echoed' | 'subverted'>('open')
const hookBuryStyle = ref<'explicit' | 'implicit' | 'half' | 'denial'>('implicit')

watchEffect(() => {
  if (props.node) {
    type.value = props.node.type
    label.value = props.node.label
    canon_text.value = props.node.canon_text || ''
    public_text.value = props.node.public_text || ''
    visibility.value = props.node.visibility
    reveal_plan.value = props.node.reveal_plan || ''
    expected_reveal_chapter.value = props.node.expected_reveal_chapter
    tags.value = props.node.tags || []
    tagsInput.value = (props.node.tags || []).join(', ')
    if (props.node.type === 'hook') {
      hookStrength.value = props.node.metadata?.strength || 5
      hookStatus.value = props.node.metadata?.status || 'open'
      hookBuryStyle.value = props.node.metadata?.bury_style || 'implicit'
    }
  }
})

const isHook = computed(() => type.value === 'hook')

async function handleSave() {
  if (!label.value.trim()) {
    error.value = 'label 不能为空'
    return
  }
  saving.value = true
  error.value = null
  try {
    // 解析 tags
    const parsedTags = tagsInput.value
      .split(',')
      .map(t => t.trim())
      .filter(Boolean)

    // HOOK 特有字段塞到 metadata
    const metadata: Record<string, any> = {}
    if (isHook.value) {
      metadata.strength = hookStrength.value
      metadata.status = hookStatus.value
      metadata.bury_style = hookBuryStyle.value
    }

    if (isEditing.value && props.node) {
      const updated = await canon.updateNode(props.bookId, props.node.id, {
        type: type.value,
        label: label.value,
        canon_text: canon_text.value,
        public_text: public_text.value,
        visibility: visibility.value,
        reveal_plan: reveal_plan.value,
        expected_reveal_chapter: expected_reveal_chapter.value,
        tags: parsedTags,
        metadata,
      })
      emit('saved', updated)
    } else {
      const created = await canon.createNode(props.bookId, {
        book_id: props.bookId,
        type: type.value,
        label: label.value,
        canon_text: canon_text.value,
        public_text: public_text.value,
        visibility: visibility.value,
        reveal_plan: reveal_plan.value,
        expected_reveal_chapter: expected_reveal_chapter.value,
        tags: parsedTags,
        metadata,
      })
      emit('saved', created)
    }
  } catch (e: any) {
    error.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  if (!props.node) return
  if (!confirm(`删除节点 [${props.node.label}]？`)) return
  saving.value = true
  try {
    await canon.deleteNode(props.bookId, props.node.id)
    emit('close')
  } catch (e: any) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <header class="modal-header">
        <h2>{{ isEditing ? '编辑节点' : '新建节点' }}</h2>
        <button class="close-btn" @click="emit('close')">×</button>
      </header>

      <div class="modal-body">
        <div class="form-row">
          <label>类型</label>
          <select v-model="type" :disabled="isEditing">
            <option v-for="(lbl, key) in NODE_TYPE_LABELS" :key="key" :value="key">{{ lbl }}</option>
          </select>
        </div>

        <div class="form-row">
          <label>名称（label）<span class="required">*</span></label>
          <input v-model="label" placeholder="如：兰星" />
        </div>

        <div class="form-row">
          <label>可见性</label>
          <select v-model="visibility">
            <option v-for="(lbl, key) in VISIBILITY_LABELS" :key="key" :value="key">{{ lbl }}</option>
          </select>
          <p class="hint">
            public=读者已知 / private=作者私有（绝不许泄露到正文） / partial=部分揭示
          </p>
        </div>

        <div class="form-row">
          <label>作者脑中的真相（canon_text）</label>
          <textarea v-model="canon_text" rows="3" placeholder="作者脑中的完整真相"></textarea>
          <p class="hint" v-if="visibility === 'private'">
            ★ private 节点：这是作者脑中的真相，AI 生成时绝不许在正文直接说出，但可作为角色隐藏动机影响行为
          </p>
        </div>

        <div class="form-row" v-if="visibility !== 'public'">
          <label>读者目前看到的（public_text）</label>
          <textarea v-model="public_text" rows="2" placeholder="读者目前在正文看到的描述（可能截断/伪装）"></textarea>
        </div>

        <div class="form-row">
          <label>揭示计划（可选）</label>
          <input v-model="reveal_plan" placeholder="如：第 30 章通过老人回忆揭示" />
        </div>

        <div class="form-row">
          <label>预期揭示章节（可选）</label>
          <input
            v-model.number="expected_reveal_chapter"
            type="number"
            min="1"
            placeholder="如：30"
          />
        </div>

        <div class="form-row">
          <label>标签（逗号分隔）</label>
          <input v-model="tagsInput" placeholder="如：主角, 暗元素, 复仇" />
        </div>

        <!-- HOOK 特有字段 -->
        <template v-if="isHook">
          <div class="hook-section">
            <h3>伏笔专属字段</h3>
            <div class="form-row">
              <label>强度（1-10）</label>
              <input v-model.number="hookStrength" type="number" min="1" max="10" />
            </div>
            <div class="form-row">
              <label>状态</label>
              <select v-model="hookStatus">
                <option value="open">open（未回收）</option>
                <option value="callback">callback（已回收）</option>
                <option value="echoed">echoed（已呼应）</option>
                <option value="subverted">subverted（被反转）</option>
              </select>
            </div>
            <div class="form-row">
              <label>埋设手法</label>
              <select v-model="hookBuryStyle">
                <option value="explicit">explicit（明确提及）</option>
                <option value="implicit">implicit（隐晦暗示）</option>
                <option value="half">half（半埋，故意说一半）</option>
                <option value="denial">denial（角色否认）</option>
              </select>
            </div>
          </div>
        </template>

        <div v-if="error" class="error">{{ error }}</div>
      </div>

      <footer class="modal-footer">
        <button v-if="isEditing" class="btn-danger" @click="handleDelete" :disabled="saving">删除</button>
        <div class="spacer"></div>
        <button class="btn-secondary" @click="emit('close')" :disabled="saving">取消</button>
        <button class="btn-primary" @click="handleSave" :disabled="saving">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal-card {
  background: var(--bg-primary);
  border-radius: 0.5rem;
  width: 90%;
  max-width: 560px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-color);
}
.modal-header h2 {
  font-size: 1rem;
  margin: 0;
}
.close-btn {
  background: transparent;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--text-muted);
  line-height: 1;
}
.modal-body {
  padding: 1rem 1.25rem;
  overflow-y: auto;
  flex: 1;
}
.form-row {
  margin-bottom: 0.875rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.form-row label {
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-secondary);
}
.required {
  color: #dc2626;
}
.form-row input,
.form-row select,
.form-row textarea {
  padding: 0.5rem 0.625rem;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  background: var(--bg-primary);
  font-family: inherit;
  resize: vertical;
}
.form-row input:focus,
.form-row select:focus,
.form-row textarea:focus {
  outline: none;
  border-color: var(--accent-500);
}
.hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin: 0;
}
.hook-section {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px dashed var(--border-color);
}
.hook-section h3 {
  font-size: 0.8125rem;
  margin: 0 0 0.75rem;
  color: #dc2626;
}
.error {
  color: #dc2626;
  font-size: 0.75rem;
  margin-top: 0.5rem;
}
.modal-footer {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--border-color);
}
.spacer { flex: 1; }
.btn-primary, .btn-secondary, .btn-danger {
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  cursor: pointer;
  border: 1px solid var(--border-color);
}
.btn-primary {
  background: var(--accent-500);
  color: white;
  border-color: var(--accent-500);
}
.btn-secondary { background: var(--bg-primary); }
.btn-danger { background: transparent; color: #dc2626; }
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
