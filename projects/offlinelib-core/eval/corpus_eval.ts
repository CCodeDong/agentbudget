/**
 * 真实语料检索评估。
 *
 * WHY THIS EXISTS
 *   老师对开题 PPT 的批评里有一条："OCR 与全文检索技术路线**无法核实**"。
 *
 *   在那之前，我们所有的测试都用手写的短文本——这只能证明"代码没崩"，
 *   不能证明"在真实资料上检索得准"。
 *
 *   这个脚本用**仓库自己的 64 个 markdown 文档**（约 762 KB）当语料，
 *   自动生成"已知答案"的查询，量出真实的召回率与排序质量。
 *
 * 方法（Known-Item Retrieval）
 *   1. 把每个文档切块、建索引
 *   2. 对每个抽样块，**取它里面最罕见的两三个词**当作查询
 *      —— 模拟"我记得它提到过 X 和 Y"这种真实提问方式
 *   3. 正确答案 = 该块所属的文档
 *   4. 看 top-k 里有没有命中该文档，并记录排名
 *
 *   为什么不用"复制一段原文当查询"：那样 BM25 一定命中，测不出什么。
 *   用罕见词组合更接近真实使用，也更能区分策略好坏。
 *
 * RUN
 *   python tools/olib.py eval
 */

import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { join, basename } from 'node:path';

import { InvertedIndex, chunkDocument, DEFAULT_CHUNK_OPTIONS } from '../src/index';
import { search } from '../src/search';
import { DocItem, SearchOptions, Chunk } from '../src/types';
import { terms } from '../src/tokenize';

// ---------------------------------------------------------------------------
// 语料加载
// ---------------------------------------------------------------------------

/** 递归收集 markdown 文件。跳过体积过小或明显的噪音目录。 */
function collectMarkdown(root: string, excludes: string[], out: string[] = []): string[] {
  if (!existsSync(root)) {
    return out;
  }
  const st = statSync(root);
  if (st.isFile()) {
    if (root.endsWith('.md') && st.size > 800) {
      out.push(root);
    }
    return out;
  }
  let names: string[] = [];
  try {
    names = readdirSync(root);
  } catch (e) {
    return out;
  }
  for (let i = 0; i < names.length; i++) {
    const name = names[i];
    if (excludes.indexOf(name) >= 0) {
      continue;
    }
    collectMarkdown(join(root, name), excludes, out);
  }
  return out;
}

interface LoadedCorpus {
  docs: DocItem[];
  totalChars: number;
}

function loadCorpus(root: string): LoadedCorpus {
  const EXCLUDES = ['node_modules', 'oh_modules', 'dist', '_hvhome', '_npmcache',
    'build', 'target', '.git', '_out', '.hvigor'];
  const files = collectMarkdown(root, EXCLUDES);
  const docs: DocItem[] = [];
  let totalChars = 0;
  for (let i = 0; i < files.length; i++) {
    let text = '';
    try {
      text = readFileSync(files[i], 'utf8');
    } catch (e) {
      continue;
    }
    if (text.length < 200) {
      continue;
    }
    const id = 'doc' + i.toString();
    const d: DocItem = {
      id: id,
      title: basename(files[i]),
      source: 'file',
      uri: files[i],
      addedAt: 0,
      text: text
    };
    docs.push(d);
    totalChars += text.length;
  }
  return { docs: docs, totalChars: totalChars };
}

// ---------------------------------------------------------------------------
// 查询生成
// ---------------------------------------------------------------------------

/**
 * 生成"已知答案"的查询。
 *
 * 做法：对每个抽样块，按**词在语料中的稀有程度**排序，
 * 取最罕见的两三个词（长度≥2，避免单字过于泛化）拼成查询。
 */
function makeQueries(index: InvertedIndex, chunks: Chunk[], sample: number, seed: number): Query[] {
  // 先统计每个词出现在多少个块里（用于判断稀有度）
  const df: Map<string, number> = new Map<string, number>();
  for (let i = 0; i < chunks.length; i++) {
    const seen: Map<string, boolean> = new Map<string, boolean>();
    const ts = terms(chunks[i].text);
    for (let j = 0; j < ts.length; j++) {
      const t = ts[j];
      if (t.length < 2) {
        continue;
      }
      if (seen.has(t)) {
        continue;
      }
      seen.set(t, true);
      df.set(t, (df.get(t) ?? 0) + 1);
    }
  }

  const out: Query[] = [];
  // 确定性抽样：固定步长，保证每次运行结果一致
  const step = Math.max(1, Math.floor(chunks.length / sample));
  for (let i = 0; i < chunks.length && out.length < sample; i += step) {
    const c = chunks[i];
    const ts = terms(c.text);
    const uniq: string[] = [];
    const seen: Map<string, boolean> = new Map<string, boolean>();
    for (let j = 0; j < ts.length; j++) {
      const t = ts[j];
      if (t.length < 2 || seen.has(t)) {
        continue;
      }
      // 太常见的词区分度差，跳过
      const d = df.get(t) ?? 999;
      if (d <= 2 || d > chunks.length / 5) {
        continue;
      }
      seen.set(t, true);
      uniq.push(t);
    }
    if (uniq.length < 2) {
      continue;
    }
    // 按 df 升序（越罕见越靠前），取前 3 个
    uniq.sort((a: string, b: string) => (df.get(a) ?? 0) - (df.get(b) ?? 0));
    const picked: string[] = [];
    for (let j = 0; j < uniq.length && picked.length < 3; j++) {
      picked.push(uniq[j]);
    }
    if (picked.length < 2) {
      continue;
    }
    const q: Query = {
      text: picked.join(' '),
      goldDocId: c.docId,
      goldChunkId: c.id
    };
    out.push(q);
  }
  return out;
}

