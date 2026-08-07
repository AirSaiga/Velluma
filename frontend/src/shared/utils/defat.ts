import type { Editor } from '@tiptap/vue-3'

/**
 * NLE-ADF 2.0 清脂拨盘（De-Fat Dial，Alt+↓）本地规则库。
 *
 * 设计原则（与后端残句门禁同款）：宁漏勿误。只删词级黑名单（套路副词/
 * AI 腔口头禅），不做句级手术（比喻句改写、心理句重写走 LLM wash，属 v2）。
 * 删除即时、免费、可预测；Ctrl+Z 可整体撤销（作者的安全网）。
 *
 * v2 路线：接 de_ai_washer（LLM 重洗）做深度档。
 */

/** AI 腔口头禅/套路修饰（整词删除） */
const BAN_WORDS = [
  '无比', '仿佛', '似乎', '宛如', '犹如', '仿若', '暗暗',
  '心中一紧', '心中一震', '心中涌起', '眼神中闪过',
  '不禁', '不由得', '顿时', '倏地', '蓦地', '骤然',
]

/** 套路"地"字副词（整词删除，只列高频套路词，防误伤正常表达） */
const ADVERBS = [
  '飞快地', '迅速地', '缓缓地', '慢慢地', '轻轻地', '重重地',
  '死死地', '狠狠地', '默默地', '静静地', '悄然地', '突然地',
  '猛地', '徐徐地', '紧紧地', '牢牢地', '深深地', '悄悄地',
  '焦急地', '愤怒地', '平静地', '温柔地', '粗暴地', '熟练地',
  '机械地', '下意识地', '本能地', '不自觉地',
]

/** 文本清脂：删黑名单词 + 清理叠标点。返回新文本与被删词清单。 */
export function defatText(text: string): { text: string; removed: string[] } {
  const removed: string[] = []
  let out = text
  for (const word of [...BAN_WORDS, ...ADVERBS]) {
    if (out.includes(word)) {
      removed.push(word)
      out = out.split(word).join('')
    }
  }
  if (removed.length) {
    // 删词产生的叠标点/悬空标点收敛
    out = out
      .replace(/，，+/g, '，')
      .replace(/。。+/g, '。')
      .replace(/，。/g, '。')
      .replace(/，：/g, '：')
      .replace(/ {2,}/g, ' ')
  }
  return { text: out, removed }
}

/**
 * 对光标所在段落执行清脂（两阶段：先删除线闪烁，再真正删除）。
 *
 * 设计稿"刮油"反馈：被删的词先以删除线闪现 450ms（让作者看见"刮掉了什么"），
 * 随后整段替换为清脂后文本。期间作者若编辑了该段，放弃删除只摘删除线
 * （位置漂移防御：以文本一致性为准，不缓存位置跨事务映射）。
 *
 * 返回删除的词数（0 = 无可清）。副作用：整段以纯文本替换（段内行内格式丢失）——
 * 写作正文场景无行内格式，可接受；调用方须在无幽灵草稿时使用。
 */
export function defatParagraphAtCursor(editor: Editor): number {
  const { $from } = editor.state.selection
  if ($from.depth < 1) return 0
  const start = $from.start()
  const end = $from.end()
  const original = $from.parent.textContent
  if (!original.trim()) return 0
  const { text: newText, removed } = defatText(original)
  if (!removed.length || newText === original) return 0

  // 第一阶段：删除线标记将被删的词（视觉预演）
  editor
    .chain()
    .command(({ tr, state }) => {
      const strike = state.schema.marks.strike
      if (!strike) return false
      for (const word of removed) {
        let idx = original.indexOf(word)
        while (idx >= 0) {
          tr.addMark(start + idx, start + idx + word.length, strike.create())
          idx = original.indexOf(word, idx + word.length)
        }
      }
      return true
    })
    .run()

  // 第二阶段：闪烁窗口后真正删除（作者期间动过这段则只摘删除线）
  setTimeout(() => {
    try {
      const $f = editor.state.selection.$from
      if ($f.depth < 1) return
      if ($f.parent.textContent !== original) {
        editor
          .chain()
          .command(({ tr, state }) => {
            const strike = state.schema.marks.strike
            if (strike) tr.removeMark($f.start(), $f.end(), strike)
            return true
          })
          .run()
        return
      }
      editor
        .chain()
        .command(({ tr }) => {
          tr.insertText(newText, $f.start(), $f.end())
          return true
        })
        .run()
    } catch {
      // 编辑器已销毁/文档剧变：静默放弃（词级清脂本就是不关键路径）
    }
  }, 450)
  return removed.length
}
