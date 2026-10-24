/**
 * 真实 OCR 引擎（CoreVisionKit）。
 *
 * ⚠️ 这个文件**静态导入了 HMS 的 CoreVisionKit**。
 *
 *   为什么这是安全的：我们先用 `canIUse('SystemCapability.AI.OCR.TextRecognition')`
 *   在设备上实测过，返回 **true**（截图见 deliverables/演示素材/L3真机验证/）。
 *
 *   为什么仍然要谨慎：早期版本静态导入 `@hms.ai.A2A` 时，因为设备缺少对应 HSP，
 *   应用在**模块加载期**就 abort 了。同一个 deviceType(2in1) 的 AgentKit
 *   探针现在仍返回 false —— 说明这两个 Kit 在这台设备上的可用性并不一样。
 *
 *   所以：**这个文件只应该在 canIUse 为 true 的设备上被加载。**
 *   实际使用中由 pipeline 决定注入 Real 还是 Fake 引擎。
 *
 * 它实现的是 lib/ocr.ts 里的 `OcrEngine` 接口 —— 核心算法层完全不知道
 * 这里是 Vision Kit 还是假引擎，这正是当初把 OCR 做成接口的目的。
 */

import { textRecognition } from '@kit.CoreVisionKit';
import { image } from '@kit.ImageKit';
import { common } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';
import { OcrEngine, OcrResult } from './ocr';

/** 覆盖率估算结果。 */
interface CoverageEstimate {
  /** 识别字数 ÷ 应有字数。引擎没给几何信息时为 0。 */
  coverage: number;
  /** 参与估算的行数。 */
  lineCount: number;
  /** 识别出的（去空白后）字数。 */
  actualChars: number;
  /** 由行几何估算的应有字数。 */
  expectedChars: number;
}

/**
 * 计算图片的锐度（边缘能量的平均值），取值 0-255 量级。
 *
 * WHY THIS EXISTS — 一次失败的尝试和它的教训
 *   我最初的想法是「字符覆盖率」：用 OCR 检测到的行框算出"这一行该有多少字"，
 *   再和实际认出的字数比。**实测证明这个信号完全无效** ——
 *   最差的那张图（召回 28%）覆盖率和正常图一样（1.74 vs 1.72）。
 *
 *   失效原因很根本：expected 是从**检测到的行框**算出来的。
 *   如果 OCR 整行都没检测到，那一行的框也不存在 ——
 *   实际字数和应有字数**一起缩小**，比值自我归一化，对漏认天然免疫。
 *   **检测器的盲区，在它自己的输出里是看不见的。**
 *
 *   所以要判断"这张图是不是糊到不能用"，必须用一个
 *   **完全不依赖 OCR 输出的**参照 —— 也就是直接看像素。
 *
 * 算法：相邻像素灰度差的平均绝对值（水平 + 竖直）。
 *   图像模糊 → 边缘被抹平 → 差值变小。
 *   实现上按 step 抽样，避免对整张图逐像素求和。
 *
 * ⚠️ 它是一个**相对指标**，不是标定的物理量：
 *   同一张图在不同分辨率下取值会变，所以阈值必须按设备/尺寸实测确定，
 *   不能当成通用常数。
 */
async function estimateSharpness(pm: image.PixelMap): Promise<number> {
  try {
    const info: image.ImageInfo = await pm.getImageInfo();
    const w: number = info.size.width;
    const h: number = info.size.height;
    if (w < 8 || h < 8) {
      return 0;
    }
    const buf: ArrayBuffer = new ArrayBuffer(w * h * 4);
    await pm.readPixelsToBuffer(buf);
    const px: Uint8Array = new Uint8Array(buf);

    // 抽样步长：目标约 200×100 个采样点，兼顾速度与代表性
    const stepX: number = Math.max(1, Math.floor(w / 200));
    const stepY: number = Math.max(1, Math.floor(h / 100));

    let sum: number = 0;
    let n: number = 0;
    for (let y = 0; y + stepY < h; y += stepY) {
      for (let x = 0; x + stepX < w; x += stepX) {
        const i0: number = (y * w + x) * 4;
        const i1: number = (y * w + (x + stepX)) * 4;
        const i2: number = ((y + stepY) * w + x) * 4;
        // 灰度近似：直接用 G 通道，省两次加法
        const g0: number = px[i0 + 1];
        const gx: number = Math.abs(g0 - px[i1 + 1]);
        const gy: number = Math.abs(g0 - px[i2 + 1]);
        sum += gx + gy;
        n += 2;
      }
    }
    return n > 0 ? sum / n : 0;
  } catch (e) {
    return 0;
  }
}

