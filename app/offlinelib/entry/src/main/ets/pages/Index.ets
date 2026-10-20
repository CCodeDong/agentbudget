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
import { QueryOutcome, ImportOutcome } from '../lib/pipeline';
import { runSelfChecks, CheckSummary, CheckResult } from '../selfcheck/SelfCheck';

const BUDGET: BudgetInput = { latencyBudgetMs: 500, memoryBudgetKb: 4096, batteryPercent: 80 };
const OPTS_FIXED: SearchOptions = { topK: 3, minK: 1, maxK: 20 };
const OPTS_AUTO: SearchOptions = { topK: 0, minK: 1, maxK: 20 };

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

  aboutToAppear(): void {
    this.refreshStats();
    this.seedDemo();
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
      .then((_r: ImportOutcome) => { this.refreshStats(); });
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
        }
      })
      .catch((_e: Error) => { this.importStatus = '导入失败'; });
  }

  private doRemove(id: string): void {
    this.svc.removeDocument(id);
    this.refreshStats();
    this.hits = [];
    this.searchStatus = '已删除，请重新搜索';
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

      Column({ space: 8 }) {
        TextInput({ placeholder: '标题（可留空）', text: this.inputTitle })
          .height(40).fontSize(13)
          .onChange((v: string) => { this.inputTitle = v; })
        TextArea({ placeholder: '粘贴或输入要入库的内容…', text: this.inputText })
          .height(110).fontSize(13)
          .onChange((v: string) => { this.inputText = v; })
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
                Text(`${d.source} · ${d.text.length} 字`).fontSize(10).fontColor('#888888').width('100%')
              }
              .layoutWeight(1)
              .alignItems(HorizontalAlign.Start)
              Button('删除')
                .fontSize(11).height(28)
                .backgroundColor('#F0F0F0').fontColor('#C0392B')
                .onClick(() => { this.doRemove(d.id); })
            }
            .padding(10)
            .width('100%')
            .backgroundColor(Color.White)
            .borderRadius(8)
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

  build() {
    Column() {
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
    .width('100%')
    .height('100%')
    .backgroundColor('#F5F7FA')
  }
}
