/**
 * 离线资料库核心 —— 单元测试
 *
 * WHY PLAIN node:test
 *   不引入 jest / vitest：这套测试要能在**任何一台装了 Node 的电脑上直接跑**，
 *   不需要 npm install。这直接对应老师"检索技术路线无法核实"那条批评——
 *   核实的第一步是**别人能一条命令复现**。
 *
 * RUN
 *   node --test test/
 *   或  node --test test/core.test.ts
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { tokenize, terms, isCJK } from '../src/tokenize';
import { InvertedIndex, chunkDocument, locateSpans, BM25_K1, BM25_B } from '../src/index';
import { search, diagnose, decideKByScoreGap, decideBudget, MIN_GAP_RATIO } from '../src/search';
import { DocItem, Chunk, SearchOptions } from '../src/types';

// ---------------------------------------------------------------------------
// 测试用的假数据（不依赖设备、不依赖 OCR）
// ---------------------------------------------------------------------------

function makeDoc(id: string, title: string, text: string): DocItem {
  return { id, title, source: 'note', uri: 'mem://' + id, addedAt: 0, text };
}

const DOC_A = makeDoc('a', '预算调度笔记',
  '移动端的多智能体系统存在一个矛盾：普通对话消耗一倍 token，而多智能体约为十五倍。' +
  '手机能提供的上下文窗口只有四千到八千。因此取舍是强制的。');

const DOC_B = makeDoc('b', '检索信号',
  '工具注入深度应当由检索置信度驱动，而不是由剩余预算驱动。' +
  '检索得分的分布才包含该取几个的信息。');

const DOC_C = makeDoc('c', '英文资料',
  'The Quick Brown Fox jumps over the lazy dog. BM25 ranking is a pure statistical method.');

// ---------------------------------------------------------------------------

test('切词：中文产生单字与二元组', () => {
  const toks = tokenize('离线资料库');
  const ts = toks.map((t) => t.term);
  // 单字
  assert.ok(ts.includes('离'));
  assert.ok(ts.includes('库'));
  // 二元组
  assert.ok(ts.includes('离线'));
  assert.ok(ts.includes('资料'));
  assert.ok(ts.includes('料库'));
  // 不应产生三元组
  assert.ok(!ts.includes('离线资'));
});

test('切词：不保留单字时只剩二元组', () => {
  const ts = tokenize('离线资料库', false).map((t) => t.term);
  assert.deepEqual(ts, ['离线', '线资', '资料', '料库']);
});

test('切词：英文小写化且按非字母数字切分', () => {
  const ts = terms('The Quick, Brown-Fox!');
  assert.deepEqual(ts, ['the', 'quick', 'brown', 'fox']);
});

test('切词：标点与空白不产生词项', () => {
  const ts = terms('，。！？ \t\n　');
  assert.equal(ts.length, 0);
});

test('切词：位置信息可用于高亮', () => {
  const toks = tokenize('资料库');
  const uni = toks.find((t) => t.term === '库');
  assert.ok(uni !== undefined);
  assert.equal(uni!.start, 2);
  assert.equal(uni!.end, 3);
});

test('isCJK 覆盖基本区与扩展 A', () => {
  assert.equal(isCJK('中'), true);
  assert.equal(isCJK('a'), false);
  assert.equal(isCJK('，'), false);
});

// ---------------------------------------------------------------------------

test('分块：短文本一块', () => {
  const doc = makeDoc('s', 't', '短文本');
  const cs = chunkDocument(doc, { size: 100, overlap: 10 });
  assert.equal(cs.length, 1);
  assert.equal(cs[0].text, '短文本');
  assert.equal(cs[0].start, 0);
  assert.equal(cs[0].end, 3);
});

test('分块：长文本按 step=size-overlap 递增且覆盖全文', () => {
  const text = 'x'.repeat(1000);
  const doc = makeDoc('l', 't', text);
  const cs = chunkDocument(doc, { size: 240, overlap: 40 });
  const step = 200;
  assert.equal(cs.length, Math.ceil((1000 - 240) / step) + 1);
  // 首块从 0 开始
  assert.equal(cs[0].start, 0);
  // 末块必须到达文末
  const last = cs[cs.length - 1];
  assert.equal(last.end, text.length);
  // 相邻块确实重叠 40
  for (let i = 0; i + 1 < cs.length; i++) {
    assert.equal(cs[i].end - cs[i + 1].start, 40);
  }
});

test('分块：空文本不产生块', () => {
  assert.equal(chunkDocument(makeDoc('e', 't', '')).length, 0);
});

test('分块：块 id 稳定可预测', () => {
  const cs = chunkDocument(makeDoc('doc1', 't', 'a'.repeat(500)), { size: 100, overlap: 0 });
  assert.equal(cs[0].id, 'doc1#0');
  assert.equal(cs[1].id, 'doc1#1');
});

// ---------------------------------------------------------------------------

test('索引：重复加入同一块返回 false 且不重复计数', () => {
  const idx = new InvertedIndex();
  const doc = makeDoc('d', 't', '离线资料库检索');
  const added = idx.addDocument(doc);
  assert.ok(added > 0);
  const before = idx.size();
  const again = idx.addDocument(doc);
  assert.equal(again, 0);
  assert.equal(idx.size(), before);
});

test('索引：clear 后尺寸归零', () => {
  const idx = new InvertedIndex();
  idx.addDocument(DOC_A);
  assert.ok(idx.size() > 0);
  idx.clear();
  assert.equal(idx.size(), 0);
  assert.equal(idx.avgDocLength(), 0);
});

test('索引：空索引检索返回空', () => {
  const idx = new InvertedIndex();
  assert.deepEqual(idx.score('任意'), []);
});

test('索引：空查询返回空', () => {
  const idx = new InvertedIndex();
  idx.addDocument(DOC_A);
  assert.deepEqual(idx.score('   '), []);
});

test('BM25：命中块的得分高于未命中块', () => {
  const idx = new InvertedIndex();
  idx.addDocument(DOC_A);   // 预算话题，不含「检索」
  idx.addDocument(DOC_B);   // 含「检索置信度」
  idx.addDocument(DOC_C);   // 英文资料
  const cands = idx.score('检索置信度');
  assert.ok(cands.length > 0);
  // 第一应来自 DOC_B（唯一含该词的资料）
  assert.equal(cands[0].chunk.docId, 'b');
});

test('BM25：得分降序且全部非负', () => {
  const idx = new InvertedIndex();
  idx.addDocument(DOC_A);
  idx.addDocument(DOC_B);
  const cands = idx.score('检索');
  for (let i = 0; i + 1 < cands.length; i++) {
    assert.ok(cands[i].score >= cands[i + 1].score, '得分必须降序');
  }
  for (const c of cands) {
    assert.ok(c.score >= 0, '得分必须非负');
  }
});

test('BM25：参数为文献常用值', () => {
  assert.equal(BM25_K1, 1.5);
  assert.equal(BM25_B, 0.75);
});

test('BM25：词项频率越高得分越高（同长度块）', () => {
  const idx = new InvertedIndex();
  idx.addChunk({ id: 'x1', docId: 'x', seq: 0, start: 0, end: 4, text: '检索检索' });
  idx.addChunk({ id: 'x2', docId: 'x', seq: 1, start: 0, end: 4, text: '检索其他' });
  const cands = idx.score('检索');
  const a = cands.find((c) => c.chunk.id === 'x1')!;
  const b = cands.find((c) => c.chunk.id === 'x2')!;
  assert.ok(a.score > b.score, 'TF 更高者得分应更高');
});

// ---------------------------------------------------------------------------

test('高亮：定位所有出现位置并合并不重叠区间', () => {
  const spans = locateSpans('检索检索检索', new Map([['检索', 3]]));
  assert.equal(spans.length, 1);
  assert.deepEqual(spans[0], { start: 0, end: 6 });
});

test('高亮：大小写不敏感', () => {
  const spans = locateSpans('BM25 Ranking', new Map([['ranking', 1]]));
  assert.equal(spans.length, 1);
  assert.deepEqual(spans[0], { start: 5, end: 12 });
});

test('高亮：未命中的词项不产生区间', () => {
  const spans = locateSpans('无关文本', new Map([['检索', 1]]));
  assert.equal(spans.length, 0);
});

// ---------------------------------------------------------------------------

test('诊断：空候选时字段为零值', () => {
  const d = diagnose([]);
  assert.equal(d.candidateCount, 0);
  assert.equal(d.maxGapAt, -1);
});

test('自适应 k：有明显断层时在断层处截断', () => {
  // 构造得分 [10, 9, 1]：第二与第三之间落差 8/9 ≈ 0.89
  const cands = [
    { index: 0, chunk: fakeChunk('a'), score: 10, matched: new Map<string, number>() },
    { index: 1, chunk: fakeChunk('b'), score: 9, matched: new Map<string, number>() },
    { index: 2, chunk: fakeChunk('c'), score: 1, matched: new Map<string, number>() }
  ];
  const d = diagnose(cands);
  assert.ok(d.maxGap > 0.8);
  assert.equal(d.maxGapAt, 1);
  assert.equal(decideKByScoreGap(cands, 1, 10), 2, '应保留断层之前的 2 条');
});

test('自适应 k：分布平坦时取上界', () => {
  const cands = [
    { index: 0, chunk: fakeChunk('a'), score: 10, matched: new Map<string, number>() },
    { index: 1, chunk: fakeChunk('b'), score: 9.9, matched: new Map<string, number>() },
    { index: 2, chunk: fakeChunk('c'), score: 9.8, matched: new Map<string, number>() }
  ];
  const d = diagnose(cands);
  assert.ok(d.maxGap < MIN_GAP_RATIO, '平坦分布的落差应低于阈值');
  assert.equal(decideKByScoreGap(cands, 1, 10), 3, '应取 min(上界, 候选数)');
});

test('自适应 k：被 minK / maxK / 候选数三重夹紧', () => {
  const cands = [
    { index: 0, chunk: fakeChunk('a'), score: 10, matched: new Map<string, number>() },
    { index: 1, chunk: fakeChunk('b'), score: 1, matched: new Map<string, number>() }
  ];
  // 断层在第 0 位后 → 自然 k=1
  // ① minK=2 时必须抬到 2
  assert.equal(decideKByScoreGap(cands, 2, 10), 2);
  // ② maxK=1 时必须压到 1
  assert.equal(decideKByScoreGap(cands, 1, 1), 1);
  // ③ 上界很大时保持 1 —— 夹紧只会压低 k，不会抬高
  assert.equal(decideKByScoreGap(cands, 1, 99), 1);
});

test('自适应 k：无候选返回 0', () => {
  assert.equal(decideKByScoreGap([], 1, 10), 0);
});

// ---------------------------------------------------------------------------

test('检索：固定 k 模式', () => {
  const idx = new InvertedIndex();
  // 两份资料都含「检索」，才能构成 2 个候选
  idx.addDocument(DOC_B);
  idx.addDocument(makeDoc('b2', '第二份检索资料',
    '检索深度应当由得分分布决定，这是检索系统的核心决策。'));
  const opts: SearchOptions = { topK: 2, minK: 1, maxK: 10 };
  const r = search(idx, '检索', opts);
  assert.equal(r.kSource, 'fixed');
  assert.equal(r.k, 2);
  assert.equal(r.hits.length, 2);
  // 每条命中都带高亮区间
  for (const h of r.hits) {
    assert.ok(h.spans.length > 0, '命中必须带高亮');
  }
});

test('检索：自适应模式并报告 kSource', () => {
  const idx = new InvertedIndex();
  idx.addDocument(DOC_A);
  idx.addDocument(DOC_B);
  idx.addDocument(DOC_C);
  const r = search(idx, '检索置信度', { topK: 0, minK: 1, maxK: 5 });
  assert.equal(r.kSource, 'score-gap');
  assert.ok(r.k >= 1);
  assert.ok(r.hits.length <= 5);
  // 诊断信息必须与命中数一致
  assert.ok(r.diagnostics.candidateCount >= r.hits.length);
});

test('检索：固定 k 大于候选数时被夹紧', () => {
  const idx = new InvertedIndex();
  idx.addDocument(DOC_A);
  const r = search(idx, '检索', { topK: 999, minK: 1, maxK: 999 });
  assert.ok(r.k <= r.diagnostics.candidateCount);
});

test('检索：无结果时不崩溃', () => {
  const idx = new InvertedIndex();
  idx.addDocument(DOC_A);
  // 必须用**纯 ASCII** 的查询：中文单字索引下，几乎任何中文查询都会命中
  // 某个常用字（如「的」），因此"无结果"要用文档里根本不存在的英文串来构造。
  const r = search(idx, 'zzzqqq', { topK: 5, minK: 1, maxK: 10 });
  assert.equal(r.k, 0);
  assert.equal(r.hits.length, 0);
});

// ---------------------------------------------------------------------------

test('预算决策：受时间限制时按时间算', () => {
  const d = decideBudget({ latencyBudgetMs: 60, memoryBudgetKb: 100000, batteryPercent: 80 }, 240);
  assert.ok(d.k >= 1);
  assert.match(d.reason, /时间/);
});

test('预算决策：受内存限制时按内存算', () => {
  const d = decideBudget({ latencyBudgetMs: 100000, memoryBudgetKb: 10, batteryPercent: 80 }, 240);
  assert.ok(d.k >= 1);
  assert.match(d.reason, /内存/);
});

test('预算决策：低电量时降级', () => {
  const hi = decideBudget({ latencyBudgetMs: 600, memoryBudgetKb: 100000, batteryPercent: 80 }, 240);
  const lo = decideBudget({ latencyBudgetMs: 600, memoryBudgetKb: 100000, batteryPercent: 10 }, 240);
  assert.ok(lo.k < hi.k, '低电量应减少 k');
  assert.match(lo.reason, /电量/);
});

test('预算决策：极小预算也至少给 1 条', () => {
  const d = decideBudget({ latencyBudgetMs: 0, memoryBudgetKb: 0, batteryPercent: 5 }, 240);
  assert.equal(d.k, 1);
});

// ---------------------------------------------------------------------------

function fakeChunk(id: string): Chunk {
  return { id, docId: 'd', seq: 0, start: 0, end: 1, text: 'x' };
}
