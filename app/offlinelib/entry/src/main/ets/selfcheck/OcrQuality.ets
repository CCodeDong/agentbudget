/**
 * OCR 质量测试 —— 用已知答案的合成图集量化识别退化。
 *
 * WHY THIS IS A MEASUREMENT AND NOT AN IMPRESSION
 *   "模糊一点还能认出来"不是结论，是感觉。
 *   这些测试图的**正确答案是已知的**（生成时写死的），
 *   所以可以算字符级召回率与精确率，把"退化多少"变成数字。
 *
 * METRIC
 *   把原文与识别结果都去掉空白后，用**最长公共子序列**比对：
 *     召回率 = LCS 长度 / 原文字数   （原文认出来多少）
 *     精确率 = LCS 长度 / 识别字数   （认出来的有多少是对的）
 *     F1     = 2PR / (P + R)
 *
 *   为什么用 LCS 而不是编辑距离：
 *     编辑距离要求对齐到具体位置，跨行/换行顺序变化会重罚；
 *     而 OCR 输出的换行位置经常和原文不同，那不是识别错误。
 *     LCS 只问"这些字有没有被认出来"，更贴近我们想测的东西。
 *
 * ⚠️ 局限（必须写在结论里）
 *   合成图没有反光、透视畸变、纸张纹理、手指遮挡。
 *   它测的是「同一段文字在不同退化条件下的识别率」，
 *   不是「在真实照片上的识别率」。
 */

import { OcrEngine, OcrResult } from '../lib/ocr';

/** 基准文字。必须与 tools/gen_ocr_test_images.py 的 GROUND_TRUTH 完全一致。 */
export const GROUND_TRUTH: string =
  '上下文窗口只有四千到八千' +
  '多智能体消耗约为十五倍' +
  '因此取舍是强制的' +
  'BM25 排序 k1=1.5';

/** 一张测试图。 */
export interface QualityCase {
  /** rawfile 文件名。 */
  file: string;
  /** 界面上显示的退化描述。 */
  label: string;
}

/** 一行测试结果。 */
export interface QualityRow {
  label: string;
  /** 识别出的字数（去空白后）。 */
  chars: number;
  /** 召回率百分比。 */
  recall: number;
  /** 精确率百分比。 */
  precision: number;
  /** F1 百分比。 */
  f1: number;
  /** 耗时毫秒。 */
  ms: number;
  /** 出错时的信息。 */
  error: string;
}

/** 测试图清单。
 *
 * 分两档，理由是**第一档找不到断点**：
 *   第一档 7 张（清晰 → 行楷）除行楷外全部 100%，
 *   这不能说明"真实照片也没问题"，只说明"这些图对 Vision Kit 太简单"。
 *   所以要再压一档，看它从哪里开始掉。
 */
export const QUALITY_CASES: QualityCase[] = [
  // 第一档：常见退化
  { file: 'q1_clean.png', label: '清晰（基准）' },
  { file: 'q2_blur.png', label: '高斯模糊' },
  { file: 'q3_lowcontrast.png', label: '低对比' },
  { file: 'q4_rotated.png', label: '旋转 6.5°' },
  { file: 'q5_small.png', label: '小字号' },
  { file: 'q6_kaiti.png', label: '楷体' },
  { file: 'q7_xingkai.png', label: '行楷（近手写）' },
  // 第二档：刻意加压，找断点
  { file: 'q8_blur_strong.png', label: '强模糊' },
  { file: 'q9_contrast_extreme.png', label: '极低对比' },
  { file: 'q10_rotated15.png', label: '旋转 15°' },
  { file: 'q11_noisy.png', label: '噪声' },
  { file: 'q12_small_blur.png', label: '小字+模糊' }
];

/**
 * 归一化：去掉所有空白，拉丁字母转小写。
 *
 * 去掉空白是必要的：OCR 输出的换行位置经常和原文不同，
 * 把换行差异算成错误会低估识别质量。
 * 拉丁转小写是因为我们只关心"字认没认出来"，不关心大小写风格。
 */
export function normalizeForCompare(s: string): string {
  let out = '';
  for (let i = 0; i < s.length; i++) {
    const c = s.charAt(i);
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r' || c === '\u3000') {
      continue;
    }
    out += c.toLowerCase();
  }
  return out;
}

/**
 * 最长公共子序列长度。
 *
 * 用滚动数组：只需要两行，内存 O(min(n,m))。
 * 我们的字符串只有几十个字符，性能不是问题，但不该写得浪费。
 */
export function lcsLength(a: string, b: string): number {
  const n = a.length;
  const m = b.length;
  if (n === 0 || m === 0) {
    return 0;
  }
  // 让较短的作为列，减少一行数组的长度
  const short = n <= m ? a : b;
  const long = n <= m ? b : a;
  const cols = short.length;

  let prev: number[] = [];
  let cur: number[] = [];
  for (let j = 0; j <= cols; j++) {
    prev.push(0);
    cur.push(0);
  }

  for (let i = 1; i <= long.length; i++) {
    cur[0] = 0;
    const lc = long.charAt(i - 1);
    for (let j = 1; j <= cols; j++) {
      if (lc === short.charAt(j - 1)) {
        cur[j] = prev[j - 1] + 1;
      } else {
        cur[j] = cur[j - 1] > prev[j] ? cur[j - 1] : prev[j];
      }
    }
    const tmp = prev;
    prev = cur;
    cur = tmp;
  }
  return prev[cols];
}

/** 一条结果的质量三元组。 */
export interface QualityScore {
  recall: number;
  precision: number;
  f1: number;
  chars: number;
}

/** 计算召回/精确/F1（都是 0-100 的百分比）。 */
export function scoreAgainstTruth(truth: string, recognized: string): QualityScore {
  const t = normalizeForCompare(truth);
  const r = normalizeForCompare(recognized);
  if (t.length === 0 || r.length === 0) {
    return { recall: 0, precision: 0, f1: 0, chars: r.length };
  }
  const l = lcsLength(t, r);
  const recall = (l / t.length) * 100;
  const precision = (l / r.length) * 100;
  const denom = recall + precision;
  const f1 = denom === 0 ? 0 : (2 * recall * precision) / denom;
  return { recall: recall, precision: precision, f1: f1, chars: r.length };
}

/**
 * 跑整套质量测试。
 *
 * 逐张串行而不是并发：并发会让 OCR 引擎争抢资源，
 * 测出来的耗时不可比。这个测试的目的之一就是看耗时随质量的变化。
 */
export async function runQualityTest(engine: OcrEngine): Promise<QualityRow[]> {
  const rows: QualityRow[] = [];
  for (let i = 0; i < QUALITY_CASES.length; i++) {
    const c = QUALITY_CASES[i];
    let r: OcrResult;
    try {
      r = await engine.recognize('rawfile:' + c.file);
    } catch (e) {
      const row: QualityRow = {
        label: c.label, chars: 0, recall: 0, precision: 0, f1: 0, ms: 0,
        error: '调用异常'
      };
      rows.push(row);
      continue;
    }
    if (r.error !== undefined) {
      const row: QualityRow = {
        label: c.label, chars: 0, recall: 0, precision: 0, f1: 0, ms: r.elapsedMs,
        error: r.error
      };
      rows.push(row);
      continue;
    }
    const s = scoreAgainstTruth(GROUND_TRUTH, r.text);
    const row: QualityRow = {
      label: c.label,
      chars: s.chars,
      recall: s.recall,
      precision: s.precision,
      f1: s.f1,
      ms: r.elapsedMs,
      error: ''
    };
    rows.push(row);
  }
  return rows;
}
