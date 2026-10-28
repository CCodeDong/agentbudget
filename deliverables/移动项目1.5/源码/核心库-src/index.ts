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
  /** 全部块，按加入顺序。**含已删除的墓碑**，所以不能直接用下标当"第 i 个活块"。 */
  private chunks: Chunk[] = [];
  /** 块 id → 下标。 */
  private chunkPos: Map<string, number> = new Map<string, number>();
  /** 词项 → (块下标 → Posting)。 */
  private postings: Map<string, Map<number, Posting>> = new Map<string, Map<number, Posting>>();
  /** 每个块的长度（词项数）。与 chunks 等长。 */
  private lengths: number[] = [];
  /** 墓碑标记。true 表示该块已删除，检索时跳过。 */
  private deleted: boolean[] = [];
  /** 活块的物理下标列表，顺序与加入顺序一致。`getChunk(i)` 用它映射。 */
  private liveIdx: number[] = [];
  /** 活块数。 */
  private liveCount: number = 0;
  /** 活块的长度总和，用于 avgdl。 */
  private liveLengthSum: number = 0;

  /**
   * 墓碑超过这个比例就自动压缩。
   *
   * 为什么需要：墓碑让删除变成 O(文档块数) 而不是 O(全库)，
   * 但死块会一直占着内存与遍历成本。20% 是一个折中——
   * 压缩本身是 O(全库)，太频繁就失去了增量的意义。
   */
  public static readonly COMPACT_THRESHOLD = 0.2;

  /** 已索引的**活块**数。 */
  public size(): number {
    return this.liveCount;
  }

  /** 清空。重新建库时用。 */
  public clear(): void {
    this.chunks = [];
    this.chunkPos = new Map<string, number>();
    this.postings = new Map<string, Map<number, Posting>>();
    this.lengths = [];
    this.deleted = [];
    this.liveIdx = [];
    this.liveCount = 0;
    this.liveLengthSum = 0;
  }

  /** 加入一个块。重复 id 会被忽略（幂等，便于增量建库）。 */
  public addChunk(c: Chunk): boolean {
    if (this.chunkPos.has(c.id)) {
      return false;
    }
    const idx = this.chunks.length;
    this.chunks.push(c);
    this.chunkPos.set(c.id, idx);
    this.deleted.push(false);
    this.liveIdx.push(idx);

    const toks = tokenize(c.text);
    this.lengths.push(toks.length);
    this.liveCount += 1;
    this.liveLengthSum += toks.length;

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

  /**
   * 删除一份文档的全部块。
   *
   * 用**墓碑标记**而不是物理删除：物理删除会让 `chunks` 下标整体前移，
   * 所有倒排表里记录的块下标立刻全部失效，只能全量重建——
   * 那正是我们要避免的。墓碑让删除只与**该文档的块数**成正比。
   *
   * 返回被标记删除的块数。
   */
  public removeDocument(docId: string): number {
    let removed = 0;
    for (let i = 0; i < this.liveIdx.length; i++) {
      const phys = this.liveIdx[i];
      if (this.chunks[phys].docId !== docId) {
        continue;
      }
      this.deleted[phys] = true;
      this.liveCount -= 1;
      this.liveLengthSum -= this.lengths[phys];
      removed += 1;
    }
    if (removed > 0) {
      this.rebuildLiveIdx();
      this.maybeCompact();
    }
    return removed;
  }

  /**
   * 用新文档替换旧文档的同 id 部分。
   *
   * 这是"用户重拍一张更清晰的照片"对应的操作：
   * 旧块墓碑化，新块加入。比"先删再建索引"少一次全量重建。
   *
   * 返回新加入的块数。
   */
  public replaceDocument(doc: DocItem, opts: ChunkOptions = DEFAULT_CHUNK_OPTIONS): number {
    this.removeDocument(doc.id);
    // 清掉该 docId 的**全部**块 id 占位。
    //
    // ⚠️ 这里曾经只遍历 liveIdx，结果漏掉了已墓碑化的旧块——
    //    它们的 id 仍留在 chunkPos 里，于是新块被当成"重复 id"而拒绝加入，
    //    表现为"替换后搜不到新内容"。
    //
    //    为什么早期测试没发现：那些用例是单文档库，删除后墓碑比例 100%
    //    会触发自动压缩，压缩顺带重建了 chunkPos，把 bug 掩盖了。
    //    多文档场景（墓碑比例低于阈值、不触发压缩）才暴露出来。
    for (let i = 0; i < this.chunks.length; i++) {
      if (this.chunks[i].docId === doc.id) {
        this.chunkPos.delete(this.chunks[i].id);
      }
    }
    return this.addDocument(doc, opts);
  }

  /** 活块的物理下标重排。删除后调用。 */
  private rebuildLiveIdx(): void {
    const next: number[] = [];
    for (let i = 0; i < this.chunks.length; i++) {
      if (!this.deleted[i]) {
        next.push(i);
      }
    }
    this.liveIdx = next;
  }

  /** 墓碑比例超阈值时自动压缩。 */
  private maybeCompact(): void {
    const total = this.chunks.length;
    if (total === 0) {
      return;
    }
    const deadRatio = (total - this.liveCount) / total;
    if (deadRatio >= InvertedIndex.COMPACT_THRESHOLD) {
      this.compact();
    }
  }

  /**
   * 物理压缩：丢掉墓碑，重建全部倒排表。
   *
   * **这是 O(全库) 的操作**，所以只在墓碑比例高时调用——
   * 频繁调用会让增量删除失去意义。
   */
  public compact(): void {
    const keptChunks: Chunk[] = [];
    const keptLengths: number[] = [];
    const remap: Map<number, number> = new Map<number, number>();

    for (let i = 0; i < this.chunks.length; i++) {
      if (this.deleted[i]) {
        continue;
      }
      remap.set(i, keptChunks.length);
      keptChunks.push(this.chunks[i]);
      keptLengths.push(this.lengths[i]);
    }

    this.chunks = keptChunks;
    this.lengths = keptLengths;
    this.deleted = [];
    for (let i = 0; i < keptChunks.length; i++) {
      this.deleted.push(false);
    }
    this.liveIdx = [];
    for (let i = 0; i < keptChunks.length; i++) {
      this.liveIdx.push(i);
    }
    this.liveCount = keptChunks.length;
    this.chunkPos = new Map<string, number>();
    for (let i = 0; i < keptChunks.length; i++) {
      this.chunkPos.set(keptChunks[i].id, i);
    }

    // 重建倒排表：把旧下标重映射到新下标
    const nextPostings: Map<string, Map<number, Posting>> = new Map<string, Map<number, Posting>>();
    this.postings.forEach((perChunk: Map<number, Posting>, term: string) => {
      const remapped: Map<number, Posting> = new Map<number, Posting>();
      perChunk.forEach((p: Posting, oldIdx: number) => {
        const ni = remap.get(oldIdx);
        if (ni !== undefined) {
          remapped.set(ni, p);
        }
      });
      if (remapped.size > 0) {
        nextPostings.set(term, remapped);
      }
    });
    this.postings = nextPostings;
  }

  /** 墓碑数。用于界面上显示"待整理"或调试。 */
  public tombstoneCount(): number {
    return this.chunks.length - this.liveCount;
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

  /** 平均块长度（词项数）。只统计活块——墓碑不该影响 avgdl。 */
  public avgDocLength(): number {
    if (this.liveCount === 0) {
      return 0;
    }
    return this.liveLengthSum / this.liveCount;
  }

  /** 活块数。 */
  public chunkCount(): number {
    return this.liveCount;
  }

  /**
   * 取第 i 个**活块**。
   *
   * 注意入参是"活块序号"，不是物理下标——真实下标由 `liveIdx` 映射。
   * 这样调用方（分块遍历、高亮、界面列表）不需要知道墓碑的存在。
   */
  public getChunk(i: number): Chunk {
    return this.chunks[this.liveIdx[i]];
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
      // 墓碑块必须跳过：它们已从 liveCount / avgdl 里剔除，
      // 但倒排表里仍留着记录（要等 compact 才清）。
      if (this.deleted[idx]) {
        return;
      }
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
