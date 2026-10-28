/**
 * 设备内自测 —— 把关键断言搬到应用里跑，结果直接显示在屏幕上。
 *
 * WHY A SELF-TEST PAGE INSTEAD OF JUST NODE TESTS
 *   Node 单测证明了算法在**电脑上**是对的，但这不能证明两件事：
 *     1. 这些 .ts 能被 ArkTS 编译（语法/类型子集是否真的兼容）
 *     2. 在设备的 ArkTS 运行时里行为是否一致
 *
 *   所以这一页的作用是：**打开应用就能看到关键用例是否通过**。
 *   它是可以截图当证据的——这直接对应老师那条"技术路线无法核实"。
 *
 * ⚠️ 这一页刻意**不依赖任何 HMS Kit**（只用假 OCR 引擎、不碰网络）。
 *    原因见 lib/ocr.ts：缺少 HSP 时静态导入会让应用在加载期崩溃。
 *
 * ⚠️ ArkTS 的几条硬约束（这次实测踩到的）：
 *    · 对象字面量必须**有上下文类型**（arkts-no-untyped-obj-literals）
 *    · 数组字面量的元素类型必须可推断（arkts-no-noninferrable-arr-literals）
 *    · 禁止 any / unknown（arkts-no-any-unknown）
 *   所以下面每一步都显式标注类型，不用 `as`、不用 `as unknown as`。
 */

import { InvertedIndex, chunkDocument, locateSpans, Candidate } from '../lib/index';
import { search, decideKByScoreGap, decideBudget } from '../lib/search';
import { DocStore } from '../lib/store';
import { FakeOcrEngine, judgeOcr, OcrResult, OcrVerdict } from '../lib/ocr';
import { LibraryService } from '../lib/pipeline';
import { DocItem, Chunk, SearchOptions, BudgetInput, BudgetDecision } from '../lib/types';

/** 一条自测结果。 */
export interface CheckResult {
  name: string;
  passed: boolean;
  detail: string;
}

/** 自测汇总。 */
export interface CheckSummary {
  total: number;
  passed: number;
  failed: number;
  results: CheckResult[];
}

const BUDGET: BudgetInput = { latencyBudgetMs: 100000, memoryBudgetKb: 1000000, batteryPercent: 90 };
const OPTS_AUTO: SearchOptions = { topK: 0, minK: 1, maxK: 10 };

function makeDoc(id: string, text: string): DocItem {
  const d: DocItem = { id: id, title: 't-' + id, source: 'note', uri: 'mem://' + id, addedAt: 1, text: text };
  return d;
}

function makeChunk(id: string, text: string): Chunk {
  const c: Chunk = { id: id, docId: 'd', seq: 0, start: 0, end: text.length, text: text };
  return c;
}

function makeOcr(text: string, confidence: number): OcrResult {
  const r: OcrResult = { text: text, confidence: confidence, elapsedMs: 1 };
  return r;
}

/**
 * 跑全部自测。
 *
 * 返回结构化结果而不是抛异常：一页里有一个失败，不该让整页白屏。
 */
