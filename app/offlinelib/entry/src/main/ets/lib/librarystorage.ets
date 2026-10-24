/**
 * 资料库的本地持久化。
 *
 * WHY THIS FILE EXISTS — 一个我自己造成的问题
 *   核心库里早就有 `DocStore.save()/load()`，自测里也在用，
 *   但**页面从来没调用过它们**。后果是：
 *
 *     应用一关，资料全没了；下次打开因为库是空的，
 *     `seedDemo()` 又会塞回那份示例 —— 看起来像"正常"，其实是每次都在重新开始。
 *
 *   一个"资料库"关掉就忘事，不是小瑕疵，是功能不成立。
 *   所以这一步补上：存档、启动时读回、任何改动后立即落盘。
 *
 * WHY SAVE ON EVERY CHANGE INSTEAD OF ON EXIT
 *   HarmonyOS 的 UIAbility 在后台可能被系统直接回收，`onDestroy` 不保证被调用。
 *   "退出时保存"在这种模型下是不可靠的。
 *   改动本来就很少（导入/删除），每次落盘的开销可以忽略。
 *
 * WHY NOT STORE THE INDEX
 *   只存原始文档，索引在启动时重建（见 core 的 README）。
 *   索引格式一改旧档就废；重建在常见规模下是毫秒级。
 */

import { fileIo } from '@kit.CoreFileKit';
import { common } from '@kit.AbilityKit';

/** 存档文件名。放在应用沙箱的 files 目录，卸载即清除。 */
const FILE_NAME = 'library.json';

/** 存档文件的绝对路径。 */
export function libraryPath(ctx: common.UIAbilityContext): string {
  return ctx.filesDir + '/' + FILE_NAME;
}

/** 把一段文本写进沙箱。返回是否成功。 */
export function writeText(ctx: common.UIAbilityContext, name: string, text: string): boolean {
  let f: fileIo.File | undefined = undefined;
  try {
    const p = ctx.filesDir + '/' + name;
    // 先删再建：避免旧内容比新内容长时尾部残留
    try {
      fileIo.unlinkSync(p);
    } catch (e) {
      // 文件不存在是正常的，忽略
    }
    f = fileIo.openSync(p, fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE);
    fileIo.writeSync(f.fd, text);
    return true;
  } catch (e) {
    return false;
  } finally {
    if (f !== undefined) {
      try {
        fileIo.closeSync(f);
      } catch (e) {
        // 关不掉不影响写入结果
      }
    }
  }
}

/**
 * 从沙箱读一段文本。
 *
 * 返回空串表示"还没有存档"（首次启动），调用方据此决定要不要放示例资料。
 * **不要把"读不到"和"读到了但是空的"混为一谈** —— 前者该放示例，后者不该。
 */
export function readText(ctx: common.UIAbilityContext, name: string): string {
  let f: fileIo.File | undefined = undefined;
  try {
    const p = ctx.filesDir + '/' + name;
    f = fileIo.openSync(p, fileIo.OpenMode.READ_ONLY);
    const stat = fileIo.statSync(f.fd);
    if (stat.size <= 0) {
      return '';
    }
    const buf: ArrayBuffer = new ArrayBuffer(stat.size);
    const n = fileIo.readSync(f.fd, buf);
    if (n <= 0) {
      return '';
    }
    const view: Uint8Array = new Uint8Array(buf, 0, n);
    // 存档是我们自己写的 UTF-8，逐字节 decode 比依赖 TextDecoder 更稳
    let out = '';
    let i = 0;
    while (i < view.length) {
      const b0 = view[i];
      if (b0 < 0x80) {
        out += String.fromCharCode(b0);
        i += 1;
      } else if (b0 >= 0xF0 && i + 3 < view.length) {
        const cp = ((b0 & 0x07) << 18) | ((view[i + 1] & 0x3F) << 12)
          | ((view[i + 2] & 0x3F) << 6) | (view[i + 3] & 0x3F);
        out += String.fromCodePoint(cp);
        i += 4;
      } else if (b0 >= 0xE0 && i + 2 < view.length) {
        const cp = ((b0 & 0x0F) << 12) | ((view[i + 1] & 0x3F) << 6) | (view[i + 2] & 0x3F);
        out += String.fromCharCode(cp);
        i += 3;
      } else if (b0 >= 0xC0 && i + 1 < view.length) {
        const cp = ((b0 & 0x1F) << 6) | (view[i + 1] & 0x3F);
        out += String.fromCharCode(cp);
        i += 2;
      } else {
        i += 1;
      }
    }
    return out;
  } catch (e) {
    return '';
  } finally {
    if (f !== undefined) {
      try {
        fileIo.closeSync(f);
      } catch (e) {
        // 忽略
      }
    }
  }
}

/** 存档文件是否存在。 */
export function hasArchive(ctx: common.UIAbilityContext): boolean {
  try {
    return fileIo.accessSync(libraryPath(ctx));
  } catch (e) {
    return false;
  }
}
