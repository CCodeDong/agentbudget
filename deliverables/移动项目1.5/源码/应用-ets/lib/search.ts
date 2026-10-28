/**
 * 检索 + 自适应 top-k 决策。
 *
 * THIS IS THE PART THAT CARRIES THE RESEARCH
 *   我们的调度器实验得出的结论是：
 *     **"剩余预算"不是决定检索深度的正确信号；"候选得分分布"才是。**
 *
 *   在资料库这个场景里，这句话变得非常具体：
 *     得分分布有明显断层 → 断层之前的是真正相关的，之后就不要再取；
 *     得分分布平坦          → 没有明显区分度，多取无益。
 *
 *   所以 `kSource: 'score-gap'` 这条路径，就是那个研究结论的产品化实现。
 *   而 `kSource: 'fixed'` 是它的对照组 —— 产品里两者都要保留，
 *   因为**用户能直观看到"固定 k"和"自适应 k"的差别**，这本身就是产品价值。
 *
 * ⚠️ 纯函数，可在 Node 里逐条断言。
 */

import { InvertedIndex, Candidate, locateSpans } from './index';
import {
  Hit, Span, Chunk, ScoreDiagnostics, SearchOptions, SearchResult, BudgetInput, BudgetDecision
} from './types';

/** 相对落差的下限：小于这个值的"断层"不算断层（避免把噪声当信号）。 */
export const MIN_GAP_RATIO = 0.05;

/**
 * 计算得分分布诊断。
 *
 * `maxGap` 用**相对落差**而不是绝对差：不同查询的绝对得分量级不同，
 * 只有相对值才可比。
 */
export function diagnose(candidates: Candidate[]): ScoreDiagnostics {
  const n = candidates.length;
  if (n === 0) {
    return { candidateCount: 0, topScore: 0, mean: 0, std: 0, maxGap: 0, maxGapAt: -1 };
  }

  let sum = 0;
  for (let i = 0; i < n; i++) {
    sum += candidates[i].score;
  }
  const mean = sum / n;

  let sq = 0;
  for (let i = 0; i < n; i++) {
    const d = candidates[i].score - mean;
    sq += d * d;
  }
  const std = Math.sqrt(sq / n);

  let maxGap = 0;
  let maxGapAt = -1;
  for (let i = 0; i + 1 < n; i++) {
    const hi = candidates[i].score;
    const lo = candidates[i + 1].score;
    if (hi <= 0) {
      continue;
    }
    const ratio = (hi - lo) / hi;
    if (ratio > maxGap) {
      maxGap = ratio;
      maxGapAt = i;
    }
  }

  return {
    candidateCount: n,
    topScore: candidates[0].score,
    mean: mean,
    std: std,
    maxGap: maxGap,
    maxGapAt: maxGapAt
  };
}

/**
 * 由得分分布决定 k。
 *
 * 规则：
 *   1. 找到相邻得分的最大相对落差位置 g
 *   2. 若该落差 >= MIN_GAP_RATIO，取 k = g + 1（断层之前的全部保留）
 *   3. 否则说明分布平坦、没有明显相关边界 → 取 maxK（反正区分不出来）
 *   4. 最后夹到 [minK, maxK] 与候选总数内
 */
export function decideKByScoreGap(
  candidates: Candidate[],
  minK: number,
  maxK: number,
  diag?: ScoreDiagnostics
): number {
  const n = candidates.length;
  if (n === 0) {
    return 0;
  }
  const d = diag !== undefined ? diag : diagnose(candidates);

  let k: number;
  if (d.maxGapAt >= 0 && d.maxGap >= MIN_GAP_RATIO) {
    k = d.maxGapAt + 1;
  } else {
    // 分布平坦：没有可信的断层，用上界
    k = maxK;
  }

  if (k < minK) {
    k = minK;
  }
  if (k > maxK) {
    k = maxK;
  }
  if (k > n) {
    k = n;
  }
  return k;
}

/**
 * 把同一文档中**重叠或首尾相接**的命中块合并成一条。
 *
 * WHY THIS EXISTS
 *   分块有 40 字符重叠，所以一段连续文字里的关键词很容易同时命中相邻的几块。
 *   对用户来说那就是"同一段话"，显示成 3 条是纯噪音。
 *
 * HOW IT MERGES
 *   · 文本：直接按偏移拼回去。chunkDocument 的 text 是 text.substring(start, end)，
 *     所以当后块起点落在前块范围内时，只需补上超出部分。
 *   · 得分：取**最高分**，不累加。累加会让"被切成很多块的长文档"凭空得高分，
 *     那是把分块策略的副作用当成相关度。
 *   · 高亮：后块的 span 需要减去前块起点，换算到合并后的坐标系。
 *   · 命中词频：相加，因为合并区域里确实出现了那么多次。
 *
 *   **不合并不同文档**：跨文档拼在一起没有意义，用户也不会那样读。
 *
 * ⚠️ 只在 ranges 真正相接或重叠时合并。中间有空隙就不合并 ——
 *    否则会把"第 1 段和第 20 段"合成一条，看起来像连续引用，实际不是。
 */
