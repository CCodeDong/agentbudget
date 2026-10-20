/**
 * 微基准：建索引 / 增量删除 vs 全量重建 / 检索。
 *
 * WHY THIS EXISTS
 *   把 removeDocument 从"全量重建索引"改成"墓碑标记"是一次**性能改动**，
 *   而性能改动如果没有数字，就只是"我觉得会更快"。
 *
 *   这个项目已经栽过三次"看起来合理的推断"，所以这里量出来。
 *
 * RUN
 *   python tools/olib.py bench
 *
 * 注意：这是**单机微基准**，数值只用于比较两种实现的相对差距，
 *       不能当作手机上的性能承诺。
 */

import { InvertedIndex } from '../src/index';
import { LibraryService } from '../src/pipeline';
import { FakeOcrEngine } from '../src/ocr';
import { DocItem } from '../src/types';

const OPTS = { topK: 0, minK: 1, maxK: 10 };
const BUDGET = { latencyBudgetMs: 100000, memoryBudgetKb: 1000000, batteryPercent: 90 };

function makeDoc(id: string): DocItem {
  // 约 1,200 字符的合成文档，切成 5 块左右
  const body = ('第' + id + '份资料的内容：离线检索需要在本地建立倒排索引，' +
    '并用 BM25 对候选片段打分，最后按得分分布决定返回几段。').repeat(12);
  return { id, title: 'doc-' + id, source: 'note', uri: 'mem://' + id, addedAt: 1, text: body };
}

function ms(fn: () => void): number {
  const t0 = process.hrtime.bigint();
  fn();
  const t1 = process.hrtime.bigint();
  return Number(t1 - t0) / 1e6;
}

function buildIndex(n: number): InvertedIndex {
  const idx = new InvertedIndex();
  for (let i = 0; i < n; i++) {
    idx.addDocument(makeDoc('d' + i));
  }
  return idx;
}

function benchBuild(n: number): void {
  const t = ms(() => { buildIndex(n); });
  const idx = buildIndex(n);
  console.log(`  建索引 ${n} 份文档（${idx.size()} 块）：${t.toFixed(1)} ms`);
}

function benchRemoveIncremental(n: number, del: number): void {
  const idx = buildIndex(n);
  const t = ms(() => {
    for (let i = 0; i < del; i++) {
      idx.removeDocument('d' + i);
    }
  });
  console.log(`  增量删除 ${del} 份（库 ${n} 份）：${t.toFixed(1)} ms  → 剩余 ${idx.size()} 块`);
}

function benchFullRebuild(n: number, del: number): void {
  // 模拟"旧的实现"：每删一份就全量重建
  const docs: DocItem[] = [];
  for (let i = 0; i < n; i++) docs.push(makeDoc('d' + i));
  const t = ms(() => {
    for (let i = 0; i < del; i++) {
      const keep = docs.filter((d) => d.id !== 'd' + i);
      const idx = new InvertedIndex();
      for (const d of keep) idx.addDocument(d);
    }
  });
  console.log(`  全量重建 ${del} 次（库 ${n} 份）：${t.toFixed(1)} ms  ← 旧实现的做法`);
}

function benchQuery(n: number, times: number): void {
  const idx = buildIndex(n);
  const t = ms(() => {
    for (let i = 0; i < times; i++) {
      idx.score('倒排索引 BM25 得分分布');
    }
  });
  console.log(`  检索 ${times} 次（库 ${n} 份 / ${idx.size()} 块）：${t.toFixed(1)} ms  → 单次 ${(t / times).toFixed(2)} ms`);
}

async function benchPipeline(n: number): Promise<void> {
  const svc = new LibraryService(new FakeOcrEngine());
  const t0 = process.hrtime.bigint();
  for (let i = 0; i < n; i++) {
    await svc.importDocument({ title: 'd' + i, source: 'note', uri: 'u' + i, text: makeDoc('d' + i).text });
  }
  const t1 = process.hrtime.bigint();
  const impl = Number(t1 - t0) / 1e6;

  const q = svc.query('倒排索引', BUDGET, OPTS);
  console.log(`  流水线导入 ${n} 份：${impl.toFixed(1)} ms  → ${svc.chunkCount()} 块`);
  console.log(`  查询命中 ${q.hits.length} 条（kSource=${q.kSource}, k=${q.k}, 候选 ${q.diagnostics.candidateCount}）`);
}

async function main(): Promise<void> {
  console.log('=== offlinelib-core 微基准 ===');
  console.log('（单机数值，仅用于比较相对差距，不代表手机性能）\n');

  console.log('[1] 建索引');
  benchBuild(100);
  benchBuild(500);
  benchBuild(1000);

  console.log('\n[2] 检索');
  benchQuery(1000, 100);

  console.log('\n[3] 删除：增量 vs 全量重建（这是本次改动的核心）');
  benchRemoveIncremental(1000, 10);
  benchFullRebuild(1000, 10);

  console.log('\n[4] 流水线端到端');
  await benchPipeline(300);
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
