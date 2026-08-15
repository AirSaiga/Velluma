/**
 * 生成错误文案分类（UX 修复：技术原文不再直达用户）。
 *
 * 后端错误帧格式为 `生成失败: RateLimitError: Error code: 429 - {...}` 这类
 * 异常类名+原文（见 backend/routes/chapter_generation/*.py 的总 catch）。
 * 这里在统一的 toast 出口做一次模式归类，给用户可读文案；原文仍进 console。
 */
export function formatGenerationError(raw: string): string {
  const msg = (raw || '').trim()
  if (!msg) return '生成失败，请重试'
  if (/429|rate\s?limit|quota|配额|insufficient/i.test(msg)) {
    return 'LLM 调用配额已达上限，请稍后重试或检查账户额度'
  }
  if (/401|403|unauthorized|invalid[_\s]?api[_\s]?key|api[_\s]?key/i.test(msg)) {
    return 'API Key 无效或已过期，请到设置面板检查模型配置'
  }
  if (/timed?\s?out|timeout|超时/i.test(msg)) {
    return '请求超时，请检查网络或代理后重试'
  }
  if (/failed to fetch|network|econnrefused|enotfound|err_|网络/i.test(msg)) {
    return '无法连接后端服务，请确认后端已启动且网络正常'
  }
  if (/content[_\s]?filter|moderation|data_inspection|审查|违规/i.test(msg)) {
    return '内容被安全策略拦截，请调整文本后重试'
  }
  return msg
}
