/**
 * 相邻命中合并的测试。
 *
 * 为什么单独开一个文件：
 *   合并逻辑有几条容易被写错却"看起来对"的地方：
 *     · 文本拼接时少补或多补几个字符
 *     · 高亮坐标忘了做偏移换算
 *     · 得分被累加（会让长文档凭空得高分）
 *   这些错误在真实语料上都不一定暴露，必须逐条钉住。
 *
 * ⚠️ 断言刻意写得比实现更"笨"：期望值用原文切片算出来，
 *    而不是复用实现里的拼接公式 —— 否则实现错了测试也跟着错。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { InvertedIndex, chunkDocument, DEFAULT_CHUNK_OPTIONS } from '../src/index';
import { search, mergeAdjacentHits } from '../src/search';
import { DocItem, Hit, Chunk, SearchOptions, Span } from '../src/types';

const KEYWORD = '关键词';

function makeDoc(id: string, text: string): DocItem {
  return { id: id, title: 't-' + id, source: 'note', uri: 'mem://' + id, addedAt: 1, text: text };
}

/** 手工构造一个块，用于精确控制范围（chunkDocument 自动产生重叠，不好造"有空隙"的情形）。 */
function makeChunk(docId: string, seq: number, start: number, text: string): Chunk {
  return {
    id: docId + '#' + seq.toString(),
    docId: docId, seq: seq, start: start, end: start + text.length, text: text
  };
}

function makeHit(chunk: Chunk, score: number, matched: Map<string, number>, spans: Span[]): Hit {
  return { chunk: chunk, score: score, matched: matched, spans: spans };
}

function oneTerm(t: string, n: number): Map<string, number> {
  const m = new Map<string, number>();
  m.set(t, n);
  return m;
}

// ---------------------------------------------------------------------------
// 基本合并
// ---------------------------------------------------------------------------

test('相邻且重叠的两块合并成一条', () => {
  // 关键词放在 0 和 303，跨 chunk0[0,240) 与 chunk1[200,440)
  const body = KEYWORD + 'A'.repeat(300) + KEYWORD + 'B'.repeat(300);
  const doc = makeDoc('d1', body);
  const idx = new InvertedIndex();
  idx.addDocument(doc);

  const r = search(idx, KEYWORD, { topK: 10, minK: 1, maxK: 10, mergeAdjacent: true });

  assert.equal(r.hits.length, 1, '两块应合并成一条');
  // 合并区域 = 从 chunk0 起点到 chunk1 终点 = [0, 440)
  assert.equal(r.hits[0].chunk.start, 0);
  assert.equal(r.hits[0].chunk.end, 440);
  assert.equal(r.hits[0].chunk.text, body.substring(0, 440), '合并文本应与原文切片完全一致');
});

test('合并后记录被合并的块数', () => {
  const body = KEYWORD + 'A'.repeat(300) + KEYWORD + 'B'.repeat(300);
  const idx = new InvertedIndex();
  idx.addDocument(makeDoc('d1', body));

  const r = search(idx, KEYWORD, { topK: 10, minK: 1, maxK: 10, mergeAdjacent: true });
  assert.equal(r.hits[0].mergedCount, 2);
});

test('不合并时保持原样', () => {
  const body = KEYWORD + 'A'.repeat(300) + KEYWORD + 'B'.repeat(300);
  const idx = new InvertedIndex();
  idx.addDocument(makeDoc('d1', body));

  const r = search(idx, KEYWORD, { topK: 10, minK: 1, maxK: 10 });
  assert.ok(r.hits.length >= 2, '不合并时两块应各自成条');
  assert.equal(r.hits[0].mergedCount, undefined);
});

// ---------------------------------------------------------------------------
// 不该合并的情形
// ---------------------------------------------------------------------------

test('同一文档但范围有空隙的不合并', () => {
  const c1 = makeChunk('d1', 0, 0, '关键词一');
  const c2 = makeChunk('d1', 1, 500, '关键词二');
  const h1 = makeHit(c1, 3.0, oneTerm(KEYWORD, 1), [{ start: 0, end: 3 }]);
  const h2 = makeHit(c2, 2.0, oneTerm(KEYWORD, 1), [{ start: 0, end: 3 }]);

  const out = mergeAdjacentHits([h1, h2]);
  assert.equal(out.length, 2, '中间隔了 497 个字符，不该合并');
});

test('不同文档即使范围相同也不合并', () => {
  const c1 = makeChunk('d1', 0, 0, '关键词一');
  const c2 = makeChunk('d2', 0, 0, '关键词二');
  const h1 = makeHit(c1, 3.0, oneTerm(KEYWORD, 1), []);
  const h2 = makeHit(c2, 2.0, oneTerm(KEYWORD, 1), []);

  const out = mergeAdjacentHits([h1, h2]);
  assert.equal(out.length, 2, '跨文档合并没有意义');
});

test('范围完全不相交的同一文档不合并', () => {
  const c1 = makeChunk('d1', 0, 0, '关键词一');
  const c2 = makeChunk('d1', 1, 10, '关键词二');   // 起点 10 > c1 终点 4
  const h1 = makeHit(c1, 3.0, oneTerm(KEYWORD, 1), []);
  const h2 = makeHit(c2, 2.0, oneTerm(KEYWORD, 1), []);

  const out = mergeAdjacentHits([h1, h2]);
  assert.equal(out.length, 2);
});

// ---------------------------------------------------------------------------
// 得分与高亮
// ---------------------------------------------------------------------------

