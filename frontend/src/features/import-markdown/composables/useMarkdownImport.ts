/**
 * Markdown 批量导入章节的核心逻辑组合函数。
 *
 * 职责：
 * - 持有导入向导的状态机（select → preview → importing → done）
 * - 管理待导入条目列表（解析、编辑、删除、重排）
 * - 执行串行导入（逐章调用 store.createChapter，失败不中断）
 *
 * 业务场景：用户从 Workspace Binder 或 Library 卡片触发"导入 .md"，经过三步向导后
 * 将多个 .md 文件作为章节批量写入当前书籍。
 *
 * 设计依据：
 * - 串行导入避免后端 chapter_number 自增竞态
 * - 失败的条目标记 error 但不中断后续，最终汇总展示
 * - 复用 AppStore.createChapter（已处理 POST → 追加 chapters[] → 自动选中）
 */
import { ref, computed } from 'vue'
import { markdownToHtml, htmlPlainTextLength, inferChapterName, splitMarkdownByH1, parseChapterHeading } from '../../../shared/utils/markdown-parser'
import type { AppStore } from '../../app/useAppStore'

/** 单个待导入条目 */
export interface ImportEntry {
  /** 内部唯一 ID（用于列表 key 和状态追踪） */
  id: string
  /** 原始文件名 */
  fileName: string
  /** 章节号（可编辑） */
  chapterNumber: number
  /** 章节名（可编辑，对应章节的 title 字段——编辑器标题输入框的值） */
  chapterName: string
  /** 章节固定标签（对应 chapter_name 字段——编辑器左侧"第X章"标签） */
  chapterLabel: string
  /** 已解析的 HTML（最终写入 content_text） */
  htmlContent: string
  /** 预估字数（HTML 纯文本长度） */
  wordCount: number
  /** 导入状态 */
  status: 'pending' | 'importing' | 'success' | 'error'
  /** 失败原因（status='error' 时填充） */
  error?: string
}

/** 文件读取结果（含跳过的空文件提示） */
export interface IngestResult {
  entries: ImportEntry[]
  /** 被跳过的文件名（空文件或读取失败） */
  skipped: { fileName: string; reason: string }[]
}

/** 向导步骤 */
export type ImportStep = 'select' | 'preview' | 'importing' | 'done'

