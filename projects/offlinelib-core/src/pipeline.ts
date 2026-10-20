/**
 * 流水线编排 —— 导入 → 分块 → 建索引 → 检索。
 *
 * THIS IS THE PART THE PPT CALLS "本项目的技术含量所在"
 *   开题 PPT 的 P9 写着：
 *     "① 本地索引与检索（切词 / 倒排 / BM25 / 高亮定位）——纯算法，可脱离设备做单元测试
 *      ② 端侧能力编排与调度——本项目的技术含量所在"
 *
 *   ① 在 index.ts / search.ts 里。② 就在这个文件。
 *
 *   编排的核心不是"把函数串起来"，而是**每一步都要做一次带信号的决策**：
 *
 *     感知环节  → 识别置信度 → 收下 / 提示重拍 / 丢弃      （信号：图像质量）
 *     索引环节  → 文档长度   → 分块大小 / 是否延迟建索引    （信号：内容规模）
 *     检索环节  → 得分分布   → 取几条                       （信号：得分断层）
 *     资源环节  → 延迟/内存/电量 → 还能取几条                （信号：资源）
 *
 *   **这四条用的是四个不同的信号。** 若把它们压成一个"剩余预算"，
 *   就退化成了我们实验里那个被每个固定策略严格支配的方案。
 *
 * ⚠️ 纯 TS：不导入任何平台 Kit。OCR 由外部注入（见 ocr.ts）。
 */

import { InvertedIndex, chunkDocument, ChunkOptions, DEFAULT_CHUNK_OPTIONS } from './index';
import { search, decideBudget } from './search';
import { DocStore } from './store';
import { OcrEngine, judgeOcr, OcrVerdict, OcrQualityPolicy, DEFAULT_OCR_POLICY } from './ocr';
import {
  BudgetInput, Hit, SearchOptions, DocItem, DocSource, ScoreDiagnostics
} from './types';

/** 导入一份资料的输入。 */
export interface ImportInput {
  /** 用户可见的标题。 */
  title: string;
  /** 来源。决定是否需要 OCR。 */
  source: DocSource;
  /** 原始文件位置。 */
  uri: string;
  /**
   * 已经有文本时直接给（纯文本资料、或用户手工粘贴的笔记）。
   * 为空则走 OCR。
   */
  text?: string;
}

/** 导入的结果。 */
export interface ImportOutcome {
  /** 是否成功入库。 */
  ok: boolean;
  /** OCR 判定（纯文本导入时恒为 'accept'）。 */
  verdict: OcrVerdict;
  /** 入库后的文档 id（失败时为空串）。 */
  docId: string;
  /** 新建的块数。 */
  chunks: number;
  /** 给用户看的一句话（成功或失败原因）。 */
  message: string;
}

/** 一次查询的结果，含全部决策依据。 */
export interface QueryOutcome {
  hits: Hit[];
  k: number;
  kSource: 'fixed' | 'score-gap';
  diagnostics: ScoreDiagnostics;
  /** 资源预算给出的上限。 */
  budgetK: number;
  /** 资源预算的理由（"受时间预算限制"等）。 */
  budgetReason: string;
  /** 最终 k 是受信息信号还是资源信号限制。 */
  limitedBy: 'information' | 'resource';
}

/**
 * 资料库服务 —— 应用层唯一需要交互的入口。
 *
 * 把 store / index / ocr 三者组合起来，并保证：
 *   - 文档变更后索引与文档库保持一致
 *   - 每次检索都返回**决策依据**（便于界面向用户解释）
 */
export class LibraryService {
  private store: DocStore;
  private index: InvertedIndex;
  private ocr: OcrEngine;
  private chunkOpts: ChunkOptions;
  private ocrPolicy: OcrQualityPolicy;
  private seq: number;

  constructor(
    ocr: OcrEngine,
    chunkOpts: ChunkOptions = DEFAULT_CHUNK_OPTIONS,
    ocrPolicy: OcrQualityPolicy = DEFAULT_OCR_POLICY
  ) {
    this.store = new DocStore();
    this.index = new InvertedIndex();
    this.ocr = ocr;
    this.chunkOpts = chunkOpts;
    this.ocrPolicy = ocrPolicy;
    this.seq = 0;
  }

  /** 文档数。 */
  public docCount(): number {
    return this.store.size();
  }

  /** 索引块数。 */
  public chunkCount(): number {
    return this.index.chunkCount();
  }

  /** OCR 能力是否可用。**界面在提供"拍照导入"入口前必须先问这个。** */
  public ocrAvailable(): boolean {
    return this.ocr.available();
  }

  public ocrName(): string {
    return this.ocr.name();
  }

