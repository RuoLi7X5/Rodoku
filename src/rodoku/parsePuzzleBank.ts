// 将“文本题库”解析为多个 81 位题目串（0 表示空格）
// 兼容：
// - 空格使用 '0' 或 '.'
// - 任意分隔：空行/空格/换行/其它字符都可作为分隔
export function parsePuzzleBankText(text: string): string[] {
  const out: string[] = []
  let buf: string[] = []

  function flushIfFull() {
    if (buf.length === 81) {
      out.push(buf.join(''))
      buf = []
    }
  }

  for (const ch of text) {
    if (ch >= '1' && ch <= '9') {
      buf.push(ch)
      flushIfFull()
      continue
    }
    if (ch === '0' || ch === '.') {
      buf.push('0')
      flushIfFull()
      continue
    }
    // 其它字符视为分隔；若 buf 未满 81 则继续累积（容忍题目中换行/空格）
    // 若题库里确实用分隔符区分题目，但每题不是严格 9 行格式，这里也能工作。
  }

  // 丢弃尾部不完整残片（可在 UI 提示）
  return out
}

