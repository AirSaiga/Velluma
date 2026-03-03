<script setup>
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import { watch, onBeforeUnmount } from 'vue'

const props = defineProps({
  modelValue: {
    type: String,
    default: '',
  },
  placeholder: {
    type: String,
    default: '开始写作...',
  },
})

const emit = defineEmits(['update:modelValue'])

const editor = useEditor({
  content: props.modelValue,
  extensions: [
    StarterKit,
    Placeholder.configure({
      placeholder: props.placeholder,
    }),
  ],
  editorProps: {
    attributes: {
      class: 'prose prose-sm sm:prose lg:prose-lg xl:prose-2xl mx-auto focus:outline-none min-h-[300px] px-4 py-2 text-[var(--text-primary)]',
    },
  },
  onUpdate: ({ editor }) => {
    emit('update:modelValue', editor.getHTML())
  },
})

watch(() => props.modelValue, (newValue) => {
  const isSame = editor.value.getHTML() === newValue
  if (isSame) {
    return
  }
  editor.value.commands.setContent(newValue, false)
})

onBeforeUnmount(() => {
  editor.value.destroy()
})

const toggleBold = () => editor.value.chain().focus().toggleBold().run()
const toggleItalic = () => editor.value.chain().focus().toggleItalic().run()
const toggleHeading = (level) => editor.value.chain().focus().toggleHeading({ level }).run()

const insertContent = (content) => {
  if (editor.value) {
    editor.value.commands.insertContent(content)
  }
}

const clearContent = () => {
  if (editor.value) {
    editor.value.commands.clearContent()
  }
}

defineExpose({
  insertContent,
  clearContent,
  editor
})
</script>

<template>
  <div class="rich-text-editor border border-[var(--border-color)] rounded-xl bg-[var(--bg-tertiary)] overflow-hidden flex flex-col h-full shadow-sm transition-shadow hover:shadow-md">
    <div v-if="editor" class="toolbar flex items-center gap-1 p-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)] overflow-x-auto">
      <button 
        @click="toggleBold" 
        :class="{ 'is-active': editor.isActive('bold') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="加粗"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h8a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path><path d="M6 12h9a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path></svg>
      </button>
      <button 
        @click="toggleItalic" 
        :class="{ 'is-active': editor.isActive('italic') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="斜体"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="4" x2="10" y2="4"></line><line x1="14" y1="20" x2="5" y2="20"></line><line x1="15" y1="4" x2="9" y2="20"></line></svg>
      </button>
      <div class="w-px h-4 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="toggleHeading(1)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 1 }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-sm font-bold"
        title="标题 1"
      >
        H1
      </button>
      <button 
        @click="toggleHeading(2)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 2 }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-sm font-bold"
        title="标题 2"
      >
        H2
      </button>
      <button 
        @click="toggleHeading(3)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 3 }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-sm font-bold"
        title="标题 3"
      >
        H3
      </button>
    </div>
    
    <editor-content :editor="editor" class="flex-1 overflow-y-auto p-4 custom-scrollbar" />
  </div>
</template>

<style scoped>
.rich-text-editor .is-active {
  background-color: var(--primary-color, #3b82f6);
  color: white;
}

/* Custom Scrollbar for Editor Content */
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background-color: var(--border-color);
  border-radius: 3px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background-color: var(--text-muted);
}

/* Tiptap Prose Customization */
:deep(.ProseMirror) {
  height: 100%;
  outline: none;
}
:deep(.ProseMirror p.is-editor-empty:first-child::before) {
  color: var(--text-muted);
  content: attr(data-placeholder);
  float: left;
  height: 0;
  pointer-events: none;
}
</style>