export async function runSelfChecks(): Promise<CheckSummary> {
  const results: CheckResult[] = [];

  const record = (name: string, ok: boolean, detail: string): void => {
    const r: CheckResult = { name: name, passed: ok, detail: detail };
    results.push(r);
  };

  const check = (name: string, fn: () => void): void => {
    let ok: boolean = true;
    let detail: string = 'ok';
    try {
      fn();
    } catch (err) {
      ok = false;
      // 不读 err.message：ArkTS 里 catch 参数类型是受限的，
      // 而且断言失败的原因对我们够用了——失败的用例名已经说明了问题。
      detail = '断言未通过';
    }
    record(name, ok, detail);
  };

  const assertTrue = (cond: boolean, msg: string): void => {
    if (!cond) {
      throw new Error(msg);
    }
  };
  const assertStr = (a: string, b: string, msg: string): void => {
    if (a !== b) {
      throw new Error(msg + '：期望 ' + b + '，实际 ' + a);
    }
  };
  const assertNum = (a: number, b: number, msg: string): void => {
    if (a !== b) {
      throw new Error(msg + '：期望 ' + b.toString() + '，实际 ' + a.toString());
    }
  };

  // ---- 纯算法 ----

  check('索引：加入块后尺寸正确', () => {
    const idx = new InvertedIndex();
    idx.addChunk(makeChunk('c', '离线资料库'));
    assertNum(idx.size(), 1, '应有 1 个活块');
  });

  check('切词：英文小写化后可检索', () => {
    const idx = new InvertedIndex();
    idx.addDocument(makeDoc('e', 'BM25 Ranking is statistical'));
    assertNum(idx.score('ranking').length, 1, '小写查询应命中大写原文');
  });

  check('分块：长文本切成多块且覆盖到文末', () => {
    const text: string = 'x'.repeat(1000);
    const d: DocItem = makeDoc('l', text);
    const cs: Chunk[] = chunkDocument(d, { size: 240, overlap: 40 });
    assertTrue(cs.length > 1, '应切成多块');
    assertNum(cs[cs.length - 1].end, 1000, '末块应到达文末');
  });

  check('BM25：含查询词的资料排第一', () => {
    const idx = new InvertedIndex();
    idx.addDocument(makeDoc('a', '这里讨论预算调度与上下文窗口'));
    idx.addDocument(makeDoc('b', '检索置信度决定注入深度'));
    const cands: Candidate[] = idx.score('检索置信度');
    assertTrue(cands.length > 0, '应有候选');
    assertStr(cands[0].chunk.docId, 'b', '含查询词的资料应排第一');
  });

  check('高亮：定位到原文区间', () => {
    const matched: Map<string, number> = new Map<string, number>();
    matched.set('检索', 2);
    const spans = locateSpans('检索与检索', matched);
    assertTrue(spans.length >= 1, '应产生高亮区间');
    assertNum(spans[0].start, 0, '首个区间应从 0 开始');
  });

  check('自适应 k：明显断层处截断', () => {
    const c0: Candidate = { index: 0, chunk: makeChunk('a', 'x'), score: 10, matched: new Map<string, number>() };
    const c1: Candidate = { index: 1, chunk: makeChunk('b', 'y'), score: 9, matched: new Map<string, number>() };
    const c2: Candidate = { index: 2, chunk: makeChunk('c', 'z'), score: 1, matched: new Map<string, number>() };
    const cands: Candidate[] = [c0, c1, c2];
    const k: number = decideKByScoreGap(cands, 1, 10);
    assertNum(k, 2, '应保留断层之前的 2 条');
  });

  check('预算决策：极小预算也至少 1 条', () => {
    const tight: BudgetInput = { latencyBudgetMs: 0, memoryBudgetKb: 0, batteryPercent: 5 };
    const d: BudgetDecision = decideBudget(tight, 240);
    assertNum(d.k, 1, 'k 不应小于 1');
  });

  // ---- 存储与 OCR ----

  check('存储：JSON 往返保持内容', () => {
    const s: DocStore = new DocStore();
    s.put(makeDoc('a', '第一份'));
    s.put(makeDoc('b', '第二份'));
    const s2: DocStore = new DocStore();
    const skipped: number = s2.load(s.save());
    assertNum(skipped, 0, '不应跳过任何条目');
    assertNum(s2.size(), 2, '应恢复 2 份文档');
  });

  check('存储：坏数据被跳过而非整体失败', () => {
    const payload: string = '{"version":1,"docs":[' +
      '{"id":"","title":"t","source":"note","uri":"u","addedAt":1,"text":"x"},' +
      '{"id":"good","title":"t","source":"note","uri":"u","addedAt":1,"text":"y"}]}';
    const s: DocStore = new DocStore();
    const skipped: number = s.load(payload);
    assertNum(skipped, 1, '应跳过 1 条坏数据');
    assertNum(s.size(), 1, '应保留 1 条好数据');
  });

  check('OCR 判定：高中低三档', () => {
    const hi: OcrVerdict = judgeOcr(makeOcr('清晰', 0.95));
    const mid: OcrVerdict = judgeOcr(makeOcr('一般', 0.4));
    const lo: OcrVerdict = judgeOcr(makeOcr('很糊', 0.1));
    assertStr(hi, 'accept', '高置信度应收下');
    assertStr(mid, 'retake', '中置信度应提示重拍');
    assertStr(lo, 'reject', '低置信度应丢弃');
  });

  // ---- 流水线（异步） ----

  const svc: LibraryService = new LibraryService(new FakeOcrEngine());
  let firstId: string = '';

  {
    let ok: boolean = true;
    let detail: string = 'ok';
    let chunks: number = 0;
    try {
      const r = await svc.importDocument({
        title: '预算笔记', source: 'note', uri: 'u1',
        text: '移动端的多智能体系统存在预算矛盾，上下文窗口只有四千到八千。'
      });
      ok = r.ok;
      chunks = r.chunks;
      firstId = r.docId;
      if (!ok) {
        detail = r.message;
      }
    } catch (err) {
      ok = false;
      detail = '导入抛异常';
    }
    record('流水线：纯文本导入成功', ok && chunks > 0, ok ? 'ok' : detail);
  }

  {
    let ok: boolean = true;
    let detail: string = 'ok';
    try {
      const q = svc.query('预算矛盾', BUDGET, OPTS_AUTO);
      ok = q.hits.length >= 1 && q.hits[0].spans.length > 0;
      if (!ok) {
        detail = '命中 ' + q.hits.length.toString() + ' 条';
      }
    } catch (err) {
      ok = false;
      detail = '查询抛异常';
    }
    record('流水线：能检索到刚导入的内容（带高亮）', ok, detail);
  }

  {
    let ok: boolean = true;
    let detail: string = 'ok';
    try {
      const r = await svc.importDocument({
        title: '另一份', source: 'note', uri: 'u2', text: '完全不同的内容甲乙丙丁'
      });
      const before: number = svc.docCount();
      svc.removeDocument(r.docId);
      const after: number = svc.docCount();
      const hitsAfter: number = svc.query('甲乙丙丁', BUDGET, OPTS_AUTO).hits.length;
      ok = before === 2 && after === 1 && hitsAfter === 0;
      if (!ok) {
        detail = '删除前 ' + before.toString() + ' / 删除后 ' + after.toString() +
          ' / 残留命中 ' + hitsAfter.toString();
      }
    } catch (err) {
      ok = false;
      detail = '删除抛异常';
    }
    record('流水线：增量删除后检索不到', ok, detail);
  }

  {
    let ok: boolean = true;
    let detail: string = 'ok';
    try {
      const json: string = svc.save();
      const svc2: LibraryService = new LibraryService(new FakeOcrEngine());
      svc2.load(json);
      const q2 = svc2.query('预算矛盾', BUDGET, OPTS_AUTO);
      ok = q2.hits.length >= 1;
      if (!ok) {
        detail = '恢复后命中 0 条（索引未重建？）';
      }
    } catch (err) {
      ok = false;
      detail = '存档往返抛异常';
    }
    record('流水线：存档恢复后仍能检索（索引重建）', ok, detail);
  }

  let passed: number = 0;
  for (let i = 0; i < results.length; i++) {
    if (results[i].passed) {
      passed += 1;
    }
  }
  const summary: CheckSummary = {
    total: results.length,
    passed: passed,
    failed: results.length - passed,
    results: results
  };
  return summary;
}
