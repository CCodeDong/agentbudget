/**
 * 切词 —— 不依赖任何词典。
 *
 * WHY NO DICTIONARY
 *   手机上没有中文分词词典，也不该为一个个人资料库塞一个几十 MB 的词表。
 *   所以用**二元组（bigram）**：
 *     "离线资料库" → 离/线/资/料/库 + 离线/线资/资料/料库
 *
 *   这是中文检索里的经典做法：不用分词也能达到可用的召回率，
 *   代价是索引会大一些（约为字数的 2 倍词项）。
 *
 *   英文与数字按非字母数字切分并转小写。
 *
 * ⚠️ 纯函数，无副作用，无平台 API —— 因此可直接在 Node 里单测。
 */

/** 一个词项及其在文本中的位置（用于高亮）。 */
export interface Token {
  term: string;
  start: number;
  end: number;
}

const CJK_START = 0x4e00;
const CJK_END = 0x9fff;
const CJK_EXT_START = 0x3400;
const CJK_EXT_END = 0x4dbf;

export function isCJK(ch: string): boolean {
  const c = ch.charCodeAt(0);
  return (c >= CJK_START && c <= CJK_END) || (c >= CJK_EXT_START && c <= CJK_EXT_END);
}

function isAlnum(ch: string): boolean {
  return /[0-9a-z]/.test(ch);
}

/**
 * 切词。
 *
 * 中文：单字 + 相邻二元组
 * 英文/数字：连续字母数字串，转小写
 *
 * @param text 原文
 * @param keepUnigram 是否保留中文单字。默认 true。
 *                   设为 false 可让索引小约一半，但"单字查询"会失效。
 */
export function tokenize(text: string, keepUnigram: boolean = true): Token[] {
  const out: Token[] = [];
  const lower = text.toLowerCase();
  const n = lower.length;
  let i = 0;

  while (i < n) {
    const ch = lower.charAt(i);

    if (isCJK(ch)) {
      // 单字
      if (keepUnigram) {
        out.push({ term: ch, start: i, end: i + 1 });
      }
      // 二元组（需要下一个字符也是 CJK）
      if (i + 1 < n && isCJK(lower.charAt(i + 1))) {
        out.push({ term: lower.substring(i, i + 2), start: i, end: i + 2 });
      }
      i += 1;
      continue;
    }

    if (isAlnum(ch)) {
      let j = i;
      while (j < n && isAlnum(lower.charAt(j))) {
        j += 1;
      }
      const term = lower.substring(i, j);
      out.push({ term: term, start: i, end: j });
      i = j;
      continue;
    }

    // 其他字符（标点、空白、emoji）不产生词项
    i += 1;
  }

  return out;
}

/** 只要词项、不要位置时用它（建索引时用）。 */
export function terms(text: string, keepUnigram: boolean = true): string[] {
  const toks = tokenize(text, keepUnigram);
  const out: string[] = [];
  for (let i = 0; i < toks.length; i++) {
    out.push(toks[i].term);
  }
  return out;
}
