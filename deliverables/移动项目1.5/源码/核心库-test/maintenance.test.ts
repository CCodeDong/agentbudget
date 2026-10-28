/**
 * 增量删除 / 压缩 / 替换 的单元测试。
 *
 * WHY THIS FILE EXISTS
 *   删除一份文档原本会触发**全量重建索引**（重切词、重建倒排表）。
 *   1000 份文档时删 10 份就是 10 次全量重建。
 *   改成墓碑标记之后，删除代价只与该文档的块数成正比。
 *
 *   但墓碑会带来一类**隐蔽的错误**：倒排表里还留着死块的下标，
 *   如果检索时不跳过它们，用户会搜到已经删掉的资料。
 *   所以这个文件重点测的就是"删了之后真的搜不到"。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { InvertedIndex, chunkDocument } from '../src/index';
import { LibraryService } from '../src/pipeline';
import { FakeOcrEngine } from '../src/ocr';
import { DocItem } from '../src/types';

const OPTS = { topK: 0, minK: 1, maxK: 10 };
const BUDGET = { latencyBudgetMs: 100000, memoryBudgetKb: 1000000, batteryPercent: 90 };

function doc(id: string, text: string): DocItem {
  return { id, title: 't-' + id, source: 'note', uri: 'mem://' + id, addedAt: 1, text };
}

/** 造一份足够长、会产生多个块的文档。 */
function longDoc(id: string, marker: string): DocItem {
  // 用同一个标记词重复，保证能稳定检索到
  return doc(id, (marker + '的内容').repeat(120));
}

// ---------------------------------------------------------------------------
// InvertedIndex 的删除语义
// ---------------------------------------------------------------------------

test('删除：移除后活块数下降，且检索不到', () => {
  const idx = new InvertedIndex();
  idx.addDocument(doc('a', '独特词汇甲乙丙丁'));
  idx.addDocument(doc('b', '另一份完全不同的资料'));

  assert.equal(idx.score('甲乙丙丁').length, 1);
  const removed = idx.removeDocument('a');
  assert.ok(removed > 0, '应删掉至少一个块');
  assert.equal(idx.score('甲乙丙丁').length, 0, '删除后必须检索不到');
  assert.equal(idx.size(), 1, '活块数应只剩 b 的块');
});

test('删除：不影响其他文档', () => {
  const idx = new InvertedIndex();
  idx.addDocument(doc('a', '独特词汇甲乙丙'));
  idx.addDocument(doc('b', '另一份独特词汇丁戊己'));
  idx.removeDocument('a');
  const cands = idx.score('丁戊己');
  assert.equal(cands.length, 1);
  assert.equal(cands[0].chunk.docId, 'b');
});

test('删除：不存在的 docId 返回 0', () => {
  const idx = new InvertedIndex();
  idx.addDocument(doc('a', '内容'));
  assert.equal(idx.removeDocument('nope'), 0);
  assert.equal(idx.size(), 1);
});

test('删除：多块文档的所有块都被删掉', () => {
  const idx = new InvertedIndex();
  const d = longDoc('big', '标记词');
  const added = idx.addDocument(d, { size: 100, overlap: 10 });
  assert.ok(added > 1, '前提：这份文档应产生多个块');

  const removed = idx.removeDocument('big');
  assert.equal(removed, added, '删除数应等于加入数');
  assert.equal(idx.size(), 0);
  assert.equal(idx.score('标记词').length, 0);
});

test('删除：墓碑计数正确（多文档、比例低于阈值时不压缩）', () => {
  const idx = new InvertedIndex();
  // 造 10 份单块文档，删 1 份 → 墓碑比例 10% < 20% 阈值，不触发压缩
  for (let i = 0; i < 10; i++) {
    idx.addChunk({ id: 'c' + i, docId: 'd' + i, seq: 0, start: 0, end: 1, text: '内容' + i });
  }
  assert.equal(idx.tombstoneCount(), 0);
  idx.removeDocument('d0');
  assert.equal(idx.tombstoneCount(), 1, '比例低于阈值时应保留墓碑');
  assert.equal(idx.size(), 9);
});

test('删除：只剩一份文档时删掉会连墓碑一起清空（自动压缩到空）', () => {
  const idx = new InvertedIndex();
  idx.addDocument(doc('a', 'x'.repeat(500)), { size: 100, overlap: 0 });
  const n = idx.size();
  assert.ok(n > 1);
  idx.removeDocument('a');
  // 墓碑比例 100% → 立即自动压缩 → 索引变空
  assert.equal(idx.size(), 0);
  assert.equal(idx.tombstoneCount(), 0);
});

