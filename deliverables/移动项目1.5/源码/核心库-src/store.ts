/**
 * 文档存储与持久化。
 *
 * DESIGN DECISION: 存文档，不存索引
 *   另一种做法是把倒排表序列化下来（省启动时间），但代价是：
 *   索引格式一旦改动，旧存档就废了；而且序列化/反序列化本身容易出静默错误
 *   （位置数组、Map 的键类型、浮点精度）。
 *
 *   个人资料库的文档量级（几百到几千）下，**重建索引是秒级**的。
 *   所以这里选择：**只持久化 DocItem[]，启动时重建索引。**
 *
 *   这条取舍写在代码里而不是只写在文档里——因为半年后改代码的人
 *   会先看这里，而不是看 README。
 *
 * ⚠️ 纯 TS：不触碰文件系统。真正的读写由调用方（ArkTS 层的 preferences/文件 API）
 *    完成，本模块只负责"文档列表 ⇄ JSON 字符串"这一段。
 *    这样它才能既被 Node 单测、又不在缺少平台能力时崩溃。
 */

import { DocItem, DocSource, DocStoreSnapshot } from './types';

/** 当前存档格式版本。格式变更时递增，load 时按版本迁移。 */
export const SNAPSHOT_VERSION = 1;

/**
 * 文档库。
 *
 * 只负责增删查与序列化，**不做索引**——索引由 InvertedIndex 管。
 * 两者分开的原因：文档是"数据"，索引是"数据之上的派生结构"，
 * 混在一起会让"重建索引"和"改文档"难以区分。
 */
export class DocStore {
  private docs: DocItem[] = [];
  private byId: Map<string, DocItem> = new Map<string, DocItem>();

  /** 全部文档（副本，避免外部改内部状态）。 */
  public all(): DocItem[] {
    const out: DocItem[] = [];
    for (let i = 0; i < this.docs.length; i++) {
      out.push(this.docs[i]);
    }
    return out;
  }

  public size(): number {
    return this.docs.length;
  }

  public get(id: string): DocItem | undefined {
    return this.byId.get(id);
  }

  public has(id: string): boolean {
    return this.byId.has(id);
  }

  /**
   * 加入一份文档。id 已存在时**覆盖**（并保持原位置），返回是否为新文档。
   *
   * 覆盖而不是拒绝：OCR 可能被重跑（用户重拍了一张更清晰的照片），
   * 这时替换文本是合理行为，不该报错。
   */
  public put(doc: DocItem): boolean {
    const isNew = !this.byId.has(doc.id);
    this.byId.set(doc.id, doc);
    if (isNew) {
      this.docs.push(doc);
    } else {
      for (let i = 0; i < this.docs.length; i++) {
        if (this.docs[i].id === doc.id) {
          this.docs[i] = doc;
          break;
        }
      }
    }
    return isNew;
  }

  /** 删除。返回是否真的删掉了。 */
  public remove(id: string): boolean {
    if (!this.byId.has(id)) {
      return false;
    }
    this.byId.delete(id);
    const next: DocItem[] = [];
    for (let i = 0; i < this.docs.length; i++) {
      if (this.docs[i].id !== id) {
        next.push(this.docs[i]);
      }
    }
    this.docs = next;
    return true;
  }

  public clear(): void {
    this.docs = [];
    this.byId = new Map<string, DocItem>();
  }

  /** 序列化为 JSON 字符串。 */
  public save(): string {
    const snap: DocStoreSnapshot = { version: SNAPSHOT_VERSION, docs: this.all() };
    return JSON.stringify(snap);
  }

  /**
   * 从 JSON 字符串恢复。
   *
   * **容错策略**：跳过不合法的条目，而不是整体失败。
   * 理由：一份存档里坏了一条，不该让用户丢掉其余全部资料。
   * 返回值是"被跳过的条数"，调用方可以据此提示用户。
   */
  public load(json: string): number {
    this.clear();
    if (json.length === 0) {
      return 0;
    }
    let raw: DocStoreSnapshot;
    try {
      raw = JSON.parse(json) as DocStoreSnapshot;
    } catch (e) {
      return 0;
    }
    if (raw === null || raw === undefined || raw.docs === undefined) {
      return 0;
    }
    let skipped = 0;
    for (let i = 0; i < raw.docs.length; i++) {
      const d = raw.docs[i];
      if (!isValidDoc(d)) {
        skipped += 1;
        continue;
      }
      this.put(d);
    }
    return skipped;
  }
}

/** 校验一个从 JSON 读进来的对象是否是可用的 DocItem。 */
export function isValidDoc(d: DocItem): boolean {
  if (d === null || d === undefined) {
    return false;
  }
  if (typeof d.id !== 'string' || d.id.length === 0) {
    return false;
  }
  if (typeof d.title !== 'string') {
    return false;
  }
  if (typeof d.text !== 'string') {
    return false;
  }
  if (typeof d.addedAt !== 'number' || !isFinite(d.addedAt)) {
    return false;
  }
  if (!isValidSource(d.source)) {
    return false;
  }
  return true;
}

export function isValidSource(s: DocSource): boolean {
  return s === 'camera' || s === 'album' || s === 'file' || s === 'note';
}

/** 生成一个文档 id。时间戳 + 序号，够用且可读。 */
export function makeDocId(seq: number, now: number): string {
  return 'd' + now.toString(36) + '-' + seq.toString(36);
}
