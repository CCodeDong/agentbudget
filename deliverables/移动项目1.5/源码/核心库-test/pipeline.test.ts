/**
 * 存储 / OCR / 流水线 的单元测试。
 *
 * RUN
 *   python tools/olib.py test
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { DocStore, isValidDoc, isValidSource, makeDocId, SNAPSHOT_VERSION }
  from '../src/store';
import { FakeOcrEngine, UnavailableOcrEngine, judgeOcr, DEFAULT_OCR_POLICY }
  from '../src/ocr';
import { LibraryService } from '../src/pipeline';
import { DocItem } from '../src/types';

// ---------------------------------------------------------------------------

function doc(id: string, text: string): DocItem {
  return { id, title: 't-' + id, source: 'note', uri: 'mem://' + id, addedAt: 1, text };
}

const BUDGET_GENEROUS = { latencyBudgetMs: 100000, memoryBudgetKb: 1000000, batteryPercent: 90 };
const OPTS_AUTO = { topK: 0, minK: 1, maxK: 10 };

// ---------------------------------------------------------------------------
// DocStore
// ---------------------------------------------------------------------------

test('存储：put 新文档返回 true，重复 put 返回 false 且不重复计数', () => {
  const s = new DocStore();
  assert.equal(s.put(doc('a', 'x')), true);
  assert.equal(s.put(doc('a', 'y')), false);
  assert.equal(s.size(), 1);
  // 覆盖后内容应更新
  assert.equal(s.get('a')!.text, 'y');
});

test('存储：remove 只删指定文档', () => {
  const s = new DocStore();
  s.put(doc('a', 'x'));
  s.put(doc('b', 'y'));
  assert.equal(s.remove('a'), true);
  assert.equal(s.remove('a'), false);
  assert.equal(s.size(), 1);
  assert.ok(s.has('b'));
});

test('存储：all 返回副本，改它不影响内部', () => {
  const s = new DocStore();
  s.put(doc('a', 'x'));
  const arr = s.all();
  arr.push(doc('z', 'z'));
  assert.equal(s.size(), 1);
});

test('存储：save/load 往返保持内容与顺序', () => {
  const s = new DocStore();
  s.put(doc('a', '第一份'));
  s.put(doc('b', '第二份'));
  const json = s.save();

  const s2 = new DocStore();
  const skipped = s2.load(json);
  assert.equal(skipped, 0);
  assert.equal(s2.size(), 2);
  assert.deepEqual(s2.all().map((d) => d.id), ['a', 'b']);
  assert.equal(s2.get('b')!.text, '第二份');
});

test('存储：存档带版本号', () => {
  const s = new DocStore();
  const parsed = JSON.parse(s.save());
  assert.equal(parsed.version, SNAPSHOT_VERSION);
});

test('存储：load 空串安全', () => {
  const s = new DocStore();
  assert.equal(s.load(''), 0);
  assert.equal(s.size(), 0);
});

test('存储：load 非法 JSON 安全（不抛异常）', () => {
  const s = new DocStore();
  assert.equal(s.load('{不是合法 json'), 0);
  assert.equal(s.size(), 0);
});

test('存储：load 跳过坏条目但保留好条目', () => {
  const payload = JSON.stringify({
    version: 1,
    docs: [
      doc('good', '正常'),
      { id: '', title: 't', source: 'note', uri: 'u', addedAt: 1, text: 'x' }, // 空 id
      { id: 'nosrc', title: 't', source: 'bogus', uri: 'u', addedAt: 1, text: 'x' },
      doc('good2', '也正常')
    ]
  });
  const s = new DocStore();
  assert.equal(s.load(payload), 2, '应跳过 2 条坏数据');
  assert.equal(s.size(), 2);
});

test('存储：isValidDoc 覆盖各类非法输入', () => {
  assert.equal(isValidDoc(doc('a', 'x')), true);
  assert.equal(isValidDoc((undefined as unknown) as DocItem), false);
  assert.equal(isValidDoc((null as unknown) as DocItem), false);
  assert.equal(isValidDoc({ ...doc('a', 'x'), id: '' }), false);
  assert.equal(isValidDoc({ ...doc('a', 'x'), text: (1 as unknown) as string }), false);
  assert.equal(isValidDoc({ ...doc('a', 'x'), addedAt: (NaN as unknown) as number }), false);
});

test('存储：isValidSource 只认四种来源', () => {
  assert.equal(isValidSource('camera'), true);
  assert.equal(isValidSource('note'), true);
  assert.equal(isValidSource('other' as never), false);
});

test('存储：makeDocId 唯一且可读', () => {
  const a = makeDocId(1, 1000);
  const b = makeDocId(2, 1000);
  assert.notEqual(a, b);
  assert.ok(a.startsWith('d'));
});

// ---------------------------------------------------------------------------
// OCR 抽象
// ---------------------------------------------------------------------------

test('OCR：假引擎按预设返回文本与置信度', async () => {
  const e = new FakeOcrEngine().preset('img://1', '识别出来的文字', 0.9);
  const r = await e.recognize('img://1');
  assert.equal(r.text, '识别出来的文字');
  assert.equal(r.confidence, 0.9);
  assert.equal(r.error, undefined);
});

test('OCR：假引擎可预设失败', async () => {
  const e = new FakeOcrEngine().presetFailure('img://bad');
  const r = await e.recognize('img://bad');
  assert.equal(r.text, '');
  assert.equal(r.confidence, 0);
  assert.ok(r.error !== undefined);
});

test('OCR：不可用引擎 available() 为 false', () => {
  const e = new UnavailableOcrEngine();
  assert.equal(e.available(), false);
  assert.equal(new FakeOcrEngine().available(), true);
});

test('OCR 判定：高置信度收下', () => {
  assert.equal(judgeOcr({ text: '清晰文字', confidence: 0.95, elapsedMs: 1 }), 'accept');
});

test('OCR 判定：中等置信度提示重拍但仍可入库', () => {
  assert.equal(judgeOcr({ text: '有点糊', confidence: 0.4, elapsedMs: 1 }), 'retake');
});

test('OCR 判定：低置信度或报错一律丢弃', () => {
  assert.equal(judgeOcr({ text: '很糊', confidence: 0.1, elapsedMs: 1 }), 'reject');
  assert.equal(judgeOcr({ text: '有字但报错', confidence: 0.9, elapsedMs: 1, error: 'x' }), 'reject');
  assert.equal(judgeOcr({ text: '', confidence: 0.9, elapsedMs: 1 }), 'reject');
});

test('OCR 判定：阈值可配置', () => {
  const loose = { retakeThreshold: 0.3, rejectThreshold: 0.1 };
  assert.equal(judgeOcr({ text: 'x', confidence: 0.35, elapsedMs: 1 }, loose), 'accept');
  assert.equal(judgeOcr({ text: 'x', confidence: 0.35, elapsedMs: 1 }), 'retake');
});

// ---------------------------------------------------------------------------
// 流水线
// ---------------------------------------------------------------------------

test('流水线：纯文本导入直接入库', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const out = await svc.importDocument({ title: '笔记', source: 'note', uri: 'mem://1', text: '离线资料库支持本地检索' });
  assert.equal(out.ok, true);
  assert.equal(out.verdict, 'accept');
  assert.ok(out.chunks > 0);
  assert.equal(svc.docCount(), 1);
});

test('流水线：空内容被拒绝', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const out = await svc.importDocument({ title: '空', source: 'note', uri: 'mem://1', text: '' });
  assert.equal(out.ok, false);
  assert.equal(svc.docCount(), 0);
});

test('流水线：OCR 高置信度入库', async () => {
  const engine = new FakeOcrEngine().preset('img://good', '课堂板书内容是预算调度', 0.92);
  const svc = new LibraryService(engine);
  const out = await svc.importDocument({ title: '板书', source: 'camera', uri: 'img://good' });
  assert.equal(out.ok, true);
  assert.equal(out.verdict, 'accept');
  assert.equal(svc.docCount(), 1);
});

test('流水线：OCR 中等置信度入库但提示重拍', async () => {
  const engine = new FakeOcrEngine().preset('img://blur', '有些模糊的板书', 0.45);
  const svc = new LibraryService(engine);
  const out = await svc.importDocument({ title: '糊', source: 'camera', uri: 'img://blur' });
  assert.equal(out.ok, true);
  assert.equal(out.verdict, 'retake');
  assert.match(out.message, /重拍/);
});

test('流水线：OCR 失败不入库', async () => {
  const engine = new FakeOcrEngine().presetFailure('img://bad');
  const svc = new LibraryService(engine);
  const out = await svc.importDocument({ title: '失败', source: 'camera', uri: 'img://bad' });
  assert.equal(out.ok, false);
  assert.equal(svc.docCount(), 0);
});

test('流水线：设备无 OCR 时给出可操作提示', async () => {
  const svc = new LibraryService(new UnavailableOcrEngine());
  assert.equal(svc.ocrAvailable(), false);
  const out = await svc.importDocument({ title: '拍照', source: 'camera', uri: 'img://1' });
  assert.equal(out.ok, false);
  assert.match(out.message, /粘贴文本/);
  // 但纯文本导入仍然可用 —— 能力降级不等于应用不可用
  const out2 = await svc.importDocument({ title: '笔记', source: 'note', uri: 'mem://1', text: '仍然可用' });
  assert.equal(out2.ok, true);
});

test('流水线：查询返回命中与高亮', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  await svc.importDocument({ title: 'a', source: 'note', uri: 'u1', text: '检索深度应当由得分分布决定' });
  await svc.importDocument({ title: 'b', source: 'note', uri: 'u2', text: '完全不相关的内容在这里' });
  const q = svc.query('检索深度', BUDGET_GENEROUS, OPTS_AUTO);
  assert.ok(q.hits.length >= 1);
  assert.ok(q.hits[0].spans.length > 0);
  assert.equal(q.diagnostics.candidateCount >= q.hits.length, true);
});

test('流水线：资源预算限制时 limitedBy 为 resource', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  for (let i = 0; i < 20; i++) {
    await svc.importDocument({ title: 'd' + i, source: 'note', uri: 'u' + i, text: '检索 ' + i + ' 号资料内容' });
  }
  const tight = { latencyBudgetMs: 1, memoryBudgetKb: 1, batteryPercent: 90 };
  const q = svc.query('检索', tight, { topK: 20, minK: 1, maxK: 20 });
  assert.equal(q.limitedBy, 'resource');
  assert.ok(q.k <= q.budgetK);
});

test('流水线：save/load 往返后仍能检索', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  await svc.importDocument({ title: 'a', source: 'note', uri: 'u1', text: '离线资料库的核心是本地检索' });
  const json = svc.save();

  const svc2 = new LibraryService(new FakeOcrEngine());
  const skipped = svc2.load(json);
  assert.equal(skipped, 0);
  assert.equal(svc2.docCount(), 1);
  // 索引必须被重建，否则检索不到
  const q = svc2.query('本地检索', BUDGET_GENEROUS, OPTS_AUTO);
  assert.ok(q.hits.length >= 1, 'load 之后必须能检索到（索引重建）');
});

test('流水线：删除文档后索引同步更新', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const a = await svc.importDocument({ title: 'a', source: 'note', uri: 'u1', text: '独特词汇甲乙丙' });
  await svc.importDocument({ title: 'b', source: 'note', uri: 'u2', text: '另一份资料' });
  assert.equal(svc.removeDocument(a.docId), true);
  const q = svc.query('甲乙丙', BUDGET_GENEROUS, OPTS_AUTO);
  assert.equal(q.hits.length, 0, '删除后不应再检索到');
});

test('流水线：分块随文档长度自适应', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const short = await svc.importDocument({ title: 's', source: 'note', uri: 'u1', text: '短文' });
  assert.equal(short.chunks, 1, '短文档应只有一块');

  const longText = '长'.repeat(50000);
  const long = await svc.importDocument({ title: 'l', source: 'note', uri: 'u2', text: longText });
  assert.ok(long.chunks > 1, '长文档应切成多块');
});

test('流水线：空库查询不崩溃', () => {
  const svc = new LibraryService(new FakeOcrEngine());
  const q = svc.query('任意', BUDGET_GENEROUS, OPTS_AUTO);
  assert.equal(q.hits.length, 0);
  assert.equal(q.k, 0);
});

test('流水线：平均块长从真实块量出来', async () => {
  const svc = new LibraryService(new FakeOcrEngine());
  assert.equal(svc.averageChunkChars(), 0);
  await svc.importDocument({ title: 'a', source: 'note', uri: 'u1', text: 'a'.repeat(500) });
  const avg = svc.averageChunkChars();
  assert.ok(avg > 0 && avg <= 500);
});