/** 把行检测结果换算成宽高。 */
function lineBox(line: textRecognition.TextLine): number[] {
  // 返回 [w, h]；几何信息缺失时返回 [0, 0]
  const pts: textRecognition.PixelPoint[] = line.cornerPoints;
  if (pts === undefined || pts.length < 4) {
    return [0, 0];
  }
  let minX: number = pts[0].x;
  let maxX: number = pts[0].x;
  let minY: number = pts[0].y;
  let maxY: number = pts[0].y;
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].x < minX) { minX = pts[i].x; }
    if (pts[i].x > maxX) { maxX = pts[i].x; }
    if (pts[i].y < minY) { minY = pts[i].y; }
    if (pts[i].y > maxY) { maxY = pts[i].y; }
  }
  return [maxX - minX, maxY - minY];
}

/** 去掉空白后的字数。与 OcrQuality 里的归一化口径保持一致。 */
function countNonSpace(s: string): number {
  let n: number = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charAt(i);
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r' || c === '\u3000') {
      continue;
    }
    n += 1;
  }
  return n;
}

/**
 * 估算字符覆盖率。
 *
 * 原理：中日韩字形近似正方形，所以「N 个字的一行」的宽度约为 N 倍行高。
 *   应有字数 ≈ 行宽 ÷ 行高
 *   覆盖率 = 实际字数 ÷ 应有字数
 *
 * 为什么要按行算而不是按整图算：
 *   字号会在同一张图里变化（标题大、正文小），按整图算会把差异抹平。
 *   按行算，每行都用**自己的行高**做尺度，天然对字号不变。
 */
function estimateCoverage(res: textRecognition.TextRecognitionResult): CoverageEstimate {
  let actual: number = 0;
  let expected: number = 0;
  let lines: number = 0;

  const blocks: textRecognition.TextBlock[] = res.blocks;
  if (blocks !== undefined) {
    for (let i = 0; i < blocks.length; i++) {
      const ls: textRecognition.TextLine[] = blocks[i].lines;
      if (ls === undefined) {
        continue;
      }
      for (let j = 0; j < ls.length; j++) {
        const box = lineBox(ls[j]);
        const w = box[0];
        const h = box[1];
        actual += countNonSpace(ls[j].value ?? '');
        lines += 1;
        if (h > 0) {
          expected += w / h;
        }
      }
    }
  }

  const cov: CoverageEstimate = {
    coverage: expected > 0 ? actual / expected : 0,
    lineCount: lines,
    actualChars: actual,
    expectedChars: expected
  };
  return cov;
}

/**
 * 由图片锐度定置信度。
 *
 * 阈值不是拍的，是从 12 张已知答案的测试图实测出来的：
 *
 *   图             召回     锐度
 *   清晰           100%    11.6
 *   旋转 15°       100%    12.9
 *   噪声           100%    27.9
 *   旋转 6.5°      100%    12.6
 *   行楷            98%    10.1
 *   楷体           100%     7.5
 *   高斯模糊       100%     5.4
 *   低对比         100%     2.7
 *   小字号         100%     2.5
 *   强模糊          93%     2.4
 *   极低对比       100%     1.6
 *   ─────────────────────────────
 *   小字+模糊       28%     1.3   ← 唯一真正失败的
 *
 * **所有识别成功的都在 1.5 以上，唯一失败的在 1.3。** 所以阈值取 1.5。
 *
 * ⚠️ 必须说清楚的三个局限：
 *   1. **分隔带很窄**（1.3 vs 1.6），而样本只有 12 张合成图。
 *      这个阈值很像过拟合，换一批图很可能要重定。
 *   2. 锐度衡量的是**图片质量**，不是**识别质量**。
 *      低对比（2.7）和极低对比（1.6）看起来"糊"，但 Vision Kit 照样认出 100% ——
 *      说明 OCR 比"图片看起来清楚"要稳健得多。
 *   3. 因此**低锐度只应提示用户核对，不应自动丢弃**。
 *      界面上我们本来就不自动入库，识别结果只是填进输入框由用户确认，
 *      这个设计比任何自动判据都可靠。
 *
 * 返回值是**分档**，不是概率。
 */