/** 生成内部唯一 ID */
function genId(): string {
  return `import-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

/**
 * 读取 File 为文本。
 * 警示：FileReader.readAsText 默认 UTF-8，非 UTF-8 文件会乱码（小说场景几乎都是 UTF-8）。
 */
function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(reader.error || new Error('文件读取失败'))
    reader.readAsText(file)
  })
}

/**
 * Markdown 导入组合函数。
 *
 * Args:
 *   store: 应用全局状态（用于 createChapter）
 *
 * Returns:
 *   响应式状态 + 操作方法
 */
export function useMarkdownImport(store: AppStore) {
  /** 当前向导步骤 */
  const step = ref<ImportStep>('select')
  /** 待导入条目列表 */
  const entries = ref<ImportEntry[]>([])
  /** Step 1 中被跳过的文件 */
  const skippedFiles = ref<{ fileName: string; reason: string }[]>([])
  /** 导入过程中是否正在执行（用于禁止关闭确认） */
  const isImporting = ref(false)
  /** 已完成的条目数（成功+失败） */
  const completedCount = ref(0)
  /** 成功条目数 */
  const successCount = ref(0)
  /** 失败条目数 */
  const errorCount = ref(0)
  /** 当前正在导入的条目序号（0-based） */
  const currentIndex = ref(-1)
  /** 是否已中止（用户点取消后停止后续） */
  let aborted = false

  /** 总条目数 */
  const totalCount = computed(() => entries.value.length)

  /** 进度百分比（0-100） */
  const progressPercent = computed(() => {
    if (totalCount.value === 0) return 0
    return Math.round((completedCount.value / totalCount.value) * 100)
  })

  /**
   * Step 1 → 2：读取并解析 File[]，生成 ImportEntry[]。
   *
   * 规则：
   * - 过滤非 .md 文件（静默丢弃）
   * - 空文件（0 字节或纯空白）跳过并记录原因
   * - 单个 .md 按 H1（# 标题）拆分为多个章节；无 H1 时整体作为一章
   * - 章节号：优先从 H1 标题解析（如"第3章"→3），解析不到则自增
   * - 章节名：优先取 H1 标题去掉章节号后的部分，无 H1 时从文件名推断
   */
  async function ingestFiles(files: File[]): Promise<void> {
    // 按扩展名过滤 .md / .markdown（不依赖 MIME type，不同系统对 .md 的 type 不一致）
    const validMdFiles = files.filter((f) => /\.(md|markdown)$/i.test(f.name))

    const existingMaxNumber = store.chapters.value.length > 0
      ? Math.max(...store.chapters.value.map((c) => c.chapter_number))
      : 0

    const newEntries: ImportEntry[] = []
    const skipped: { fileName: string; reason: string }[] = []
    // 用于无法从标题解析出章节号时的自增兜底
    let fallbackCounter = existingMaxNumber

    for (let i = 0; i < validMdFiles.length; i++) {
      const file = validMdFiles[i]
      try {
        const text = await readFileAsText(file)
        if (!text || !text.trim()) {
          skipped.push({ fileName: file.name, reason: '空文件' })
          continue
        }
        // 统一预处理：去 BOM + 统一换行（与 markdownToHtml 内部一致，供 splitMarkdownByH1 使用）
        const cleaned = text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n')
        // 按 H1 拆分（无 H1 时返回单个分片，title 为空串）
        const sections = splitMarkdownByH1(cleaned)
        for (const section of sections) {
          const htmlContent = markdownToHtml(section.markdown)
          // 跳过拆分后纯空白的分片（如 H1 下无正文）
          if (!htmlContent.replace(/<[^>]+>/g, '').trim()) continue
          const wordCount = htmlPlainTextLength(htmlContent)

          // 从 H1 标题解析章节号和名称
          const parsed = parseChapterHeading(section.title)
          let chapterNumber: number
          let chapterName: string
          let chapterLabel: string
          if (parsed.number !== null) {
            // 标题含"第X章"：用解析的编号，名称取剩余部分，标签为"第X章"
            chapterNumber = parsed.number
            chapterName = parsed.name || section.title
            chapterLabel = `第${chapterNumber}章`
          } else {
            // 标题无章节号前缀：编号自增兜底，名称用原标题
            fallbackCounter++
            chapterNumber = fallbackCounter
            chapterName = parsed.name || inferChapterName(file.name)
            chapterLabel = `第${chapterNumber}章`
          }

          newEntries.push({
            id: genId(),
            fileName: file.name,
            chapterNumber,
            chapterName,
            chapterLabel,
            htmlContent,
            wordCount,
            status: 'pending',
          })
        }
      } catch (e: any) {
        skipped.push({ fileName: file.name, reason: e.message || '读取失败' })
      }
    }

    // 合并到已有列表（支持追加选择）
    entries.value.push(...newEntries)
    skippedFiles.value.push(...skipped)
    step.value = 'preview'
  }

  /** Step 2：更新单条 entry */
  function updateEntry(id: string, partial: Partial<ImportEntry>): void {
    const idx = entries.value.findIndex((e) => e.id === id)
    if (idx !== -1) {
      entries.value[idx] = { ...entries.value[idx], ...partial }
    }
  }

  /** Step 2：移除单条 entry */
  function removeEntry(id: string): void {
    entries.value = entries.value.filter((e) => e.id !== id)
  }

  /**
   * Step 2：重排条目（上移/下移）。
   *
   * Args:
   *   id: 要移动的条目 ID
   *   direction: 'up' 或 'down'
   */
  function moveEntry(id: string, direction: 'up' | 'down'): void {
    const idx = entries.value.findIndex((e) => e.id === id)
    if (idx === -1) return
    const targetIdx = direction === 'up' ? idx - 1 : idx + 1
    if (targetIdx < 0 || targetIdx >= entries.value.length) return
    const list = [...entries.value]
    ;[list[idx], list[targetIdx]] = [list[targetIdx], list[idx]]
    entries.value = list
  }

  /** Step 2：清空所有条目（回到 Step 1） */
  function clearEntries(): void {
    entries.value = []
    skippedFiles.value = []
    step.value = 'select'
  }

  /**
   * 校验：检测章节号冲突。
   *
   * Returns:
   *   { ok: 是否通过, conflicts: 冲突的章节号列表 }
   */
  function validate(): { ok: boolean; conflicts: number[] } {
    const conflicts = new Set<number>()
    // 与现有章节冲突
    const existingNumbers = new Set(store.chapters.value.map((c) => c.chapter_number))
    const seenNumbers = new Map<number, number>() // number → 出现次数

    for (const entry of entries.value) {
      if (entry.chapterNumber < 1) {
        conflicts.add(entry.chapterNumber)
        continue
      }
      if (existingNumbers.has(entry.chapterNumber)) {
        conflicts.add(entry.chapterNumber)
      }
      seenNumbers.set(entry.chapterNumber, (seenNumbers.get(entry.chapterNumber) || 0) + 1)
    }
    // 表内重复
    for (const [num, count] of seenNumbers) {
      if (count > 1) conflicts.add(num)
    }

    return { ok: conflicts.size === 0 && entries.value.length > 0, conflicts: [...conflicts] }
  }

  /**
   * Step 2 → 3 → done：执行串行导入。
   *
   * 警示：串行执行，每章 await store.createChapter。
   * 单章失败标记 error 但不中断后续。用户可通过 aborted 中止。
   */
  async function executeImport(): Promise<void> {
    if (!store.currentBookId.value) return
    aborted = false
    isImporting.value = true
    step.value = 'importing'
    completedCount.value = 0
    successCount.value = 0
    errorCount.value = 0
    currentIndex.value = -1

    for (let i = 0; i < entries.value.length; i++) {
      if (aborted) break
      const entry = entries.value[i]
      currentIndex.value = i
      entry.status = 'importing'
      try {
        await store.createChapter({
          chapter_number: entry.chapterNumber,
          chapter_name: entry.chapterLabel,
          title: entry.chapterName,
          outline_text: '',
          content_text: entry.htmlContent,
          status: 'draft',
        } as any)
        entry.status = 'success'
        successCount.value++
      } catch (e: any) {
        entry.status = 'error'
        entry.error = e.message || '创建失败'
        errorCount.value++
      }
      completedCount.value++
    }

    isImporting.value = false
    currentIndex.value = -1
    step.value = 'done'
  }

  /** 中止导入（仅停止后续未执行的条目） */
  function abortImport(): void {
    aborted = true
  }

  /** Step 3 done → 回到 Step 2（重试失败条目） */
  function backToPreview(): void {
    // 将 error 状态重置为 pending，保留 success 条目（用户可选择删除）
    for (const entry of entries.value) {
      if (entry.status === 'error') {
        entry.status = 'pending'
        entry.error = undefined
      }
    }
    // 只保留未成功的（已成功的不重导）
    entries.value = entries.value.filter((e) => e.status !== 'success')
    step.value = 'preview'
  }

  /** 重置全部状态（关闭 Modal 时调用） */
  function reset(): void {
    step.value = 'select'
    entries.value = []
    skippedFiles.value = []
    isImporting.value = false
    completedCount.value = 0
    successCount.value = 0
    errorCount.value = 0
    currentIndex.value = -1
    aborted = false
  }

  return {
    // 状态
    step,
    entries,
    skippedFiles,
    isImporting,
    completedCount,
    successCount,
    errorCount,
    currentIndex,
    totalCount,
    progressPercent,
    // 操作
    ingestFiles,
    updateEntry,
    removeEntry,
    moveEntry,
    clearEntries,
    validate,
    executeImport,
    abortImport,
    backToPreview,
    reset,
  }
}
