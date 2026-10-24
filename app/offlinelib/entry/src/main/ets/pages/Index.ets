/**
 * 离线资料库 —— 主界面。
 *
 * 设计原则（都来自开题答辩时老师提的批评）：
 *   1. **打开就能用**：默认进搜索页，不需要先"建库"才能看到东西
 *   2. **可解释**：每次检索都告诉用户"为什么给你这几条"（k 是怎么定的）
 *   3. **诚实降级**：OCR 不可用时明确提示改用粘贴文本，而不是静默失败
 *
 * ⚠️ ArkTS 约束（L2 验证时实测踩到的，务必遵守）：
 *    · 对象字面量必须有上下文类型
 *    · 数组字面量元素类型必须可推断
 *    · 禁止 any / unknown / as unknown as
 */

import { LibraryService } from '../lib/pipeline';
import { FakeOcrEngine } from '../lib/ocr';
import { DocItem, Hit, Span, BudgetInput, SearchOptions, DocSource } from '../lib/types';
import { QueryOutcome, ImportOutcome, ImportInput } from '../lib/pipeline';
import { runSelfChecks, CheckSummary, CheckResult } from '../selfcheck/SelfCheck';
import { probeCapabilities, CapabilityProbe } from '../selfcheck/Capability';
import { common } from '@kit.AbilityKit';
import { readText, writeText, hasArchive, readTextByUri } from '../lib/librarystorage';
import { photoAccessHelper } from '@kit.MediaLibraryKit';
import { picker } from '@kit.CoreFileKit';
import { RealOcrEngine } from '../lib/realocr';
import { OcrResult } from '../lib/ocr';
import { runQualityTest, QualityRow, QUALITY_CASES } from '../selfcheck/OcrQuality';

const BUDGET: BudgetInput = { latencyBudgetMs: 500, memoryBudgetKb: 4096, batteryPercent: 80 };
// mergeAdjacent：把同一文档里相接的命中块合并成一条，避免同一段话返回多次。
const OPTS_FIXED: SearchOptions = { topK: 3, minK: 1, maxK: 20, mergeAdjacent: true };
const OPTS_AUTO: SearchOptions = { topK: 0, minK: 1, maxK: 20, mergeAdjacent: true };

@Entry
@Component
struct Index {
  // 服务实例（用假 OCR：本页要在没有 HMS 的环境里也能跑）
  private svc: LibraryService = new LibraryService(new FakeOcrEngine());

  @State currentTab: number = 0;
  @State query: string = '';
  @State hits: Hit[] = [];
  @State kUsed: number = 0;
  @State kSource: string = '-';
  @State limitedBy: string = '-';
  @State budgetReason: string = '-';
  @State candidateCount: number = 0;
  @State searchStatus: string = '输入关键词，或先在「资料」页添加一份内容';
  @State useAutoK: boolean = true;

  @State docs: DocItem[] = [];
  @State docCount: number = 0;
  @State chunkCount: number = 0;
  @State tombstone: number = 0;

  // 导入表单
  @State inputTitle: string = '';
  @State inputText: string = '';
  @State importStatus: string = '';

  // 自测
  @State checks: CheckResult[] = [];
  @State checkSummary: string = '尚未运行';
  @State checksDone: boolean = false;
  @State caps: CapabilityProbe[] = [];
  @State ocrStatus: string = '未运行';
  @State ocrText: string = '';
  @State pickStatus: string = '';
  @State qualityRows: QualityRow[] = [];
  @State qualityStatus: string = '未运行';
  /** 持久化状态，显示在「资料」页顶部，让用户知道这次是不是真的存下来了。 */
  @State persistStatus: string = '';

  // ---- 详情与编辑 ----
  /** 是否打开详情页。打开时主界面被替换掉，返回即关闭。 */
  @State detailOpen: boolean = false;
  @State detailId: string = '';
  @State detailTitle: string = '';
  @State detailText: string = '';
  @State detailEditing: boolean = false;
  @State detailStatus: string = '';

  // ---- 删除确认 ----
  /**
   * 待确认删除的文档 id。空串表示没有待确认的删除。
   *
   * 为什么用两步确认而不是弹窗：
   *   AlertDialog 在 2in1 的浮动窗口里位置不好控制，
   *   而"点一次变成『确认删除』、再点一次才删"是纯状态切换，
   *   不需要额外 API，行为也更容易验证。
   */
  @State pendingDeleteId: string = '';

  // ---- 搜索历史 ----
  @State history: string[] = [];

  // ---- 文件导入 ----
  @State fileStatus: string = '';

  aboutToAppear(): void {
    this.caps = probeCapabilities();
    this.refreshStats();
    this.restoreOrSeed();
  }