test('合并后得分取最高分而不是相加', () => {
  const c1 = makeChunk('d1', 0, 0, '关键词一');
  const c2 = makeChunk('d1', 1, 3, '关键词二');   // 与 c1 首尾相接
  const h1 = makeHit(c1, 5.0, oneTerm(KEYWORD, 1), []);
  const h2 = makeHit(c2, 2.5, oneTerm(KEYWORD, 1), []);

  const out = mergeAdjacentHits([h1, h2]);
  assert.equal(out.length, 1);
  assert.equal(out[0].score, 5.0, '应取最高分，不是 7.5 —— 相加会把分块副作用当相关度');
});

test('合并后高亮坐标换算到新坐标系', () => {
  // c1 覆盖 [0,4)，c2 覆盖 [4,8)，c2 的高亮相对自身从 0 开始 -> 合并后应是 4
  const c1 = makeChunk('d1', 0, 0, '关键词一');
  const c2 = makeChunk('d1', 1, 4, '关键词二');
  const h1 = makeHit(c1, 5.0, oneTerm(KEYWORD, 1), [{ start: 0, end: 3 }]);
  const h2 = makeHit(c2, 2.0, oneTerm(KEYWORD, 1), [{ start: 0, end: 3 }]);

  const out = mergeAdjacentHits([h1, h2]);
  assert.equal(out.length, 1);
  assert.equal(out[0].spans.length, 2);
  // 排序后应是 [0,3) 与 [4,7)
  assert.equal(out[0].spans[0].start, 0);
  assert.equal(out[0].spans[0].end, 3);
  assert.equal(out[0].spans[1].start, 4, 'c2 的高亮应偏移 +4');
  assert.equal(out[0].spans[1].end, 7);
});

test('合并后高亮确实指向合并文本里的关键词', () => {
  const body = KEYWORD + 'A'.repeat(300) + KEYWORD + 'B'.repeat(300);
  const idx = new InvertedIndex();
  idx.addDocument(makeDoc('d1', body));

  const r = search(idx, KEYWORD, { topK: 10, minK: 1, maxK: 10, mergeAdjacent: true });
  const hit = r.hits[0];
  assert.ok(hit.spans.length >= 2, '两个关键词应各有一个高亮');

  // 这是真正该验证的：按 span 从合并文本里切出来，必须还是关键词
  for (let i = 0; i < hit.spans.length; i++) {
    const seg = hit.chunk.text.substring(hit.spans[i].start, hit.spans[i].end);
    assert.equal(seg, KEYWORD, 'span ' + i.toString() + ' 切出的内容应是关键词，实际是 ' + seg);
  }
});

test('合并后命中词频相加', () => {
  const c1 = makeChunk('d1', 0, 0, '关键词关键词');
  const c2 = makeChunk('d1', 1, 6, '关键词三');
  const h1 = makeHit(c1, 5.0, oneTerm(KEYWORD, 2), []);
  const h2 = makeHit(c2, 2.0, oneTerm(KEYWORD, 1), []);

  const out = mergeAdjacentHits([h1, h2]);
  assert.equal(out.length, 1);
  assert.equal(out[0].matched.get(KEYWORD), 3, '2 + 1 = 3');
});

// ---------------------------------------------------------------------------
// 排序与边界
// ---------------------------------------------------------------------------

test('合并后保持原有相对顺序', () => {
  // 三条命中：A(最高分, d1) / B(d2) / C(d1，与 A 相接)
  const a = makeHit(makeChunk('d1', 0, 0, '关键词一'), 9.0, oneTerm(KEYWORD, 1), []);
  const b = makeHit(makeChunk('d2', 0, 0, '关键词二'), 5.0, oneTerm(KEYWORD, 1), []);
  const c = makeHit(makeChunk('d1', 1, 4, '关键词三'), 1.0, oneTerm(KEYWORD, 1), []);

  const out = mergeAdjacentHits([a, b, c]);
  assert.equal(out.length, 2);
  assert.equal(out[0].chunk.docId, 'd1', '第一名仍应是 d1（A 与 C 合并后保留了 A 的名次）');
  assert.equal(out[0].mergedCount, 2);
  assert.equal(out[1].chunk.docId, 'd2');
});

test('空列表与单条不报错', () => {
  assert.equal(mergeAdjacentHits([]).length, 0);
  const only = makeHit(makeChunk('d1', 0, 0, '关键词'), 1.0, oneTerm(KEYWORD, 1), []);
  const out = mergeAdjacentHits([only]);
  assert.equal(out.length, 1);
  assert.equal(out[0].mergedCount, undefined, '没合并就不该有 mergedCount');
});

test('三块连续相接应全部合成一条', () => {
  const c1 = makeChunk('d1', 0, 0, '关键词一');
  const c2 = makeChunk('d1', 1, 4, '关键词二');
  const c3 = makeChunk('d1', 2, 8, '关键词三');
  const h1 = makeHit(c1, 5.0, oneTerm(KEYWORD, 1), []);
  const h2 = makeHit(c2, 4.0, oneTerm(KEYWORD, 1), []);
  const h3 = makeHit(c3, 3.0, oneTerm(KEYWORD, 1), []);

  const out = mergeAdjacentHits([h1, h2, h3]);
  assert.equal(out.length, 1);
  assert.equal(out[0].mergedCount, 3);
  assert.equal(out[0].chunk.text, '关键词一关键词二关键词三', '三块文本应完整拼回');
  assert.equal(out[0].chunk.end, 12);
});

test('合并后总文本长度等于覆盖区间长度', () => {
  const body = 'x'.repeat(120) + KEYWORD + 'y'.repeat(120) + KEYWORD + 'z'.repeat(120);
  const idx = new InvertedIndex();
  idx.addDocument(makeDoc('d1', body));

  const r = search(idx, KEYWORD, { topK: 10, minK: 1, maxK: 10, mergeAdjacent: true });
  const h = r.hits[0];
  assert.equal(h.chunk.text.length, h.chunk.end - h.chunk.start, '文本长度必须与区间长度一致');
});
