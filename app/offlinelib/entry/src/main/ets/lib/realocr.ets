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

      const conf: textRecognition.TextRecognitionConfiguration = {
        isDirectionDetectionSupported: false
      };
      const res: textRecognition.TextRecognitionResult = await textRecognition.recognizeText(
        { pixelMap: pm }, conf
      );
      pm.release();

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