  // -------------------------------------------------------------------------
  // 持久化
  // -------------------------------------------------------------------------

  /**
   * 从沙箱读回资料；没有存档时才放示例。
   *
   * ⚠️ 这里区分两种"空"：
   *   ① 从来没有存档（首次启动）→ 放示例，让用户知道能干什么
   *   ② 有存档但里面没文档（用户删光了）→ **不放示例**，尊重用户的删除
   *   把两者混为一谈，用户体验就是"删了又回来"。
   */
  private restoreOrSeed(): void {
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      if (!hasArchive(ctx)) {
        this.persistStatus = '首次启动，已放入示例资料';
        this.seedDemo();
        return;
      }
      const json: string = readText(ctx, 'library.json');
      if (json.length === 0) {
        this.persistStatus = '存档读取失败';
        return;
      }
      const skipped: number = this.svc.load(json);
      this.refreshStats();
      this.persistStatus = skipped > 0
        ? `已恢复 ${this.svc.docCount()} 份（跳过 ${skipped} 条损坏数据）`
        : `已恢复 ${this.svc.docCount()} 份资料`;
    } catch (e) {
      this.persistStatus = '恢复失败';
    }
  }

  /** 立即落盘。任何改动之后都要调用。 */
  private persist(): void {
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      const ok = writeText(ctx, 'library.json', this.svc.save());
      if (!ok) {
        this.persistStatus = '保存失败（改动仅在本次运行有效）';
      }
    } catch (e) {
      this.persistStatus = '保存异常';
    }
  }

  // -------------------------------------------------------------------------
  // 数据操作
  // -------------------------------------------------------------------------

  /** 首次启动放一份示例内容，避免"打开是空的、不知道能干嘛"。 */
  private seedDemo(): void {
    if (this.svc.docCount() > 0) {
      return;
    }
    const demo: string = '示例资料：移动端的多智能体系统存在预算矛盾，' +
      '普通对话消耗一倍 token，而多智能体约为十五倍；手机能提供的上下文窗口只有四千到八千。' +
      '因此取舍是强制的：注入哪些工具、消息用什么形式、这一步在哪里执行，都要在预算内决定。';
    this.svc.importDocument({ title: '示例：预算调度笔记', source: 'note', uri: 'demo://1', text: demo })
      .then((_r: ImportOutcome) => {
        this.refreshStats();
        // 示例也要落盘：否则下次启动又会判定"没有存档"，再塞一遍
        this.persist();
      });
  }

  private refreshStats(): void {
    this.docs = this.svc.documents();
    this.docCount = this.svc.docCount();
    this.chunkCount = this.svc.chunkCount();
    this.tombstone = this.svc.tombstoneCount();
  }

  private doSearch(): void {
    const q: string = this.query.trim();
    if (q.length === 0) {
      this.searchStatus = '请先输入关键词';
      return;
    }
    if (this.svc.chunkCount() === 0) {
      this.searchStatus = '资料库还是空的，请先在「资料」页添加内容';
      return;
    }
    const opts: SearchOptions = this.useAutoK ? OPTS_AUTO : OPTS_FIXED;
    const out: QueryOutcome = this.svc.query(q, BUDGET, opts);
    this.hits = out.hits;
    this.kUsed = out.k;
    this.kSource = out.kSource;
    this.limitedBy = out.limitedBy;
    this.budgetReason = out.budgetReason;
    this.candidateCount = out.diagnostics.candidateCount;
    this.searchStatus = out.hits.length === 0
      ? '没有找到相关内容'
      : `找到 ${out.hits.length} 条（候选 ${out.diagnostics.candidateCount} 条）`;
    this.pushHistory(q);
  }

  private doImport(): void {
    const t: string = this.inputText.trim();
    if (t.length === 0) {
      this.importStatus = '内容不能为空';
      return;
    }
    const title: string = this.inputTitle.trim().length > 0 ? this.inputTitle.trim() : '未命名资料';
    const src: DocSource = 'note';
    this.svc.importDocument({ title: title, source: src, uri: 'note://' + Date.now().toString(), text: t })
      .then((r: ImportOutcome) => {
        this.importStatus = r.message;
        if (r.ok) {
          this.inputTitle = '';
          this.inputText = '';
          this.refreshStats();
          // 每次改动立即落盘：HarmonyOS 里 UIAbility 可能被系统直接回收，
          // "退出时保存"不可靠。
          this.persist();
        }
      })
      .catch((_e: Error) => { this.importStatus = '导入失败'; });
  }

  private doRemove(id: string): void {
    this.svc.removeDocument(id);
    this.refreshStats();
    this.hits = [];
    this.searchStatus = '已删除，请重新搜索';
    this.persist();
  }

  // -------------------------------------------------------------------------
  // 详情与编辑
  // -------------------------------------------------------------------------

  private openDetail(id: string): void {
    for (let i = 0; i < this.docs.length; i++) {
      if (this.docs[i].id === id) {
        this.detailId = id;
        this.detailTitle = this.docs[i].title;
        this.detailText = this.docs[i].text;
        this.detailEditing = false;
        this.detailStatus = '';
        this.detailOpen = true;
        return;
      }
    }
  }

  /** 保存编辑。走 replaceDocument，保持文档在列表中的位置。 */
  private saveDetail(): void {
    const t = this.detailText;
    if (t.trim().length === 0) {
      this.detailStatus = '内容不能为空';
      return;
    }
    const input: ImportInput = {
      title: this.detailTitle.trim().length > 0 ? this.detailTitle.trim() : '未命名资料',
      source: 'note',
      uri: 'note://edited/' + this.detailId,
      text: t
    };
    this.svc.replaceDocument(this.detailId, input)
      .then((r: ImportOutcome) => {
        this.detailStatus = r.message;
        if (r.ok) {
          this.detailEditing = false;
          this.refreshStats();
          this.persist();
          // 内容变了，旧结果已失效
          this.hits = [];
          this.searchStatus = '资料已更新，请重新搜索';
        }
      })
      .catch((_e: Error) => { this.detailStatus = '保存失败'; });
  }

  // -------------------------------------------------------------------------
  // 删除确认（两步）
  // -------------------------------------------------------------------------

  private askDelete(id: string): void {
    this.pendingDeleteId = id;
  }

  private confirmDelete(): void {
    const id = this.pendingDeleteId;
    this.pendingDeleteId = '';
    if (id.length === 0) {
      return;
    }
    this.doRemove(id);
  }

  private cancelDelete(): void {
    this.pendingDeleteId = '';
  }

  // -------------------------------------------------------------------------
  // 搜索历史
  // -------------------------------------------------------------------------

  /** 记一条历史。同一条移到最前，最多保留 8 条。 */
  private pushHistory(q: string): void {
    const out: string[] = [];
    out.push(q);
    for (let i = 0; i < this.history.length && out.length < 8; i++) {
      if (this.history[i] !== q) {
        out.push(this.history[i]);
      }
    }
    this.history = out;
  }

  private clearHistory(): void {
    this.history = [];
  }

  // -------------------------------------------------------------------------
  // 文件导入
  // -------------------------------------------------------------------------

  /**
   * 用系统文件选择器导入 txt / md。
   *
   * DocumentViewPicker 和相册选择器一样**不需要申请权限**：
   * 由系统界面让用户挑文件，应用只拿到那一个文件的 URI。
   * 所以零权限的主张在这里同样成立。
   */
  private pickFileAndImport(): void {
    this.fileStatus = '请选择 txt 或 md 文件…';
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      // 局部变量不能叫 picker：会遮蔽导入的模块名（编译报「used before its declaration」）
      const filePicker: picker.DocumentViewPicker = new picker.DocumentViewPicker(ctx);
      const opts: picker.DocumentSelectOptions = new picker.DocumentSelectOptions();
      opts.maxSelectNumber = 1;
      const filters: string[] = ['.txt', '.md', '.markdown'];
      opts.fileSuffixFilters = filters;

      filePicker.select(opts)
        .then((uris: string[]) => {
          if (uris.length === 0) {
            this.fileStatus = '没有选择文件';
            return;
          }
          this.importFromUri(ctx, uris[0]);
        })
        .catch((_e: Error) => { this.fileStatus = '打开文件选择器失败'; });
    } catch (e) {
      this.fileStatus = '无法打开文件选择器';
    }
  }

  private importFromUri(ctx: common.UIAbilityContext, uri: string): void {
    try {
      const text = readTextByUri(uri);
      if (text.length === 0) {
        this.fileStatus = '文件为空或无法读取';
        return;
      }
      let name: string = uri;
      const slash = uri.lastIndexOf('/');
      if (slash >= 0 && slash + 1 < uri.length) {
        name = uri.substring(slash + 1);
      }
      this.svc.importDocument({ title: name, source: 'file', uri: uri, text: text })
        .then((r: ImportOutcome) => {
          this.fileStatus = r.message;
          if (r.ok) {
            this.refreshStats();
            this.persist();
          }
        })
        .catch((_e: Error) => { this.fileStatus = '导入失败'; });
    } catch (e) {
      this.fileStatus = '读取文件失败';
    }
  }

  private runChecks(): void {
    this.checkSummary = '运行中…';
    runSelfChecks()
      .then((s: CheckSummary) => {
        this.checks = s.results;
        this.checksDone = true;
        this.checkSummary = s.failed === 0
          ? `全部通过：${s.passed} / ${s.total}`
          : `有失败：${s.failed} / ${s.total}`;
      })
      .catch((_e: Error) => { this.checkSummary = '自测运行失败'; });
  }



  /**
   * 从相册选一张图，识别后把文字填进导入框。
   *
   * 为什么用选择器而不是调相机：
   * 相机需要 ohos.permission.CAMERA，会破坏本软件"零权限"的主张；
   * 系统相册选择器不需要任何权限，由系统界面让用户挑选，
   * 应用只拿到那一张图的 URI。
   */
  private pickImageAndOcr(): void {
    this.pickStatus = '请在系统相册中选择图片…';
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      // 局部变量不叫 picker：会遮蔽从 @kit.CoreFileKit 导入的 picker 模块
      const photoPicker: photoAccessHelper.PhotoViewPicker = new photoAccessHelper.PhotoViewPicker();
      const opts = new photoAccessHelper.PhotoSelectOptions();
      opts.MIMEType = photoAccessHelper.PhotoViewMIMETypes.IMAGE_TYPE;
      opts.maxSelectNumber = 1;

      photoPicker.select(opts)
        .then((res: photoAccessHelper.PhotoSelectResult) => {
          if (res.photoUris.length === 0) {
            this.pickStatus = '没有选择图片';
            return;
          }
          const uri = res.photoUris[0];
          this.pickStatus = '识别中…';
          const engine = new RealOcrEngine(ctx);
          engine.recognize(uri)
            .then((r: OcrResult) => {
              if (r.error !== undefined) {
                this.pickStatus = r.error;
                return;
              }
              // 识别结果填进导入框，由用户确认后再入库 ——
              // 不直接入库，因为识别可能有错，用户需要看一眼
              this.inputText = r.text;
              if (this.inputTitle.length === 0) {
                this.inputTitle = '图片导入 ' + new Date().toLocaleDateString();
              }
              this.ocrText = r.text;
              this.ocrStatus = `识别成功：${r.text.length} 字 · 用时 ${r.elapsedMs} ms`;
              this.pickStatus = '已填入下方输入框，确认后点「加入资料库」';
            })
            .catch((e: Error) => { this.pickStatus = '识别失败：' + e.message; });
        })
        .catch((e: Error) => { this.pickStatus = '选择图片失败：' + e.message; });
    } catch (e) {
      this.pickStatus = '无法打开相册选择器';
    }
  }

  /** OCR 质量测试：用已知答案的合成图集量化退化。 */
  private runQuality(): void {
    this.qualityStatus = '运行中…';
    this.qualityRows = [];
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      const engine = new RealOcrEngine(ctx);
      if (!engine.available()) {
        this.qualityStatus = '该设备不支持 OCR，无法测试';
        return;
      }
      runQualityTest(engine)
        .then((rows: QualityRow[]) => {
          this.qualityRows = rows;
          let ok = 0;
          for (let i = 0; i < rows.length; i++) {
            if (rows[i].error === '') { ok += 1; }
          }
          this.qualityStatus = `完成：${ok} / ${rows.length} 张有结果`;
        })
        .catch((e: Error) => { this.qualityStatus = '测试失败：' + e.message; });
    } catch (e) {
      this.qualityStatus = '初始化失败';
    }
  }
  /** L4：真实 OCR 实测（内置测试图，不依赖相机）。 */
  private runOcrTest(): void {
    this.ocrStatus = '识别中…';
    this.ocrText = '';
    try {
      // getContext(this) 在页面里拿到的就是 UIAbilityContext
      const ctx = getContext(this) as common.UIAbilityContext;
      const engine = new RealOcrEngine(ctx);
      if (!engine.available()) {
        this.ocrStatus = '该设备不支持 OCR';
        return;
      }
      engine.recognize('rawfile:ocr_sample.png')
        .then((r: OcrResult) => {
          if (r.error !== undefined) {
            this.ocrStatus = r.error;
            return;
          }
          this.ocrStatus = `识别成功：${r.text.length} 字 · 用时 ${r.elapsedMs} ms`;
          this.ocrText = r.text;
        })
        .catch((e: Error) => { this.ocrStatus = 'OCR 调用失败：' + e.message; });
    } catch (e) {
      this.ocrStatus = 'OCR 初始化失败';
    }
  }
  // -------------------------------------------------------------------------
  // 视图片段
  // -------------------------------------------------------------------------

  /** 把带高亮的文本渲染成多个 Span。 */
  @Builder
  highlightText(text: string, spans: Span[]) {
    Text() {
      Span(text.substring(0, spans.length > 0 ? spans[0].start : text.length))
      ForEach(spans, (s: Span) => {
        Span(text.substring(s.start, s.end))
          .fontColor('#C0392B')
          .fontWeight(FontWeight.Bold)
      }, (_s: Span, i: number) => i.toString())
      if (spans.length > 0) {
        Span(text.substring(spans[spans.length - 1].end))
      }
    }
    .fontSize(13)
    .width('100%')
  }

  @Builder
  searchTab() {
    Column({ space: 10 }) {
      Row({ space: 8 }) {
        TextInput({ placeholder: '搜索你的资料…', text: this.query })
          .layoutWeight(1)
          .height(42)
          .fontSize(14)
          .onChange((v: string) => { this.query = v; })
          .onSubmit(() => { this.doSearch(); })
        Button('搜索')
          .height(42)
          .fontSize(14)
          .onClick(() => { this.doSearch(); })
      }
      .width('100%')

      Row({ space: 8 }) {
        Text('检索深度').fontSize(12).fontColor('#666666')
        Toggle({ type: ToggleType.Switch, isOn: this.useAutoK })
          .onChange((on: boolean) => { this.useAutoK = on; })
        Text(this.useAutoK ? '按得分分布自适应' : '固定 3 条')
          .fontSize(12)
          .fontColor('#0A59F7')
      }
      .width('100%')

      // 搜索历史：点一下就用那个词重搜
      if (this.history.length > 0) {
        Row({ space: 6 }) {
          Text('最近').fontSize(10).fontColor('#999999')
          ForEach(this.history, (h: string) => {
            Text(h)
              .fontSize(10.5)
              .fontColor('#0A59F7')
              .padding({ left: 8, right: 8, top: 3, bottom: 3 })
              .backgroundColor('#E8F0FE')
              .borderRadius(10)
              .onClick(() => {
                this.query = h;
                this.doSearch();
              })
          }, (h: string, i: number) => h + i.toString())
          Text('清空')
            .fontSize(10).fontColor('#999999')
            .onClick(() => { this.clearHistory(); })
        }
        .width('100%')
      }

      // 决策解释条
      if (this.kUsed > 0) {
        Column({ space: 3 }) {
          Text(`返回 ${this.kUsed} 条 · 来源 ${this.kSource} · 限制方 ${this.limitedBy}`)
            .fontSize(11).fontColor('#0A59F7').width('100%')
          Text(`候选 ${this.candidateCount} 条 · 资源约束：${this.budgetReason}`)
            .fontSize(10).fontColor('#888888').width('100%')
        }
        .padding(8)
        .width('100%')
        .backgroundColor('#EEF4FF')
        .borderRadius(6)
      }

      Text(this.searchStatus).fontSize(11).fontColor('#888888').width('100%')

      List({ space: 8 }) {
        ForEach(this.hits, (h: Hit) => {
          ListItem() {
            Column({ space: 4 }) {
              Row({ space: 6 }) {
                Text(this.titleOf(h.chunk.docId)).fontSize(13).fontWeight(FontWeight.Medium).layoutWeight(1)
                Text(h.score.toFixed(2)).fontSize(10).fontColor('#0A59F7')
              }
              .width('100%')
              this.highlightText(h.chunk.text, h.spans)
            }
            .padding(10)
            .width('100%')
            .backgroundColor(Color.White)
            .borderRadius(8)
          }
        }, (h: Hit) => h.chunk.id)
      }
      .layoutWeight(1)
      .width('100%')
    }
    .padding(14)
    .width('100%')
    .height('100%')
    .backgroundColor('#F5F7FA')
  }

  private titleOf(docId: string): string {
    for (let i = 0; i < this.docs.length; i++) {
      if (this.docs[i].id === docId) {
        return this.docs[i].title;
      }
    }
    return docId;
  }

  @Builder
  libraryTab() {
    Column({ space: 10 }) {
      Row({ space: 12 }) {
        Text(`资料 ${this.docCount} 份`).fontSize(12).fontColor('#333333')
        Text(`片段 ${this.chunkCount} 个`).fontSize(12).fontColor('#333333')
        if (this.tombstone > 0) {
          Text(`待整理 ${this.tombstone}`).fontSize(12).fontColor('#C0392B')
        }
      }
      .width('100%')

      // 持久化状态：让用户看得见"这次有没有存下来"
      if (this.persistStatus.length > 0) {
        Row({ space: 6 }) {
          Text('存档').fontSize(10).fontColor('#0A8F4C')
          Text(this.persistStatus).fontSize(10).fontColor('#666666').layoutWeight(1)
        }
        .width('100%')
      }

      Column({ space: 8 }) {
        TextInput({ placeholder: '标题（可留空）', text: this.inputTitle })
          .height(40).fontSize(13)
          .onChange((v: string) => { this.inputTitle = v; })
        TextArea({ placeholder: '粘贴或输入要入库的内容…', text: this.inputText })
          .height(110).fontSize(13)
          .onChange((v: string) => { this.inputText = v; })

        Row({ space: 8 }) {
          Button('从相册选图识别')
            .height(34).fontSize(12)
            .backgroundColor('#0A59F7')
            .onClick(() => { this.pickImageAndOcr(); })
          Button('导入文件')
            .height(34).fontSize(12)
            .backgroundColor('#E8F0FE').fontColor('#0A59F7')
            .onClick(() => { this.pickFileAndImport(); })
        }
        .width('100%')
        if (this.pickStatus.length > 0) {
          Text(this.pickStatus).fontSize(10).fontColor('#666666').width('100%')
        }
        if (this.fileStatus.length > 0) {
          Text(this.fileStatus).fontSize(10).fontColor('#0A59F7').width('100%')
        }
        Row({ space: 8 }) {
          Button('加入资料库')
            .height(38).fontSize(13)
            .onClick(() => { this.doImport(); })
          if (this.importStatus.length > 0) {
            Text(this.importStatus).fontSize(11).fontColor('#0A8F4C').layoutWeight(1)
          }
        }
        .width('100%')
      }
      .padding(10)
      .width('100%')
      .backgroundColor(Color.White)
      .borderRadius(8)

      List({ space: 6 }) {
        ForEach(this.docs, (d: DocItem) => {
          ListItem() {
            Row({ space: 8 }) {
              Column({ space: 2 }) {
                Text(d.title).fontSize(13).width('100%')
                Text(`${d.source} · ${d.text.length} 字 · 点开查看`)
                  .fontSize(10).fontColor('#888888').width('100%')
              }
              .layoutWeight(1)
              .alignItems(HorizontalAlign.Start)

              // 删除两步确认：一点就删在手机上太容易误触，
              // 而资料删掉是找不回来的。
              if (this.pendingDeleteId === d.id) {
                Row({ space: 6 }) {
                  Button('确认删除')
                    .fontSize(11).height(28)
                    .backgroundColor('#C0392B').fontColor(Color.White)
                    .onClick(() => { this.confirmDelete(); })
                  Button('取消')
                    .fontSize(11).height(28)
                    .backgroundColor('#F0F0F0').fontColor('#333333')
                    .onClick(() => { this.cancelDelete(); })
                }
              } else {
                Button('删除')
                  .fontSize(11).height(28)
                  .backgroundColor('#F0F0F0').fontColor('#C0392B')
                  .onClick(() => { this.askDelete(d.id); })
              }
            }
            .padding(10)
            .width('100%')
            .backgroundColor(Color.White)
            .borderRadius(8)
            .onClick(() => { this.openDetail(d.id); })
          }
        }, (d: DocItem) => d.id)
      }
      .layoutWeight(1)
      .width('100%')
    }
    .padding(14)
    .width('100%')
    .height('100%')
    .backgroundColor('#F5F7FA')
  }

  @Builder
  advancedTab() {
    Column({ space: 10 }) {
      // 能力探测（canIUse，零风险：不 import 任何 Kit）
      Column({ space: 5 }) {
        Text('设备能力探测（canIUse）').fontSize(14).fontWeight(FontWeight.Bold).width('100%')
        Text('只用 canIUse 查询，不 import 任何 Kit —— 因此不可能把应用拖崩')
          .fontSize(10).fontColor('#888888').width('100%')
        ForEach(this.caps, (c: CapabilityProbe) => {
          Row({ space: 8 }) {
            Text(c.available ? '✓' : '✗')
              .fontSize(13).width(16)
              .fontColor(c.available ? '#0A8F4C' : '#C0392B')
            Column({ space: 1 }) {
              Text(c.label).fontSize(11.5).width('100%')
              Text(c.syscap.replace('SystemCapability.', '')).fontSize(9)
                .fontColor('#999999').width('100%')
            }
            .layoutWeight(1)
            .alignItems(HorizontalAlign.Start)
          }
          .width('100%')
          .padding({ left: 8, right: 8, top: 4, bottom: 4 })
        }, (c: CapabilityProbe) => c.syscap)
      }
      .padding(12)
      .width('100%')
      .backgroundColor(Color.White)
      .borderRadius(8)



      // OCR 质量测试（已知答案，量化退化）
      Column({ space: 6 }) {
        Text('OCR 质量测试（' + QUALITY_CASES.length.toString() + ' 张已知答案的图）').fontSize(14).fontWeight(FontWeight.Bold).width('100%')
        Text('同一段文字，不同退化条件 —— 算字符级召回/精确率，而不是靠印象')
          .fontSize(10).fontColor('#888888').width('100%')
        Row({ space: 10 }) {
          Button('运行质量测试').height(36).fontSize(13)
            .onClick(() => { this.runQuality(); })
          Text(this.qualityStatus).fontSize(11).fontColor('#666666').layoutWeight(1)
        }
        .width('100%')
        if (this.qualityRows.length > 0) {
          Row({ space: 3 }) {
            Text('图').fontSize(9).fontColor('#999999').width(86)
            Text('召回').fontSize(9).fontColor('#999999').width(36)
            Text('精确').fontSize(9).fontColor('#999999').width(36)
            Text('F1').fontSize(9).fontColor('#999999').width(32)
            Text('覆盖').fontSize(9).fontColor('#BBBBBB').width(36)
            Text('锐度').fontSize(9).fontColor('#0A59F7').width(38)
            Text('置信').fontSize(9).fontColor('#0A59F7').width(34)
            Text('ms').fontSize(9).fontColor('#999999').width(30)
          }
          .width('100%')
          Row({ space: 3 }) {
            Text('覆盖=旧方案(已验证无效)  锐度=新方案  置信由锐度给出')
              .fontSize(8).fontColor('#BBBBBB').width('100%')
          }
          .width('100%')
          ForEach(this.qualityRows, (r: QualityRow) => {
            Row({ space: 3 }) {
              Text(r.label).fontSize(9.5).width(86)
              Text(r.error === '' ? r.recall.toFixed(0) + '%' : '—').fontSize(9.5)
                .fontColor(r.recall >= 90 ? '#0A8F4C' : (r.recall >= 60 ? '#B8860B' : '#C0392B')).width(36)
              Text(r.error === '' ? r.precision.toFixed(0) + '%' : '—').fontSize(9.5).width(36)
              Text(r.error === '' ? r.f1.toFixed(0) + '%' : '—').fontSize(9.5).width(32)
              Text(r.coverage > 0 ? r.coverage.toFixed(2) : '—').fontSize(9.5)
                .fontColor('#BBBBBB').width(36)
              Text(r.sharpness > 0 ? r.sharpness.toFixed(1) : '—').fontSize(9.5)
                .fontColor('#0A59F7').width(38)
              Text(r.confidence > 0 ? r.confidence.toFixed(2) : '—').fontSize(9.5)
                .fontColor(r.confidence >= 0.9 ? '#0A8F4C'
                  : (r.confidence >= 0.7 ? '#B8860B' : '#C0392B')).width(34)
              Text(r.error === '' ? r.ms.toString() : '—').fontSize(9.5)
                .fontColor('#888888').width(30)
            }
            .width('100%')
            .padding({ top: 2, bottom: 2 })
          }, (r: QualityRow, i: number) => r.label + i.toString())
        }
      }
      .padding(12)
      .width('100%')
      .backgroundColor(Color.White)
      .borderRadius(8)
      // L4：真实 OCR 实测
      Column({ space: 6 }) {
        Text('OCR 实测（CoreVisionKit）').fontSize(14).fontWeight(FontWeight.Bold).width('100%')
        Text('用内置测试图跑一次真实 OCR —— 不依赖相机')
          .fontSize(10).fontColor('#888888').width('100%')
        Row({ space: 10 }) {
          Button('运行 OCR 实测')
            .height(36).fontSize(13)
            .onClick(() => { this.runOcrTest(); })
          Text(this.ocrStatus).fontSize(11).fontColor('#666666').layoutWeight(1)
        }
        .width('100%')
        if (this.ocrText.length > 0) {
          Text(this.ocrText)
            .fontSize(11)
            .width('100%')
            .padding(8)
            .backgroundColor('#F5F7FA')
            .borderRadius(6)
        }
      }
      .padding(12)
      .width('100%')
      .backgroundColor(Color.White)
      .borderRadius(8)
      Column({ space: 6 }) {
        Text('四个环节，四个信号').fontSize(14).fontWeight(FontWeight.Bold).width('100%')
        Text('这是本项目的研究主张：调度不能用单一的「剩余预算」驱动。')
          .fontSize(11).fontColor('#666666').width('100%')
        Text('· 感知（OCR）→ 识别置信度决定收下/重拍/丢弃')
          .fontSize(11).width('100%')
        Text('· 索引 → 内容规模决定分块大小')
          .fontSize(11).width('100%')
        Text('· 检索 → 得分分布决定返回几条')
          .fontSize(11).width('100%')
        Text('· 资源 → 延迟/内存/电量决定还取得起几条')
          .fontSize(11).width('100%')
      }
      .padding(12)
      .width('100%')
      .backgroundColor(Color.White)
      .borderRadius(8)

      Column({ space: 8 }) {
        Row({ space: 8 }) {
          Button('运行设备内自测')
            .height(38).fontSize(13)
            .onClick(() => { this.runChecks(); })
          Text(this.checkSummary).fontSize(12)
            .fontColor(this.checkSummary.indexOf('全部通过') >= 0 ? '#0A8F4C' : '#666666')
            .layoutWeight(1)
        }
        .width('100%')

        if (this.checksDone) {
          List({ space: 1 }) {
            ForEach(this.checks, (c: CheckResult) => {
              ListItem() {
                Row({ space: 8 }) {
                  Text(c.passed ? '✓' : '✗')
                    .fontSize(13).width(18)
                    .fontColor(c.passed ? '#0A8F4C' : '#C0392B')
                  Text(c.name).fontSize(11).layoutWeight(1)
                  if (!c.passed) {
                    Text(c.detail).fontSize(10).fontColor('#C0392B')
                  }
                }
                .padding({ left: 8, right: 8, top: 5, bottom: 5 })
                .width('100%')
              }
            }, (c: CheckResult, i: number) => c.name + i.toString())
          }
          .layoutWeight(1)
          .width('100%')
        }
      }
      .padding(12)
      .width('100%')
      .layoutWeight(1)
      .backgroundColor(Color.White)
      .borderRadius(8)
    }
    .padding(14)
    .width('100%')
    .height('100%')
    .backgroundColor('#F5F7FA')
  }

  /** 详情页：查看与编辑一份资料。打开时替换主界面，返回即关闭。 */
  @Builder
  detailView() {
    Column({ space: 0 }) {
      // 顶栏
      Row({ space: 10 }) {
        Button('← 返回')
          .fontSize(13).height(34)
          .backgroundColor('#F0F0F0').fontColor('#333333')
          .onClick(() => {
            this.detailOpen = false;
            this.detailEditing = false;
            this.detailStatus = '';
          })
        Text(this.detailEditing ? '编辑资料' : '资料详情')
          .fontSize(14).fontWeight(FontWeight.Bold).layoutWeight(1)
        if (!this.detailEditing) {
          Button('编辑')
            .fontSize(12).height(34)
            .onClick(() => {
              this.detailEditing = true;
              this.detailStatus = '';
            })
        }
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 12, bottom: 10 })
      .backgroundColor('#F5F7FA')

      Column({ space: 8 }) {
        if (this.detailEditing) {
          TextInput({ placeholder: '标题', text: this.detailTitle })
            .height(40).fontSize(13)
            .onChange((v: string) => { this.detailTitle = v; })
          TextArea({ placeholder: '正文', text: this.detailText })
            .layoutWeight(1).fontSize(12.5)
            .onChange((v: string) => { this.detailText = v; })
        } else {
          Text(this.detailTitle)
            .fontSize(15).fontWeight(FontWeight.Bold).width('100%')
          Text(`${this.detailText.length} 字`)
            .fontSize(10).fontColor('#888888').width('100%')
          Scroll() {
            Text(this.detailText)
              .fontSize(12.5)
              .width('100%')
              .lineHeight(21)
          }
          .layoutWeight(1)
          .width('100%')
          .align(Alignment.TopStart)
        }
      }
      .layoutWeight(1)
      .padding(14)
      .width('100%')

      // 底栏
      Row({ space: 10 }) {
        if (this.detailEditing) {
          Button('保存')
            .height(38).fontSize(13).layoutWeight(1)
            .onClick(() => { this.saveDetail(); })
          Button('取消')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor('#F0F0F0').fontColor('#333333')
            .onClick(() => {
              this.detailEditing = false;
              // 放弃修改：重新从列表里读回原值
              this.openDetail(this.detailId);
              this.detailStatus = '';
            })
        } else {
          Text(this.detailStatus.length > 0 ? this.detailStatus : '只读。点「编辑」可修改内容。')
            .fontSize(11).fontColor('#888888').layoutWeight(1)
        }
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 14 })
      .backgroundColor('#F5F7FA')
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F5F7FA')
  }

  build() {
    Column() {
      if (this.detailOpen) {
        this.detailView()
      } else {
        Tabs({ barPosition: BarPosition.End, index: this.currentTab }) {
          TabContent() { this.searchTab() }.tabBar('搜索')
          TabContent() { this.libraryTab() }.tabBar('资料')
          TabContent() { this.advancedTab() }.tabBar('高级')
        }
        .onChange((i: number) => { this.currentTab = i; })
        .barHeight(52)
        .width('100%')
        .height('100%')
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F5F7FA')
  }
}