function confidenceFromSharpness(sharpness: number, textLen: number): number {
  if (textLen === 0) {
    return 0;
  }
  if (sharpness <= 0) {
    // 读不到像素，无法判断 —— 给中性值，不假装有信心
    return 0.5;
  }
  if (sharpness >= 1.5) {
    return 0.9;
  }
  // 低于 1.5：实测里唯一失败的那一档。提示核对，而不是直接判死。
  return 0.3;
}

export class RealOcrEngine implements OcrEngine {
  private ctx: common.UIAbilityContext;

  constructor(ctx: common.UIAbilityContext) {
    this.ctx = ctx;
  }

  public name(): string {
    return 'vision-kit-ocr';
  }

  /**
   * 能力是否可用。
   *
   * 用 `canIUse` 而不是"试着调一下"：前者不会产生副作用，也不会因为失败而拖慢启动。
   */
  public available(): boolean {
    return canIUse('SystemCapability.AI.OCR.TextRecognition');
  }

  /**
   * 识别一张图。
   *
   * 支持三种来源：
   *   · `rawfile:<文件名>`  —— 应用内置资源（自测用，不依赖用户数据）
   *   · `file://...`        —— 系统选择器返回的文件 URI（相册/文件）
   *   · 其他                —— 明确报错，不静默失败
   *
   * ⚠️ 关于"为什么不直接调相机"
   *   调相机需要 `ohos.permission.CAMERA`，而本软件的核心主张之一是
   *   **不申请任何系统权限**（这也是"数据不出设备"在权限层面的证据）。
   *
   *   系统相册选择器（PhotoViewPicker）**不需要申请权限**：
   *   由系统界面让用户挑选，应用只拿到那一张图的 URI。
   *   所以"导入图片做识别"可以做到零权限，"调相机拍照"不行。
   *   取舍是明确的：宁可少一个入口，也不放弃零权限。
   */
  public async recognize(imageUri: string): Promise<OcrResult> {
    const t0: number = Date.now();
    let file: fileIo.File | undefined = undefined;
    try {
      let src: image.ImageSource | undefined = undefined;

      if (imageUri.startsWith('rawfile:')) {
        const name: string = imageUri.substring('rawfile:'.length);
        const content: Uint8Array = await this.ctx.resourceManager.getRawFileContent(name);
        // Uint8Array 的 buffer 可能带偏移，这里拷一份干净的 ArrayBuffer
        const copy: Uint8Array = new Uint8Array(content.length);
        copy.set(content);
        src = image.createImageSource(copy.buffer as ArrayBuffer);
      } else if (imageUri.startsWith('file://') || imageUri.startsWith('datashare://')) {
        // 选择器返回的 URI：拿到 fd 再交给解码器，不必把整个文件读进内存
        file = fileIo.openSync(imageUri, fileIo.OpenMode.READ_ONLY);
        src = image.createImageSource(file.fd);
      } else {
        return {
          text: '',
          confidence: 0,
          elapsedMs: Date.now() - t0,
          error: '不支持的图片来源：' + imageUri
        };
      }

      const pm: image.PixelMap = await src.createPixelMap();
      src.release();

      // 锐度必须在 OCR **之前**算：它是独立于识别结果的参照。
      const sharp: number = await estimateSharpness(pm);

      const conf: textRecognition.TextRecognitionConfiguration = {
        isDirectionDetectionSupported: false
      };
      const res: textRecognition.TextRecognitionResult = await textRecognition.recognizeText(
        { pixelMap: pm }, conf
      );
      pm.release();

      const text: string = res.value;
      const cov = estimateCoverage(res);
      const confidence: number = confidenceFromSharpness(sharp, text.length);

      return {
        text: text,
        confidence: confidence,
        elapsedMs: Date.now() - t0,
        coverage: cov.coverage,
        lineCount: cov.lineCount,
        sharpness: sharp
      };
    } catch (e) {
      const msg: string = e instanceof Error ? e.message : '未知错误';
      return {
        text: '',
        confidence: 0,
        elapsedMs: Date.now() - t0,
        error: 'OCR 失败：' + msg
      };
    } finally {
      // 无论成功失败都要关文件描述符，否则反复识别会耗光 fd
      if (file !== undefined) {
        try {
          fileIo.closeSync(file);
        } catch (e) {
          // 关闭失败不改变识别结果，忽略
        }
      }
    }
  }
}
