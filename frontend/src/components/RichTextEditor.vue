<script setup>
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import TextAlign from '@tiptap/extension-text-align'
import Underline from '@tiptap/extension-underline'
import Strike from '@tiptap/extension-strike'
import { Color, BackgroundColor } from '@tiptap/extension-text-style'
import Highlight from '@tiptap/extension-highlight'
import Subscript from '@tiptap/extension-subscript'
import Superscript from '@tiptap/extension-superscript'
import { watch, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  modelValue: {
    type: String,
    default: '',
  },
  placeholder: {
    type: String,
    default: '开始写作...',
  },
  disabled: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue'])

const textColor = ref('#000000')
const highlightColor = ref('#FFFF00')

const editor = useEditor({
  content: props.modelValue,
  extensions: [
    StarterKit,
    Placeholder.configure({
      placeholder: props.placeholder,
    }),
    TextAlign.configure({
      types: ['heading', 'paragraph'],
    }),
    Underline,
    Strike,
    Color,
    BackgroundColor,
    Highlight.configure({
      multicolor: true,
    }),
    Subscript,
    Superscript,
  ],
  editorProps: {
    attributes: {
      class: 'prose prose-lg max-w-none mx-auto focus:outline-none min-h-[560px] px-10 py-8 text-[var(--text-primary)]',
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
const toggleUnderline = () => editor.value.chain().focus().toggleUnderline().run()
const toggleStrike = () => editor.value.chain().focus().toggleStrike().run()
const toggleHeading = (level) => editor.value.chain().focus().toggleHeading({ level }).run()

const setTextAlign = (align) => editor.value.chain().focus().setTextAlign(align).run()
const setTextColor = (color) => editor.value.chain().focus().setColor(color).run()
const setHighlightColor = (color) => editor.value.chain().focus().toggleHighlight({ color }).run()
const toggleSubscript = () => editor.value.chain().focus().toggleSubscript().run()
const toggleSuperscript = () => editor.value.chain().focus().toggleSuperscript().run()

let contentBuffer = ''

const insertContent = (content) => {
  if (editor.value) {
    contentBuffer += content
    const buffer = contentBuffer.trim()
    
    const hasParagraphBreak = buffer.includes('。</p>') || buffer.includes('！</p>') || buffer.includes('？</p>') || 
                             buffer.includes('。\n') || buffer.includes('！\n') || buffer.includes('？\n') ||
                             buffer.includes('。</') || buffer.includes('！</') || buffer.includes('？</')
    
    if (hasParagraphBreak) {
      if (buffer.includes('<')) {
        editor.value.commands.insertContent(contentBuffer)
      } else {
        const paragraphs = buffer.split(/\n\n+/)
        const htmlContent = paragraphs.map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('')
        editor.value.commands.insertContent(htmlContent)
      }
      contentBuffer = ''
    }
  }
}

const flushBuffer = () => {
  if (contentBuffer && editor.value) {
    const buffer = contentBuffer.trim()
    if (buffer) {
      if (buffer.includes('<')) {
        editor.value.commands.insertContent(buffer)
      } else {
        const paragraphs = buffer.split(/\n\n+/)
        const htmlContent = paragraphs.map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('')
        editor.value.commands.insertContent(htmlContent)
      }
    }
    contentBuffer = ''
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
  flushBuffer,
  editor
})
</script>

<template>
  <div class="rich-text-editor bg-white overflow-hidden flex flex-col h-full" :class="{ 'opacity-60 pointer-events-none': disabled }">
    <div v-if="editor && !disabled" class="toolbar flex items-center gap-0.5 px-3 py-1.5 bg-white border-b border-[var(--border-color)] overflow-x-auto whitespace-nowrap">
      <button 
        @click="toggleBold" 
        :class="{ 'is-active': editor.isActive('bold') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="加粗"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h8a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path><path d="M6 12h9a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path></svg>
      </button>
      <button 
        @click="toggleItalic" 
        :class="{ 'is-active': editor.isActive('italic') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="斜体"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="4" x2="10" y2="4"></line><line x1="14" y1="20" x2="5" y2="20"></line><line x1="15" y1="4" x2="9" y2="20"></line></svg>
      </button>
      <button 
        @click="toggleUnderline" 
        :class="{ 'is-active': editor.isActive('underline') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="下划线"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3v7a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3"></path><line x1="4" y1="21" x2="20" y2="21"></line></svg>
      </button>
      <button 
        @click="toggleStrike" 
        :class="{ 'is-active': editor.isActive('strike') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="删除线"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.3 4.9c-2.3-.6-4.4-1-6.2-.9-2.7 0-5.3.7-5.3 3.6 0 1.5 1.8 3.3 3.6 3.9h.2"></path><path d="M8.7 19.1c2.3.6 4.4 1 6.2.9 2.7 0 5.3-.7 5.3-3.6 0-1.5-1.8-3.3-3.6-3.9h-.2"></path><line x1="3" y1="12" x2="21" y2="12"></line></svg>
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <label class="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-[var(--hover-bg)] transition-colors cursor-pointer" title="文字颜色">
        <input
          type="color"
          v-model="textColor"
          @input="setTextColor($event.target.value)"
          class="w-4 h-4 p-0 border-0 bg-transparent cursor-pointer"
        />
      </label>
      <label class="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-[var(--hover-bg)] transition-colors cursor-pointer" title="背景高亮">
        <input
          type="color"
          v-model="highlightColor"
          @input="setHighlightColor($event.target.value)"
          class="w-4 h-4 p-0 border-0 bg-transparent cursor-pointer"
        />
      </label>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="setTextAlign('left')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'left' }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="左对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="9" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('center')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'center' }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="居中"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="18" y1="12" x2="6" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('right')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'right' }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="右对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="15" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('justify')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'justify' }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="两端对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="3" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line><line x1="21" y1="6" x2="21" y2="18"></line></svg>
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="toggleSuperscript" 
        :class="{ 'is-active': editor.isActive('superscript') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="上标"
      >
        X<sup>2</sup>
      </button>
      <button 
        @click="toggleSubscript" 
        :class="{ 'is-active': editor.isActive('subscript') }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="下标"
      >
        X<sub>2</sub>
      </button>
      <div class="w-px h-3 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="toggleHeading(1)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 1 }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 1"
      >
        H1
      </button>
      <button 
        @click="toggleHeading(2)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 2 }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 2"
      >
        H2
      </button>
      <button 
        @click="toggleHeading(3)" 
        :class="{ 'is-active': editor.isActive('heading', { level: 3 }) }"
        class="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-[10px] font-bold"
        title="标题 3"
      >
        H3
      </button>
    </div>
    
    <editor-content :editor="editor" class="flex-1 overflow-y-auto custom-scrollbar" />
  </div>
</template>

<style scoped>
.rich-text-editor .is-active {
  background-color: rgba(99, 102, 241, 0.12);
  color: var(--accent-600);
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
  font-family: 'Songti SC', 'STSong', 'Noto Serif SC', 'Source Han Serif SC', Georgia, serif;
  font-size: 1.15rem;
  line-height: 1.95;
}
:deep(.ProseMirror p.is-editor-empty:first-child::before) {
  color: var(--text-muted);
  content: attr(data-placeholder);
  float: left;
  height: 0;
  pointer-events: none;
}
</style>