test('删除：avgDocLength 只统计活块', () => {
  const idx = new InvertedIndex();
  // 一份很长的、一份很短的
  idx.addDocument(doc('long', '词'.repeat(2000)));
  idx.addDocument(doc('short', '短'));
  const before = idx.avgDocLength();
  idx.removeDocument('long');
  const after = idx.avgDocLength();
  assert.ok(after < before, '删掉长文档后平均长度应变小');
  assert.ok(after > 0);
});

test('删除：getChunk 按活块序号映射（跳过墓碑）', () => {
  const idx = new InvertedIndex();
  idx.addChunk({ id: 'c0', docId: 'd0', seq: 0, start: 0, end: 1, text: '甲' });
  idx.addChunk({ id: 'c1', docId: 'd1', seq: 0, start: 0, end: 1, text: '乙' });
  idx.addChunk({ id: 'c2', docId: 'd2', seq: 0, start: 0, end: 1, text: '丙' });
  idx.removeDocument('d1');
  assert.equal(idx.size(), 2);
  assert.equal(idx.getChunk(0).id, 'c0');
  assert.equal(idx.getChunk(1).id, 'c2', '第二活块应是 c2，不是被删的 c1');
});

// ---------------------------------------------------------------------------
// 压缩
// ---------------------------------------------------------------------------

test('压缩：清掉墓碑且不改变检索结果', () => {
  const idx = new InvertedIndex();
  idx.addDocument(doc('a', '甲乙丙'));
  idx.addDocument(doc('b', '丁戊己'));
  idx.addDocument(doc('c', '庚辛壬'));

  idx.removeDocument('b');
  const beforeIds = idx.score('甲').map((c) => c.chunk.id);

  idx.compact();
  assert.equal(idx.tombstoneCount(), 0, '压缩后不应有墓碑');
  assert.equal(idx.size(), 2);

  const afterIds = idx.score('甲').map((c) => c.chunk.id);
  assert.deepEqual(afterIds, beforeIds, '压缩不应改变检索结果');
});

test('压缩：压缩后仍能检索到其他文档', () => {
  const idx = new InvertedIndex();
  idx.addDocument(doc('a', '保留的内容甲乙'));
  idx.addDocument(doc('b', '要删的内容丙丁'));
  idx.removeDocument('b');
  idx.compact();
  const cands = idx.score('甲乙');
  assert.equal(cands.length, 1);
  assert.equal(cands[0].chunk.docId, 'a');
});

test('压缩：墓碑比例达阈值时自动触发', () => {
  const idx = new InvertedIndex();
  for (let i = 0; i < 10; i++) {
    idx.addChunk({ id: 'k' + i, docId: 'doc' + i, seq: 0, start: 0, end: 1, text: '内容' + i });
  }

  // 删第 1 个：1/10 = 10% < 20% → 不压缩
  idx.removeDocument('doc0');
  assert.equal(idx.tombstoneCount(), 1);
  assert.equal(idx.size(), 9);

  // 删第 2 个：2/10 = 20% ≥ 20% → 自动压缩，墓碑归零
  idx.removeDocument('doc1');
  assert.equal(idx.tombstoneCount(), 0, '达到阈值应自动压缩');
  assert.equal(idx.size(), 8);

  // 删第 3 个：此时分母已变为 8，1/8 = 12.5% < 20% → 不压缩
  idx.removeDocument('doc2');
  assert.equal(idx.tombstoneCount(), 1);
  assert.equal(idx.size(), 7, '活块数始终正确');
});

test('压缩：空索引安全', () => {
  const idx = new InvertedIndex();
  idx.compact();
  assert.equal(idx.size(), 0);
  assert.equal(idx.avgDocLength(), 0);
});

// ---------------------------------------------------------------------------
// 替换
// ---------------------------------------------------------------------------

test('替换：新内容可检索，旧内容检索不到', () => {
  const idx = new InvertedIndex();
  idx.addDocument(doc('a', '旧内容甲乙丙'));
  const n = idx.replaceDocument(doc('a', '新内容丁戊己'));
  assert.ok(n > 0);
  assert.equal(idx.score('甲乙丙').length, 0, '旧内容不应再命中');
  assert.equal(idx.score('丁戊己').length, 1, '新内容应命中');
});

