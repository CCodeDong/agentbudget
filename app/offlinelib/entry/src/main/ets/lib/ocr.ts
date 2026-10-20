/**
 * OCR 抽象层。
 *
 * WHY AN INTERFACE INSTEAD OF CALLING THE KIT DIRECTLY
 *   这是整个工程最重要的一条架构决定。
 *
 *   我们实测过一个真实的崩溃：应用静态 `import` 了 HMS 的 A2A Kit，
 *   而设备上没有对应的 HSP 时，ArkTS 运行时会在**模块加载期**直接
 *   `abort` 整个进程 —— 不是"功能不可用"，是"应用起不来"。
 *   （崩溃日志：`load hsp failed, hsp name: com.huawei.hmsapp.hiai.hsp/agentKitHsp`）
 *
 *   所以 OCR 在这里是一个**接口**，而不是一个 import。
 *   真正的实现（调用 Vision Kit）由上层注入，并且**必须在使用前先探测能力是否存在**。
 *   这样：
 *     1. 本模块可以在 Node 里被单测，不需要设备
 *     2. 设备上没有 OCR 时，应用仍然能启动（只是这个能力降级）
 *
 * ⚠️ 本文件不导入任何 HarmonyOS Kit。这是刻意的。
 */

/** 一次 OCR 的结果。 */
export interface OcrResult {
  /** 识别出的纯文本。失败时为空串。 */
  text: string;
  /** 平均置信度 0-1。0 表示完全不可信或识别失败。 */
  confidence: number;
  /** 用时（毫秒），用于预算决策。 */
  elapsedMs: number;
  /** 失败原因；成功时为 undefined。 */
  error?: string;
}

/** OCR 引擎。真实实现由 ArkTS 侧提供。 */
export interface OcrEngine {
  /** 引擎名，用于界面显示与排错。 */
  name(): string;
  /** 这个引擎在当前设备上是否可用。**调用方必须先问这个，再决定用不用。** */
  available(): boolean;
  /** 识别一张图片。 */
  recognize(imageUri: string): Promise<OcrResult>;
}

/**
 * 假 OCR 引擎 —— 用预设文本代替真实识别。
 *
 * 用途有三个，都不是"应付测试"：
 *   1. **让检索流水线在没有设备的机器上可端到端跑通**（老师要的"可核实"）
 *   2. 在设备 OCR 不可用时作为**降级占位**，让其余功能仍可演示
 *   3. 造可控的"识别质量差"场景，用来测调度模块的降级逻辑
 */
export class FakeOcrEngine implements OcrEngine {
  private table: Map<string, OcrResult>;
  private defaultText: string;
  private failUris: Set<string>;

  /**
   * @param defaultText 没有预设时返回的文本
   */
  constructor(defaultText: string = '') {
    this.table = new Map<string, OcrResult>();
    this.defaultText = defaultText;
    this.failUris = new Set<string>();
  }

  public name(): string {
    return 'fake-ocr';
  }

  public available(): boolean {
    return true;
  }

  /** 预设某个 URI 的识别结果。 */
  public preset(uri: string, text: string, confidence: number): FakeOcrEngine {
    this.table.set(uri, { text: text, confidence: confidence, elapsedMs: 10 });
    return this;
  }

  /** 预设某个 URI 识别失败。 */
  public presetFailure(uri: string): FakeOcrEngine {
    this.failUris.add(uri);
    return this;
  }

  public recognize(imageUri: string): Promise<OcrResult> {
    if (this.failUris.has(imageUri)) {
      return Promise.resolve({
        text: '',
        confidence: 0,
        elapsedMs: 5,
        error: 'fake: 预设的识别失败'
      });
    }
    const hit = this.table.get(imageUri);
    if (hit !== undefined) {
      return Promise.resolve(hit);
    }
    return Promise.resolve({
      text: this.defaultText,
      confidence: this.defaultText.length > 0 ? 0.5 : 0,
      elapsedMs: 5,
      error: this.defaultText.length > 0 ? undefined : 'fake: 无预设文本'
    });
  }
}

/**
 * 一个永远不可用的引擎 —— 用于模拟"设备没有 OCR 能力"。
 *
 * 它的存在是为了让"能力缺失时应用仍能启动"这条设计**可被测试**，
 * 而不是只在文档里承诺。
 */
export class UnavailableOcrEngine implements OcrEngine {
  private why: string;

  constructor(why: string = '设备不具备 OCR 能力') {
    this.why = why;
  }

  public name(): string {
    return 'unavailable-ocr';
  }

  public available(): boolean {
    return false;
  }

  public recognize(_imageUri: string): Promise<OcrResult> {
    return Promise.resolve({
      text: '',
      confidence: 0,
      elapsedMs: 0,
      error: this.why
    });
  }
}

/**
 * 根据识别置信度决定"要不要提示用户重拍"。
 *
 * 这是三个信号里的**感知环节信号**：图像质量 → 是否重拍。
 * 对应研究主张里"感知（OCR）应当由图像质量驱动"这一条。
 */
export interface OcrQualityPolicy {
  /** 低于这个置信度就提示重拍。 */
  retakeThreshold: number;
  /** 低于这个置信度就认为识别失败，不应入库。 */
  rejectThreshold: number;
}

export const DEFAULT_OCR_POLICY: OcrQualityPolicy = {
  retakeThreshold: 0.6,
  rejectThreshold: 0.2
};

export type OcrVerdict = 'accept' | 'retake' | 'reject';

/** 掉一个 OCR 结果该不该收、该不该提示重拍。 */
export function judgeOcr(result: OcrResult, policy: OcrQualityPolicy = DEFAULT_OCR_POLICY): OcrVerdict {
  if (result.error !== undefined || result.text.length === 0) {
    return 'reject';
  }
  if (result.confidence < policy.rejectThreshold) {
    return 'reject';
  }
  if (result.confidence < policy.retakeThreshold) {
    return 'retake';
  }
  return 'accept';
}
