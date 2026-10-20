/**
 * 倒排索引 + BM25 打分 + 分块。
 *
 * WHY BM25 AND NOT VECTORS
 *   - 向量检索在手机上要么依赖 HMS 的 Retrieval（我们无法验证它是否存在），
 *     要么自己跑一个嵌入模型（手机上没有可用的端侧大模型）。
 *   - BM25 是**纯统计**方法：零依赖、确定性、可在 Node 里逐条断言。
 *   对一个"个人资料库"来说，BM25 的召回质量足够，而且它的打分分布
 *   **恰好就是自适应 top-k 要用的信号**（见 search.ts）。
 *
 * ⚠️ 纯计算，不导入任何平台 API。
 */

import { Chunk, DocItem, Span } from './types';
import { terms, tokenize } from './tokenize';

/** BM25 参数。默认值是文献里的常用取值。 */
export const BM25_K1 = 1.5;
export const BM25_B = 0.75;

/** 分块参数。 */
export interface ChunkOptions {
  /** 每块目标字符数。中文按字符算，英文按字符算（不做语言区分，保持简单）。 */
  size: number;
  /** 相邻块的重叠字符数。避免关键词被切在边界上而漏检。 */
  overlap: number;
}

export const DEFAULT_CHUNK_OPTIONS: ChunkOptions = { size: 240, overlap: 40 };

/** 倒排表的一项：某个词项 → (块 id → 词频)。 */
interface Posting {
  tf: number;
  positions: number[];
}

export class InvertedIndex {
  /** 全部块，按加入顺序。 */
  private chunks: Chunk[] = [];
  /** 块 id → 下标。 */
  private chunkPos: Map<string, number> = new Map<string, number>();
  /** 词项 → (块下标 → Posting)。 */
  private postings: Map<string, Map<number, Posting>> = new Map<string, Map<number, Posting>>();
  /** 每个块的长度（词项数）。 */
  private lengths: number[] = [];
  /** 长度总和，用于 avgdl。 */
  private totalLength: number = 0;

  /** 已索引的块数。 */
  public size(): number {
    return this.chunks.length;
  }

  /** 清空。重新建库时用。 */
  public clear(): void {
    this.chunks = [];
    this.chunkPos = new Map<string, number>();
    this.postings = new Map<string, Map<number, Posting>>();
    this.lengths = [];
    this.totalLength = 0;
  }

  /** 加入一个块。重复 id 会被忽略（幂等，便于增量建库）。 */
  public addChunk(c: Chunk): boolean {
    if (this.chunkPos.has(c.id)) {
      return false;
    }
    const idx = this.chunks.length;
    this.chunks.push(c);
    this.chunkPos.set(c.id, idx);

    const toks = tokenize(c.text);
    this.lengths.push(toks.length);
    this.totalLength += toks.length;

    // 逐词项累积词频与位置
    for (let i = 0; i < toks.length; i++) {
      const t = toks[i];
      let perChunk = this.postings.get(t.term);
      if (perChunk === undefined) {
        perChunk = new Map<number, Posting>();
        this.postings.set(t.term, perChunk);
      }
      let p = perChunk.get(idx);
      if (p === undefined) {
        p = { tf: 0, positions: [] };
        perChunk.set(idx, p);
      }
      p.tf += 1;
      p.positions.push(t.start);
    }
    return true;
  }

  /** 把一份资料切成块并全部加入。返回新建的块数。 */
  public addDocument(doc: DocItem, opts: ChunkOptions = DEFAULT_CHUNK_OPTIONS): number {
    const chunks = chunkDocument(doc, opts);
    let added = 0;
    for (let i = 0; i < chunks.length; i++) {
      if (this.addChunk(chunks[i])) {
        added += 1;
      }
    }
    return added;
  }

  /** 平均块长度（词项数）。 */
  public avgDocLength(): number {
    if (this.lengths.length === 0) {
      return 0;
    }
    return this.totalLength / this.lengths.length;
  }

  /** 块数。 */
  public chunkCount(): number {
    return this.chunks.length;
  }

  public getChunk(i: number): Chunk {
    return this.chunks[i];
  }

