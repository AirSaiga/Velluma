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
  <div class="rich-text-editor border border-[var(--border-color)] rounded-xl bg-[var(--bg-tertiary)] overflow-hidden flex flex-col h-full shadow-sm transition-shadow hover:shadow-md" :class="{ 'opacity-60 pointer-events-none': disabled }">
    <div v-if="editor && !disabled" class="toolbar flex items-center gap-1 p-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)] overflow-x-auto flex-wrap">
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
      <button 
        @click="toggleUnderline" 
        :class="{ 'is-active': editor.isActive('underline') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="下划线"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3v7a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3"></path><line x1="4" y1="21" x2="20" y2="21"></line></svg>
      </button>
      <button 
        @click="toggleStrike" 
        :class="{ 'is-active': editor.isActive('strike') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="删除线"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.3 4.9c-2.3-.6-4.4-1-6.2-.9-2.7 0-5.3.7-5.3 3.6 0 1.5 1.8 3.3 3.6 3.9h.2"></path><path d="M8.7 19.1c2.3.6 4.4 1 6.2.9 2.7 0 5.3-.7 5.3-3.6 0-1.5-1.8-3.3-3.6-3.9h-.2"></path><line x1="3" y1="12" x2="21" y2="12"></line></svg>
      </button>
      <div class="w-px h-4 bg-[var(--border-color)] mx-1"></div>
      <div class="relative group">
        <button 
          class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors flex items-center gap-1"
          title="文字颜色"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16"></path><path d="m4 12 4-8 4 8"></path><path d="m18 12 4 8-4 8"></path></svg>
          <span class="w-3 h-3 rounded-full border border-[var(--border-color)]" :style="{ backgroundColor: textColor }"></span>
        </button>
        <div class="absolute top-full left-0 mt-1 p-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg shadow-lg grid grid-cols-5 gap-1 z-50 hidden group-hover:grid">
          <button v-for="color in ['#000000', '#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#FF00FF', '#00FFFF', '#FFA500', '#800080', '#FFC0CB']" 
            :key="color"
            @click="textColor = color; setTextColor(color)"
            class="w-6 h-6 rounded border border-[var(--border-color)] hover:scale-110 transition-transform"
            :style="{ backgroundColor: color }"
            :title="color"
          ></button>
        </div>
      </div>
      <div class="relative group">
        <button 
          class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors flex items-center gap-1"
          title="背景高亮"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 11-6 6v3h9l3-3"></path><path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"></path></svg>
          <span class="w-3 h-3 rounded-full border border-[var(--border-color)]" :style="{ backgroundColor: highlightColor }"></span>
        </button>
        <div class="absolute top-full left-0 mt-1 p-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg shadow-lg grid grid-cols-5 gap-1 z-50 hidden group-hover:grid">
          <button v-for="color in ['#FFFF00', '#00FF00', '#00FFFF', '#FFA500', '#FF00FF', '#FF9999', '#99FF99', '#9999FF', '#FFFFFF', '#000000']" 
            :key="color"
            @click="highlightColor = color; setHighlightColor(color)"
            class="w-6 h-6 rounded border border-[var(--border-color)] hover:scale-110 transition-transform"
            :style="{ backgroundColor: color }"
            :title="color"
          ></button>
        </div>
      </div>
      <div class="w-px h-4 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="setTextAlign('left')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'left' }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="左对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="9" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('center')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'center' }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="居中"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="18" y1="12" x2="6" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('right')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'right' }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="右对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="15" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line></svg>
      </button>
      <button 
        @click="setTextAlign('justify')" 
        :class="{ 'is-active': editor.isActive({ textAlign: 'justify' }) }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        title="两端对齐"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="3" y2="12"></line><line x1="21" y1="18" x2="3" y2="18"></line><line x1="21" y1="6" x2="21" y2="18"></line></svg>
      </button>
      <div class="w-px h-4 bg-[var(--border-color)] mx-1"></div>
      <button 
        @click="toggleSuperscript" 
        :class="{ 'is-active': editor.isActive('superscript') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-xs font-bold"
        title="上标"
      >
        X<sup>2</sup>
      </button>
      <button 
        @click="toggleSubscript" 
        :class="{ 'is-active': editor.isActive('subscript') }"
        class="p-1.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-xs font-bold"
        title="下标"
      >
        X<sub>2</sub>
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
