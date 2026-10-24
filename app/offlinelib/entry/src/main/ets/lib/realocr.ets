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

import { textRecognition } from '@hms.ai.ocr.textRecognition';
import { image } from '@kit.ImageKit';
import { common } from '@kit.AbilityKit';
import { OcrEngine, OcrResult } from './ocr';

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
   * `imageUri` 支持两种形式：
   *   · `rawfile:<文件名>`  —— 应用内置资源（用于自测，不依赖相机）
   *   · 其他                —— 交给上层扩展（相机/相册路径）
   */
  public async recognize(imageUri: string): Promise<OcrResult> {
    const t0: number = Date.now();
    try {
      let buf: ArrayBuffer | undefined = undefined;

      if (imageUri.startsWith('rawfile:')) {
        const name: string = imageUri.substring('rawfile:'.length);
        const content: Uint8Array = await this.ctx.resourceManager.getRawFileContent(name);
        // Uint8Array 的 buffer 可能带偏移，这里拷一份干净的 ArrayBuffer
        const copy: Uint8Array = new Uint8Array(content.length);
        copy.set(content);
        buf = copy.buffer as ArrayBuffer;
      } else {
        // 相机/相册路径尚未接入 —— 明确报错而不是静默失败
        return {
          text: '',
          confidence: 0,
          elapsedMs: Date.now() - t0,
          error: '尚未接入相机/相册图片路径，当前只支持 rawfile: 内置图'
        };
      }

      const src: image.ImageSource = image.createImageSource(buf);
      const pm: image.PixelMap = await src.createPixelMap();
      await src.release();

      const conf: textRecognition.TextRecognitionConfiguration = {
        isDirectionDetectionSupported: false
      };
      const res: textRecognition.TextRecognitionResult = await textRecognition.recognizeText(
        { pixelMap: pm }, conf
      );
      await pm.release();

      const text: string = res.value;

      // Vision Kit 不返回标量置信度，只返回分块。
      // 这里用"块数"做一个保守的代理指标：块越少越可能是极短或识别失败。
      // **不要把这个数当成概率**——它只是给 OcrQualityPolicy 一个有界的输入。
      const blockCount: number = res.blocks !== undefined ? res.blocks.length : 0;
      const confidence: number = text.length === 0 ? 0 : (blockCount >= 3 ? 0.9 : 0.7);

      return { text: text, confidence: confidence, elapsedMs: Date.now() - t0 };
    } catch (e) {
      const msg: string = e instanceof Error ? e.message : '未知错误';
      return {
        text: '',
        confidence: 0,
        elapsedMs: Date.now() - t0,
        error: 'OCR 失败：' + msg
      };
    }
  }
}