  /**
   * BM25 打分。
   *
   * 返回**全部候选**（未截断）的得分，按降序排。
   * 不截断是刻意的：自适应 top-k 需要看完整分布才能找断层（见 search.ts）。
   */
  public score(query: string): Candidate[] {
    const qTerms = terms(query);
    if (qTerms.length === 0 || this.chunks.length === 0) {
      return [];
    }

    const N = this.chunks.length;
    const avgdl = this.avgDocLength();
    // 同一查询里重复的词项只计一次
    const uniq: string[] = [];
    const seen: Map<string, boolean> = new Map<string, boolean>();
    for (let i = 0; i < qTerms.length; i++) {
      if (!seen.has(qTerms[i])) {
        seen.set(qTerms[i], true);
        uniq.push(qTerms[i]);
      }
    }

    const acc: Map<number, number> = new Map<number, number>();
    const matched: Map<number, Map<string, number>> = new Map<number, Map<string, number>>();

    for (let qi = 0; qi < uniq.length; qi++) {
      const term = uniq[qi];
      const perChunk = this.postings.get(term);
      if (perChunk === undefined) {
        continue;
      }
      const df = perChunk.size;
      // BM25 的 IDF，加 1 保证非负
      const idf = Math.log((N - df + 0.5) / (df + 0.5) + 1);

      perChunk.forEach((p: Posting, idx: number) => {
        const dl = this.lengths[idx];
        const denom = p.tf + BM25_K1 * (1 - BM25_B + (BM25_B * dl) / avgdl);
        const gain = (idf * (p.tf * (BM25_K1 + 1))) / denom;
        acc.set(idx, (acc.get(idx) ?? 0) + gain);

        let m = matched.get(idx);
        if (m === undefined) {
          m = new Map<string, number>();
          matched.set(idx, m);
        }
        m.set(term, p.tf);
      });
    }

    const out: Candidate[] = [];
    acc.forEach((score: number, idx: number) => {
      const m = matched.get(idx);
      out.push({
        index: idx,
        chunk: this.chunks[idx],
        score: score,
        matched: m !== undefined ? m : new Map<string, number>()
      });
    });

    out.sort((a: Candidate, b: Candidate) => b.score - a.score);
    return out;
  }
}

/** 一个候选（未截断）。 */
export interface Candidate {
  /** 块在索引里的下标。 */
  index: number;
  chunk: Chunk;
  score: number;
  matched: Map<string, number>;
}

/**
 * 把一份资料切成重叠的块。
 *
 * 重叠是必需的：中文关键词被切在块边界上会导致漏检，
 * 而 40 字符的重叠足以覆盖绝大多数被切断的词。
 */
export function chunkDocument(doc: DocItem, opts: ChunkOptions = DEFAULT_CHUNK_OPTIONS): Chunk[] {
  const text = doc.text;
  const out: Chunk[] = [];
  if (text.length === 0) {
    return out;
  }
  const size = Math.max(1, opts.size);
  const overlap = Math.max(0, Math.min(opts.overlap, size - 1));
  const step = Math.max(1, size - overlap);

  let seq = 0;
  let start = 0;
  while (start < text.length) {
    const end = Math.min(start + size, text.length);
    out.push({
      id: doc.id + '#' + seq.toString(),
      docId: doc.id,
      seq: seq,
      start: start,
      end: end,
      text: text.substring(start, end)
    });
    seq += 1;
    if (end >= text.length) {
      break;
    }
    start += step;
  }
  return out;
}

/** 在块内定位查询词的高亮区间。 */
export function locateSpans(chunkText: string, matched: Map<string, number>): Span[] {
  const spans: Span[] = [];
  const lower = chunkText.toLowerCase();
  matched.forEach((_tf: number, term: string) => {
    let from = 0;
    while (true) {
      const at = lower.indexOf(term, from);
      if (at < 0) {
        break;
      }
      spans.push({ start: at, end: at + term.length });
      from = at + term.length;
    }
  });
  // 按起点排序并合并重叠区间，避免界面上重复绘制
  spans.sort((a: Span, b: Span) => a.start - b.start);
  return mergeSpans(spans);
}

function mergeSpans(spans: Span[]): Span[] {
  if (spans.length <= 1) {
    return spans;
  }
  const out: Span[] = [];
  let cur = spans[0];
  for (let i = 1; i < spans.length; i++) {
    const s = spans[i];
    if (s.start <= cur.end) {
      cur = { start: cur.start, end: Math.max(cur.end, s.end) };
    } else {
      out.push(cur);
      cur = s;
    }
  }
  out.push(cur);
  return out;
}