test('替换：不产生重复块 id', () => {
  const idx = new InvertedIndex();
  // 三版内容**刻意不共享任何汉字**——中文单字索引下，
  // 只要有一个共同字（比如"版"），旧内容的查询仍会命中新块，
  // 那样就测不出"替换是否真的生效"。
  idx.addDocument(doc('a', '甲乙丙'));
  idx.replaceDocument(doc('a', '丁戊己'));
  idx.replaceDocument(doc('a', '庚辛壬'));

  assert.equal(idx.score('庚辛壬').length, 1, '当前版本应命中');
  assert.equal(idx.score('甲乙丙').length, 0, '第一版不应命中');
  assert.equal(idx.score('丁戊己').length, 0, '第二版不应命中');
  assert.equal(idx.size(), 1, '活块数应只有 1');
});

test('替换：活块数不会无限增长', () => {
  const idx = new InvertedIndex();
  idx.addDocument(doc('a', '内容'));
  const base = idx.size();
  for (let i = 0; i < 5; i++) {
    idx.replaceDocument(doc('a', '内容第' + i + '版'));
  }
  assert.equal(idx.size(), base, '反复替换后活块数应稳定');
});

// ---------------------------------------------------------------------------
// 流水线层
// ---------------------------------------------------------------------------

test('流水线：删除走增量路径，其余文档仍可检索', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const a = await svc.importDocument({ title: 'a', source: 'note', uri: 'u1', text: '甲乙丙独特词汇' });
  await svc.importDocument({ title: 'b', source: 'note', uri: 'u2', text: '丁戊己独特词汇' });

  assert.equal(svc.removeDocument(a.docId), true);
  const q1 = svc.query('甲乙丙', BUDGET, OPTS);
  assert.equal(q1.hits.length, 0, '删掉的资料不应命中');
  const q2 = svc.query('丁戊己', BUDGET, OPTS);
  assert.ok(q2.hits.length >= 1, '未删的资料仍应命中');
});

test('流水线：删除不存在的文档返回 false', () => {
  const svc = new LibraryService(new FakeOcrEngine());
  assert.equal(svc.removeDocument('nope'), false);
});

test('流水线：替换文档后检索到新内容', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const a = await svc.importDocument({ title: 'a', source: 'note', uri: 'u1', text: '原始内容甲乙' });
  const r = await svc.replaceDocument(a.docId, { title: 'a', source: 'note', uri: 'u1', text: '更新内容丙丁' });
  assert.equal(r.ok, true);
  assert.equal(svc.docCount(), 1, '替换不应增加文档数');
  assert.equal(svc.query('甲乙', BUDGET, OPTS).hits.length, 0);
  assert.ok(svc.query('丙丁', BUDGET, OPTS).hits.length >= 1);
});

test('流水线：替换不存在的文档返回失败', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const r = await svc.replaceDocument('nope', { title: 'x', source: 'note', uri: 'u', text: '内容' });
  assert.equal(r.ok, false);
});

test('流水线：替换时 OCR 失败则保留原内容', async () => {
  const engine = new FakeOcrEngine().presetFailure('img://bad');
  const svc = new LibraryService(engine);
  const a = await svc.importDocument({ title: 'a', source: 'note', uri: 'u1', text: '原始内容甲乙' });
  const r = await svc.replaceDocument(a.docId, { title: 'a', source: 'camera', uri: 'img://bad' });
  assert.equal(r.ok, false);
  assert.ok(svc.query('甲乙', BUDGET, OPTS).hits.length >= 1, '原内容应完好');
});

test('流水线：墓碑数可查询，手动压缩后归零', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const a = await svc.importDocument({ title: 'a', source: 'note', uri: 'u1', text: 'x'.repeat(800) });
  await svc.importDocument({ title: 'b', source: 'note', uri: 'u2', text: 'y'.repeat(800) });
  svc.removeDocument(a.docId);
  const t = svc.tombstoneCount();
  svc.compactIndex();
  assert.equal(svc.tombstoneCount(), 0);
  assert.ok(t >= 0);
});

test('流水线：删干净后再查询不崩溃', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const a = await svc.importDocument({ title: 'a', source: 'note', uri: 'u1', text: '内容甲乙' });
  svc.removeDocument(a.docId);
  const q = svc.query('甲乙', BUDGET, OPTS);
  assert.equal(q.hits.length, 0);
  assert.equal(svc.docCount(), 0);
  assert.equal(svc.chunkCount(), 0);
});
