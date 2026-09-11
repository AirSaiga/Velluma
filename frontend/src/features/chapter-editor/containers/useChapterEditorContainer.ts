import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { chapterApi, generateApi } from '../../../services/api'
import { reviewApi, type CritiqueItem } from '../../../services/api/domain/review.api'
import type { ApiConfig, Chapter, Character } from '../../../types'
import { useChapterPublisher } from './useChapterPublisher'
import { useChapterAssets } from './useChapterAssets'
import { saveChapterDraft } from '../useChapterDraft'
import type { EntityFocusPayload } from '../../../shared/types'

// V3.1 清理：旧双轨生成路径（startGenerate → 节拍预览弹窗 → 双轨 SSE）已移除。
// 章节生成统一由 generation 特性的 useGenerationSession（Inspector「本章」tab）驱动。
// 本容器只保留编辑器自身职责：内容编辑、发布、灵感、格式整理/选区优化、角色/资产勾选。
export interface ChapterEditorContainerProps {
  selectedChapter: Chapter | null
  characters: Character[]
  apiConfig: ApiConfig
  metaCollapsed?: boolean
}

type ChapterEditorEmit = (event: 'update-chapter' | 'update-meta-collapsed' | 'refresh-characters' | 'editor-entity-focus', ...args: any[]) => void