  /**
   * 导入一份资料。
   *
   * 决策点：OCR 置信度决定"收下 / 提示重拍 / 丢弃"。
   * 这是"感知环节由图像质量驱动"的具体实现。
   */
  public async importDocument(input: ImportInput): Promise<ImportOutcome> {
    let text = input.text !== undefined ? input.text : '';
    let verdict: OcrVerdict = 'accept';

    if (text.length === 0) {
      // 没有现成文本 → 走 OCR
      if (!this.ocr.available()) {
        return {
          ok: false,
          verdict: 'reject',
          docId: '',
          chunks: 0,
          message: '当前设备没有可用的 OCR 能力，请改用「粘贴文本」导入'
        };
      }
      const res = await this.ocr.recognize(input.uri);
      verdict = judgeOcr(res, this.ocrPolicy);
      if (verdict === 'reject') {
        return {
          ok: false,
          verdict: verdict,
          docId: '',
          chunks: 0,
          message: res.error !== undefined ? res.error : '识别质量过低，未入库'
        };
      }
      text = res.text;
    }

    if (text.length === 0) {
      return { ok: false, verdict: 'reject', docId: '', chunks: 0, message: '内容为空' };
    }

    this.seq += 1;
    const docId = 'd' + this.seq.toString();
    const doc: DocItem = {
      id: docId,
      title: input.title,
      source: input.source,
      uri: input.uri,
      addedAt: 0,
      text: text
    };
    this.store.put(doc);

    // 决策点：内容规模决定分块大小
    const opts = this.chunkOptionsFor(text.length);
    const added = this.index.addDocument(doc, opts);

    const base = verdict === 'retake'
      ? '已入库，但识别置信度偏低，建议重拍以获得更好的检索效果'
      : '已入库';
    return {
      ok: true,
      verdict: verdict,
      docId: docId,
      chunks: added,
      message: base + '（' + added.toString() + ' 个片段）'
    };
  }

  /**
   * 由文档长度决定分块参数。
   *
   * 为什么不是固定值：短文档（一页笔记）按 240 字符切会切成一个块，
   * 而长文档（几十页 PDF）按 240 切会产生上千个块、索引膨胀。
   * **内容规模是一个独立信号**——它只影响分块，不该影响检索深度。
   */
  private chunkOptionsFor(textLen: number): ChunkOptions {
    if (textLen <= 1000) {
      return { size: Math.max(120, textLen), overlap: 0 };
    }
    if (textLen <= 20000) {
      return { size: 240, overlap: 40 };
    }
    // 长文档：块更大以减少块数，保留重叠避免切断
    return { size: 400, overlap: 60 };
  }

  /**
   * 查询。
   *
   * **两个信号各管一件事**：
   *   - 得分分布 → 该取几条（信息层面）
   *   - 延迟/内存/电量 → 还取得起吗（资源层面）
   * 最终 k 取两者的较小值，并报告是谁在限制。
   */
  public query(q: string, budget: BudgetInput, options: SearchOptions): QueryOutcome {
    const r = search(this.index, q, options);

    const bd = decideBudget(budget, this.averageChunkChars());

    let k = r.k;
    let limitedBy: 'information' | 'resource' = 'information';
    if (bd.k < r.k) {
      k = bd.k;
      limitedBy = 'resource';
    }
    const hits: Hit[] = r.hits.slice(0, k);

    return {
      hits: hits,
      k: k,
      kSource: r.kSource,
      diagnostics: r.diagnostics,
      budgetK: bd.k,
      budgetReason: bd.reason,
      limitedBy: limitedBy
    };
  }

  /**
   * 实际的块平均字符数。
   *
   * 早先这里写的是拿一个固定参数去推，那是错的——块大小随文档长度变，
   * 必须从**真实块**上量。这条注释留着，是因为"看起来合理的估计"
   * 正是这个项目里反复出错的形态。
   */
  public averageChunkChars(): number {
    const n = this.index.chunkCount();
    if (n === 0) {
      return 0;
    }
    let sum = 0;
    for (let i = 0; i < n; i++) {
      sum += this.index.getChunk(i).text.length;
    }
    return sum / n;
  }

  /** 序列化整个资料库（只存文档，索引在 load 时重建）。 */
  public save(): string {
    return this.store.save();
  }

  /**
   * 恢复资料库并重建索引。
   *
   * 返回被跳过的坏条目数。**rebuildIndex 是必需的**——
   * 存档里只有文档，没有索引（见 store.ts 的设计决定）。
   */
  public load(json: string): number {
    const skipped = this.store.load(json);
    this.seq = this.store.size();
    this.rebuildIndex();
    return skipped;
  }

  /** 从文档库重建索引。返回重建的块数。 */
  public rebuildIndex(): number {
    this.index.clear();
    const docs = this.store.all();
    let n = 0;
    for (let i = 0; i < docs.length; i++) {
      const d = docs[i];
      n += this.index.addDocument(d, this.chunkOptionsFor(d.text.length));
    }
    return n;
  }

  /** 删除一份资料，并把它从索引里剔除（重建索引，简单且不会漏）。 */
  public removeDocument(id: string): boolean {
    const ok = this.store.remove(id);
    if (ok) {
      this.rebuildIndex();
    }
    return ok;
  }

  /** 训练/演示用：列出全部文档。 */
  public documents(): DocItem[] {
    return this.store.all();
  }
}
