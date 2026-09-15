<script setup lang="ts">
/**
 * 批量导入事件（TSV 粘贴）。
 * 复用 engine/bulkImport.ts 的 parseTsv（纯函数，错误收集不抛异常）。
 * 一次粘贴导入 ≥50 条。
 */
import { ref, computed } from 'vue'
import ModalShell from '../../../components/ModalShell.vue'
import { parseTsv, SAMPLE_TSV } from '../engine/bulkImport'
import { useWorld } from '../composables/useWorld'

const props = defineProps<{ bookId: string }>()
const emit = defineEmits<{ done: []; cancel: [] }>()

const { createEvent } = useWorld()

const text = ref(SAMPLE_TSV)
const result = computed(() => parseTsv(text.value))
const importing = ref(false)
const importMsg = ref('')

async function doImport() {
  importing.value = true
  let ok = 0
  for (const row of result.value.rows) {
    try {
      await createEvent(props.bookId, {
        event_type: row.event_type,
        time_start: row.time_start,
        time_end: row.time_end,
        note: row.note,
        tags: row.tags,
        location_id: row.location_id || null,
        participant_ids: row.participant_ids,
      })
      ok += 1
    } catch {
      // 单条失败继续（部分成功）
    }
  }
  importing.value = false
  importMsg.value = `已导入 ${ok} 条${result.value.errors.length ? `，解析错误 ${result.value.errors.length} 条` : ''}`
  if (ok > 0 && result.value.errors.length === 0) {
    setTimeout(() => emit('done'), 800)
  }
}
</script>

<template>
  <ModalShell
    title="批量导入事件（TSV）"
    subtitle="第一行中文表头，Tab 分隔，一行一事件。支持：类型/开始年/开始月/开始日/结束年/备注/标签/地点ID/人物ID/X坐标/Y坐标"
    width="620px"
    @close="emit('cancel')"
  >
    <textarea v-model="text" class="bi-textarea" spellcheck="false"></textarea>

    <div class="bi-preview">
      <div v-if="result.rows.length" class="bi-ok">
        ✓ 解析成功 {{ result.rows.length }} 条
      </div>
      <div v-if="result.errors.length" class="bi-err">
        ⚠ {{ result.errors.length }} 条解析错误（行号：
        {{ result.errors.slice(0, 5).map((e) => e.line).join(', ') }}{{ result.errors.length > 5 ? '…' : '' }}）
      </div>
      <div v-if="importMsg" class="bi-msg">{{ importMsg }}</div>
    </div>

    <template #footer>
      <button class="wbtn" @click="emit('cancel')">取消</button>
      <button class="wbtn wbtn--primary btn-primary-instrument" :disabled="importing || !result.rows.length" @click="doImport">
        {{ importing ? '导入中…' : `导入 ${result.rows.length} 条` }}
      </button>
    </template>
  </ModalShell>
</template>

<style scoped>
.bi-textarea {
  width: 100%;
  box-sizing: border-box;
  height: 200px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-family: ui-monospace, monospace;
  font-size: var(--text-xs);
  resize: vertical;
  transition: border-color 0.15s;
}
.bi-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
  box-shadow: var(--ring-soft);
}
.bi-preview {
  margin-top: 12px;
  font-size: var(--text-xs);
}
.bi-ok {
  color: var(--ok);
}
.bi-err {
  color: var(--danger);
  margin-top: 3px;
}
.bi-msg {
  color: var(--accent-500);
  margin-top: 3px;
  font-weight: 600;
}

/* footer 按钮（与 WorldView 同一套 wbtn 体系） */
.wbtn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 16px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-canvas);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease-out;
}
.wbtn:hover:not(:disabled) {
  border-color: var(--accent-500);
  color: var(--accent-500);
  background: color-mix(in srgb, var(--accent-500) 6%, transparent);
}
.wbtn:disabled {
  opacity: 0.5;
  cursor: default;
}
.wbtn--primary {
}
.wbtn--primary:hover:not(:disabled) {
  background: var(--accent-600);
  border-color: var(--accent-600);
  color: var(--bg-canvas);
  box-shadow: var(--glow-accent);
  transform: translateY(-1px);
}
</style>