export function useChapterEditorContainer(props: ChapterEditorContainerProps, emit: ChapterEditorEmit) {
  const { showToast } = useToast()
  const { show: showConfirm } = useConfirmDialog()

  const publisher = useChapterPublisher(emit)
  const assets = useChapterAssets()

  const chapterSummary = computed(() => publisher.chapterSummary.value)
  const isEditorDisabled = computed(() => publisher.isPublishing.value)
  const selectedChapter = computed(() => props.selectedChapter)

  function handleEditorEntityFocus(payload: EntityFocusPayload) {
    emit('editor-entity-focus', payload)
  }

  // 落库统一入口：chapterId 由调用方快照传入（不在触发时刻读 selectedChapter）——
  // 防抖回调触发时若已切章，仍写回调度时的原章节，修切章串文竞态。
  function updateChapter(chapterId: string, updates: Record<string, any>) {
    emit('update-chapter', chapterId, updates)
  }

  function handleTitleInput(e: Event) {
    const target = e.target as HTMLInputElement
    scheduleMetaUpdate({ title: target.value })
  }

  function handleAssetsSchemaInput(e: Event) {
    const target = e.target as HTMLTextAreaElement
    scheduleMetaUpdate({ chapter_assets_schema: target.value })
  }

  let metaUpdateTimeout: ReturnType<typeof setTimeout> | undefined
  // 挂起的元信息更新：调度时快照章节 id；同窗多次调用按字段合并（标题+大纲不互相覆盖）
  let metaPending: { chapterId: string; updates: Record<string, any> } | null = null
  function scheduleMetaUpdate(updates: Record<string, any>) {
    const chapterId = selectedChapter.value?.id
    if (!chapterId) return
    clearTimeout(metaUpdateTimeout)
    metaPending = metaPending && metaPending.chapterId === chapterId
      ? { chapterId, updates: { ...metaPending.updates, ...updates } }
      : { chapterId, updates }
    metaUpdateTimeout = setTimeout(() => {
      const p = metaPending
      metaPending = null
      metaUpdateTimeout = undefined
      if (p) updateChapter(p.chapterId, p.updates)
    }, 500)
  }

  // 保存状态反馈已上移到 WorkspaceView（真实落库发生地），经 props 下传 View。
  // 此处不再维护（旧实现声明后从未赋值，是死代码）。

  const isFormatting = ref(false)
  const editorRef = ref<any>(null)
  function setEditorRef(editor: any) {
    editorRef.value = editor
  }

  function toggleCharacter(charId: string) {
    if (!selectedChapter.value) return
    const chapterId = selectedChapter.value.id
    const currentIds = selectedChapter.value.character_ids || []
    const newCharacterIds = currentIds.includes(charId)
      ? currentIds.filter(id => id !== charId)
      : [...currentIds, charId]
    updateChapter(chapterId, { character_ids: newCharacterIds })
    chapterApi.updateEntities(chapterId, newCharacterIds).catch(err => {
      console.error('更新章节角色关联失败:', err)
      // 失败不能静默：UI 勾选已变但实际未保存 → 提示 + 回滚勾选态
      showToast('更新章节角色关联失败：' + (err?.message || '未知错误'), 'error')
      if (selectedChapter.value?.id === chapterId) {
        updateChapter(chapterId, { character_ids: currentIds })
      }
    })
  }

  let updateTimeout: ReturnType<typeof setTimeout> | undefined
  let contentPending: { chapterId: string; updates: Record<string, any> } | null = null
  // NLE-ADF 2.0/3.0：落库前剥除幽灵草稿与细纲胶囊——两者都是"未确认 AI 中间态"
  // （幽灵 Esc 可蒸发；细纲扩写未落笔），1s 防抖落库撞上其在屏时不能进库
  // （刷新后复活 = 事故）。细纲胶囊连速记文本一起剥除（数据库永远只有正文）。
  // 只改 outgoing 副本，绝不动编辑器文档（画布上正常存活）。
  function stripGhostDraftHtml(html: string): string {
    if (!html.includes('data-ghost-draft') && !html.includes('data-outline-note')) return html
    const doc = new DOMParser().parseFromString(html, 'text/html')
    doc.querySelectorAll('[data-ghost-draft]').forEach((el) => el.remove())
    doc.querySelectorAll('[data-outline-note]').forEach((el) => el.remove())
    return doc.body.innerHTML
  }
  function handleContentUpdate(content: string) {
    const chapterId = selectedChapter.value?.id
    if (!chapterId) return
    clearTimeout(updateTimeout)
    const cleaned = stripGhostDraftHtml(content)
    // 本地草稿兜底：防抖窗口内即写 localStorage（断网/关窗/保存失败均可恢复）；
    // 落库成功后由 WorkspaceView.handleUpdateChapter 清除。
    saveChapterDraft(chapterId, cleaned)
    contentPending = { chapterId, updates: { content_text: cleaned, draft_text: cleaned } }
    updateTimeout = setTimeout(() => {
      const p = contentPending
      contentPending = null
      updateTimeout = undefined
      if (p) updateChapter(p.chapterId, p.updates)
    }, 1000)
  }

  /** 立即冲刷挂起的防抖保存（切章/卸载前调用；快照 id 保证写回原章节）。 */
  function flushPendingSaves() {
    if (metaUpdateTimeout) { clearTimeout(metaUpdateTimeout); metaUpdateTimeout = undefined }
    if (updateTimeout) { clearTimeout(updateTimeout); updateTimeout = undefined }
    if (metaPending) { const p = metaPending; metaPending = null; updateChapter(p.chapterId, p.updates) }
    if (contentPending) { const p = contentPending; contentPending = null; updateChapter(p.chapterId, p.updates) }
  }

  const localMetaCollapsed = ref(props.metaCollapsed ?? false)
  function toggleMetaCollapsed() {
    localMetaCollapsed.value = !localMetaCollapsed.value
    emit('update-meta-collapsed', localMetaCollapsed.value)
  }

  function getMetaCollapsedLabel() {
    return localMetaCollapsed.value ? '展开信息' : '收起信息'
  }

  function isCharacterSelected(charId: string) {
    return selectedChapter.value?.character_ids?.includes(charId) || false
  }

  const showInspirationModal = ref(false)
  const inspirationActiveCharacterIds = ref<string[]>([])

  function openInspirationModal() {
    if (!selectedChapter.value) return
    const charIds = props.characters
      .filter(char => selectedChapter.value?.character_ids?.includes(char.id))
      .map(char => char.id)
    inspirationActiveCharacterIds.value = charIds
    showInspirationModal.value = true
  }

  function closeInspirationModal() {
    showInspirationModal.value = false
  }

  // 章节审阅（POST /api/critique_chapter，毒舌编辑视角，纯文本无需 LLM Key 配置——走后端统一配置）
  const showCritiqueModal = ref(false)
  const critiqueLoading = ref(false)
  const critiqueComments = ref<CritiqueItem[]>([])
  const critiquePraise = ref('')

  async function openCritiqueModal() {
    const chapter = selectedChapter.value
    if (!chapter) return
    const content = (chapter.content_text || chapter.draft_text || '').trim()
    if (content.length < 10) {
      showToast('本章内容太少——先多写一点，再请编辑看', 'warning')
      return
    }
    showCritiqueModal.value = true
    critiqueLoading.value = true
    critiqueComments.value = []
    critiquePraise.value = ''
    try {
      const result = await reviewApi.critiqueChapter(content, chapter.title || undefined)
      critiqueComments.value = result.comments || []
      critiquePraise.value = result.overall_praise || ''
    } catch (e: any) {
      console.error('章节审阅失败:', e)
      showCritiqueModal.value = false
      showToast('审阅失败：' + (e?.message || '未知错误'), 'error')
    } finally {
      critiqueLoading.value = false
    }
  }

  function closeCritiqueModal() {
    showCritiqueModal.value = false
  }

  function handleApplyInspirationToOutline(content: string) {
    if (!selectedChapter.value) return
    const currentOutline = selectedChapter.value.outline_text || ''
    const newOutline = currentOutline ? `${currentOutline}\n${content}` : content
    scheduleMetaUpdate({ outline_text: newOutline })
  }

  async function handlePartialOptimize(payload: { selection: any, instruction: string, mode?: string, tone?: string | null }) {
    if (!selectedChapter.value || !props.apiConfig.api_key) {
      showToast('请先在设置里配置 API Key', 'warning')
      return
    }

    isFormatting.value = true

    try {
      // CP4.1：透传 mode + tone 到后端（蓝图 §4.9）
      const requestBody: Record<string, any> = {
        chapter_id: selectedChapter.value.id,
        selected_text: payload.selection.text,
        context_before: payload.selection.contextBefore,
        context_after: payload.selection.contextAfter,
        user_instruction: payload.instruction,
        api_key: props.apiConfig.api_key,
        base_url: props.apiConfig.base_url,
        model: props.apiConfig.reasoning_model || props.apiConfig.model,
      }
      if (payload.mode) {
        requestBody.mode = payload.mode
      }
      if (payload.tone) {
        requestBody.tone = payload.tone
      }
      const { optimized_text } = await generateApi.optimizeSelection(requestBody)

      if (optimized_text && editorRef.value) {
        editorRef.value.applyOptimizationDiff(optimized_text)
        showToast('改好了，请在正文里确认', 'success')
      } else {
        editorRef.value.resetOptimization()
        showToast('AI 没给出可用的改写，换个说法再试', 'warning')
      }
    } catch (e: any) {
      console.error('Optimization failed', e)
      showToast('改写失败：' + e.message, 'error')
      if (editorRef.value) {
        editorRef.value.resetOptimization()
      }
    } finally {
      isFormatting.value = false
    }
  }

  /** 文档是否含行内格式/非段落块（全文格式整理会剥掉这些，需先确认）。 */
  function docHasRichFormatting(editor: any): boolean {
    let found = false
    editor.state.doc.descendants((node: any) => {
      if (found) return false
      if (node.isText && node.marks.length > 0) { found = true; return false }
      if (node.isTextblock && node.type.name !== 'paragraph') { found = true; return false }
      return true
    })
    return found
  }

  async function handleFormatText(payload: string | { text: string; selection?: { from: number; to: number } }) {
    const text = typeof payload === 'string' ? payload : payload.text
    const selection = typeof payload === 'string' ? undefined : payload.selection

    if (isFormatting.value || !text) return

    try {
      if (!props.apiConfig.api_key) {
        showToast('请先在设置里配置 API Key 才能整理格式', 'warning')
        return
      }

      // 细纲守卫：全文整理以纯文本重建段落，会静默毁掉未落笔的细纲胶囊
      if (!selection && editorRef.value?.editor) {
        let hasNote = false
        editorRef.value.editor.state.doc.descendants((node: any) => {
          if (node.type.name === 'outlineNote') { hasNote = true; return false }
          return true
        })
        if (hasNote) {
          showToast('文里有还没扩写的细纲胶囊——先扩写或删掉，再整理格式', 'warning')
          return
        }
      }

      // 全文整理（无选区）用纯文本重建段落，会剥掉加粗/高亮/标题等全部行内格式。
      // 有格式时先确认（原生撤销已恢复，整理后可 Ctrl+Z 反悔）。
      if (!selection && editorRef.value?.editor && docHasRichFormatting(editorRef.value.editor)) {
        const ok = await showConfirm({
          title: '整理全文格式',
          message: '全文整理只保留段落结构，将清除加粗、高亮、标题等行内格式。',
          warning: '整理后可按 Ctrl+Z 撤销。',
          confirmText: '继续整理',
        })
        if (!ok) return
      }

      isFormatting.value = true
      const { formatted_text } = await generateApi.formatText({
        text,
      })

      if (formatted_text && editorRef.value) {
        const paragraphs = formatted_text
          .split(/\r?\n/)
          .filter((line: string) => line.trim().length > 0)

        const jsonContent = {
          type: 'doc',
          content: paragraphs.map((text: string) => ({
            type: 'paragraph',
            content: [{ type: 'text', text: text.trim() }]
          }))
        }

        if (selection) {
          editorRef.value.editor.commands.setTextSelection(selection)
          editorRef.value.editor.commands.insertContent(jsonContent)
        } else {
          editorRef.value.editor.commands.setContent(jsonContent)
        }
      }
    } catch (e: any) {
      console.error('Format text failed', e)
      showToast('格式整理失败: ' + e.message, 'error')
    } finally {
      isFormatting.value = false
    }
  }

  watch(
    () => props.selectedChapter,
    async (newChapter, oldChapter) => {
      if (newChapter?.id !== oldChapter?.id) {
        // 切章前把旧章挂起的防抖保存立即落库（快照 id 保证写回旧章，不串新章）
        flushPendingSaves()
        publisher.resetOnChapterChange()
      }
    }
  )

  // 卸载（路由离开写作台等）前同样冲刷，防挂起保存丢失或错章落库
  onBeforeUnmount(() => flushPendingSaves())

  assets.watchChapterAssets(() => props.selectedChapter)

  return {
    toggleAsset: (assetId: string) => assets.toggleAsset(props.selectedChapter, assetId),
    isAssetSelected: assets.isAssetSelected,
    chapterSummary,
    characterUpdates: publisher.characterUpdates,
    characterExtraction: publisher.characterExtraction,
    closePublishModal: publisher.closePublishModal,
    handleContentUpdate,
    handleEditorEntityFocus,
    handleFormatText,
    handlePartialOptimize,
    handleAssetsSchemaInput,
    handleTitleInput,
    inspirationActiveCharacterIds,
    isCharacterSelected,
    isEditorDisabled,
    isFormatting,
    isPublishing: publisher.isPublishing,
    localMetaCollapsed,
    openInspirationModal,
    showCritiqueModal,
    critiqueLoading,
    critiqueComments,
    critiquePraise,
    openCritiqueModal,
    closeCritiqueModal,
    anchorPov: ref<string | null>(null),
    publishChapter: () => publisher.publishChapter(props.selectedChapter, props.apiConfig),
    selectedChapter,
    setEditorRef,
    showInspirationModal,
    showPublishModal: publisher.showPublishModal,
    toggleCharacter,
    toggleMetaCollapsed,
    getMetaCollapsedLabel,
    handleApplyInspirationToOutline,
    closeInspirationModal,
    flushPendingSaves,
  }
}