interface Query {
  text: string;
  goldDocId: string;
  goldChunkId: string;
}

// ---------------------------------------------------------------------------
// 指标
// ---------------------------------------------------------------------------

interface Metrics {
  name: string;
  /** 正确文档出现在返回结果里的比例。 */
  recall: number;
  /** 正确块的排名倒数均值（未命中记 0）。 */
  mrr: number;
  /** 返回结果里属于正确文档的比例。 */
  precision: number;
  /** 平均返回条数。 */
  avgReturned: number;
  /** 完全命中正确块的比例。 */
  chunkHit: number;
}

function evaluate(index: InvertedIndex, queries: Query[], opts: SearchOptions, name: string): Metrics {
  let recallHits = 0;
  let mrrSum = 0;
  let precisionSum = 0;
  let returnedSum = 0;
  let chunkHits = 0;

  for (let i = 0; i < queries.length; i++) {
    const q = queries[i];
    const r = search(index, q.text, opts);
    returnedSum += r.hits.length;

    let rank = -1;
    let chunkRank = -1;
    let relevant = 0;
    for (let j = 0; j < r.hits.length; j++) {
      const h = r.hits[j];
      if (h.chunk.docId === q.goldDocId) {
        relevant += 1;
        if (rank < 0) {
          rank = j;
        }
      }
      if (h.chunk.id === q.goldChunkId && chunkRank < 0) {
        chunkRank = j;
      }
    }
    if (rank >= 0) {
      recallHits += 1;
      mrrSum += 1 / (rank + 1);
    }
    if (chunkRank >= 0) {
      chunkHits += 1;
    }
    if (r.hits.length > 0) {
      precisionSum += relevant / r.hits.length;
    }
  }

  const n = Math.max(queries.length, 1);
  return {
    name: name,
    recall: (recallHits / n) * 100,
    mrr: mrrSum / n,
    precision: (precisionSum / n) * 100,
    avgReturned: returnedSum / n,
    chunkHit: (chunkHits / n) * 100
  };
}

function pct(v: number): string {
  return v.toFixed(1) + '%';
}

// ---------------------------------------------------------------------------

function main(): void {
  const root = process.argv.length > 2 ? process.argv[2] : '.';
  console.log('=== 真实语料检索评估 ===');
  console.log('方法：已知答案检索（用块的罕见词组合作查询）\n');

  const corpus = loadCorpus(root);
  if (corpus.docs.length === 0) {
    console.log('  未找到语料。用法: python tools/olib.py eval');
    return;
  }
  console.log(`语料：${corpus.docs.length} 个文档，共 ${(corpus.totalChars / 1024).toFixed(0)} KB`);

  // 建索引
  const t0 = process.hrtime.bigint();
  const index = new InvertedIndex();
  const allChunks: Chunk[] = [];
  for (let i = 0; i < corpus.docs.length; i++) {
    const cs = chunkDocument(corpus.docs[i], DEFAULT_CHUNK_OPTIONS);
    for (let j = 0; j < cs.length; j++) {
      allChunks.push(cs[j]);
      index.addChunk(cs[j]);
    }
  }
  const buildMs = Number(process.hrtime.bigint() - t0) / 1e6;
  console.log(`索引：${index.chunkCount()} 个片段（${buildMs.toFixed(0)} ms）`);

  // 生成查询
  const queries = makeQueries(index, allChunks, 150, 7);
  console.log(`查询：自动生成 ${queries.length} 条，均带已知答案\n`);
  if (queries.length === 0) {
    console.log('  生成的查询为 0，语料可能太小或无区分度。');
    return;
  }

  // 对照实验：固定 k vs 自适应 k
  const results: Metrics[] = [];
  for (const k of [1, 3, 5, 10]) {
    const o: SearchOptions = { topK: k, minK: 1, maxK: 50 };
    results.push(evaluate(index, queries, o, `固定 k=${k}`));
  }
  const auto: SearchOptions = { topK: 0, minK: 1, maxK: 10 };
  results.push(evaluate(index, queries, auto, '自适应（得分分布）'));

  console.log('策略                       召回率    MRR    精确率   平均返回   精确块命中');
  console.log('-'.repeat(80));
  for (let i = 0; i < results.length; i++) {
    const r = results[i];
    console.log(
      `${r.name.padEnd(24)} ${pct(r.recall).padStart(7)} ${r.mrr.toFixed(3).padStart(7)} ` +
      `${pct(r.precision).padStart(8)} ${r.avgReturned.toFixed(1).padStart(9)} ${pct(r.chunkHit).padStart(10)}`
    );
  }

  console.log('\n指标含义：');
  console.log('  召回率   = 正确文档出现在返回结果里的比例（越高越不容易"找不到"）');
  console.log('  MRR      = 正确文档平均排名的倒数（越高说明排在越前面）');
  console.log('  精确率   = 返回结果里属于正确文档的比例（越高说明越不啰嗦）');
  console.log('  精确块命中 = 直接命中目标片段的比例');
}

main();