export function mergeAdjacentHits(hits: Hit[]): Hit[] {
  if (hits.length <= 1) {
    return hits;
  }

  // 记录每条属于哪个合并组，以及组内成员的原始名次（用于保持排序）
  const groups: Hit[] = [];
  const groupRank: number[] = [];

  for (let i = 0; i < hits.length; i++) {
    const h = hits[i];
    let target = -1;

    // 找同一文档且范围相接/重叠的已有组
    for (let g = 0; g < groups.length; g++) {
      const cur = groups[g];
      if (cur.chunk.docId !== h.chunk.docId) {
        continue;
      }
      if (h.chunk.start <= cur.chunk.end && cur.chunk.start <= h.chunk.end) {
        target = g;
        break;
      }
    }

    if (target < 0) {
      const copy: Hit = {
        chunk: h.chunk,
        score: h.score,
        matched: new Map<string, number>(h.matched),
        spans: h.spans.slice()
      };
      if (h.mergedCount !== undefined) {
        copy.mergedCount = h.mergedCount;
      }
      groups.push(copy);
      groupRank.push(i);
      continue;
    }

    const g0 = groups[target];
    const base = g0.chunk;
    const add = h.chunk;

    // 拼文本：add 覆盖 [add.start, add.end)，base 已覆盖 [base.start, base.end)
    const baseLen = base.text.length;
    const baseEnd = base.start + baseLen;
    const tailFrom = baseEnd - add.start;
    let newText = base.text;
    if (tailFrom >= 0 && tailFrom < add.text.length) {
      newText = base.text + add.text.substring(tailFrom);
    } else if (tailFrom < 0) {
      // 中间有空隙：不合并，另起一组（正常不会走到，这里防御）
      groups.push({
        chunk: add, score: h.score,
        matched: new Map<string, number>(h.matched), spans: h.spans.slice()
      });
      groupRank.push(i);
      continue;
    }

    // 高亮坐标换算
    const shift = add.start - base.start;
    const spans = g0.spans.slice();
    for (let s = 0; s < h.spans.length; s++) {
      const nv: Span = { start: h.spans[s].start + shift, end: h.spans[s].end + shift };
      spans.push(nv);
    }
    spans.sort((a: Span, b: Span) => a.start - b.start);

    // 词频相加
    const matched = g0.matched;
    h.matched.forEach((tf: number, term: string) => {
      matched.set(term, (matched.get(term) ?? 0) + tf);
    });

    const mergedChunk: Chunk = {
      id: base.docId + '#' + base.seq.toString() + '-' + add.seq.toString(),
      docId: base.docId,
      seq: base.seq,
      start: base.start,
      end: Math.max(baseEnd, add.end),
      text: newText
    };

    const merged: Hit = {
      chunk: mergedChunk,
      score: Math.max(g0.score, h.score),
      matched: matched,
      spans: spans,
      mergedCount: (g0.mergedCount ?? 1) + (h.mergedCount ?? 1)
    };
    groups[target] = merged;
  }

  // 按各组里最好的原始名次排序，保持与合并前一致的顺序
  const order: number[] = [];
  for (let i = 0; i < groups.length; i++) {
    order.push(i);
  }
  order.sort((a: number, b: number) => groupRank[a] - groupRank[b]);

  const out: Hit[] = [];
  for (let i = 0; i < order.length; i++) {
    out.push(groups[order[i]]);
  }
  return out;
}

/**
 * 检索主入口。
 *
 * `options.topK > 0` → 固定 k（对照组）
 * `options.topK <= 0` → 由得分分布自适应（我们的方法）
 * `options.mergeAdjacent` → 选出 top-k 之后，把同文档相接的块合并
 */
export function search(index: InvertedIndex, query: string, options: SearchOptions): SearchResult {
  const candidates = index.score(query);
  const diag = diagnose(candidates);

  let k: number;
  let kSource: 'fixed' | 'score-gap';
  if (options.topK > 0) {
    k = options.topK;
    kSource = 'fixed';
  } else {
    k = decideKByScoreGap(candidates, options.minK, options.maxK, diag);
    kSource = 'score-gap';
  }
  if (k > candidates.length) {
    k = candidates.length;
  }

  const hits: Hit[] = [];
  for (let i = 0; i < k; i++) {
    const c = candidates[i];
    hits.push({
      chunk: c.chunk,
      score: c.score,
      matched: c.matched,
      spans: locateSpans(c.chunk.text, c.matched)
    });
  }

  if (options.mergeAdjacent === true) {
    return { hits: mergeAdjacentHits(hits), k: k, kSource: kSource, diagnostics: diag };
  }
  return { hits: hits, k: k, kSource: kSource, diagnostics: diag };
}

/**
 * 由资源预算决定"还能不能多取几条"。
 *
 * 注意这与上面的 k 决策是**两件事**：
 *   - `decideKByScoreGap` 回答"该取几条"（信息层面的问题，看得分分布）
 *   - `decideBudget`     回答"还取得起吗"（资源层面的问题，看延迟/内存/电量）
 *
 * 这正是我们研究主张的另一半：**两个问题需要两个不同的信号**。
 * 把它们混成一个"剩余预算"信号，就会得到实验里那个被严格支配的结果。
 */
export function decideBudget(input: BudgetInput, avgChunkChars: number): BudgetDecision {
  // 每条命中大约要一次排序 + 一次高亮定位，按经验折算成时间
  const msPerHit = 0.6;
  const kbPerHit = (avgChunkChars * 2) / 1024 + 0.5;

  const byLatency = Math.floor(input.latencyBudgetMs / msPerHit);
  const byMemory = Math.floor(input.memoryBudgetKb / kbPerHit);

  let k = Math.min(byLatency, byMemory);
  const reasons: string[] = [];

  if (byLatency <= byMemory) {
    reasons.push('受时间预算限制');
  } else {
    reasons.push('受内存预算限制');
  }

  // 低电量：主动降级，避免后台建库/检索耗电
  if (input.batteryPercent <= 15) {
    k = Math.floor(k / 2);
    reasons.push('电量偏低，已降级');
  }

  if (k < 1) {
    k = 1;
    reasons.push('已压到最小 1 条');
  }

  return { k: k, reason: reasons.join('；') };
}
