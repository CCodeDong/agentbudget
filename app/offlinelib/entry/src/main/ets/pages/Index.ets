/**
 * 自测页面 —— 打开应用就跑断言，结果直接显示。
 *
 * 这一页存在的唯一目的：**让"技术路线可核实"变成屏幕上看得见的东西**。
 * 截图即可作为证据，不需要对方装环境、读代码、跑命令。
 */

import { runSelfChecks } from '../selfcheck/SelfCheck';

interface CheckResult {
  name: string;
  passed: boolean;
  detail: string;
}

interface CheckSummary {
  total: number;
  passed: number;
  failed: number;
  results: CheckResult[];
}

@Entry
@Component
struct Index {
  @State summary: CheckSummary = { total: 0, passed: 0, failed: 0, results: [] };
  @State running: boolean = true;
  @State statusLine: string = '正在运行自测…';

  aboutToAppear(): void {
    this.start();
  }

  private start(): void {
    this.running = true;
    runSelfChecks()
      .then((s: CheckSummary) => {
        this.summary = s;
        this.running = false;
        this.statusLine = s.failed === 0
          ? `全部通过：${s.passed} / ${s.total}`
          : `有失败：${s.failed} / ${s.total}`;
      })
      .catch((e: Error) => {
        this.running = false;
        this.statusLine = '自测崩溃：' + e.message;
      });
  }

  build() {
    Column({ space: 0 }) {
      // 标题区
      Column({ space: 6 }) {
        Text('离线资料库 · 核心自测')
          .fontSize(22)
          .fontWeight(FontWeight.Bold)
          .width('100%')
        Text('这一页把关键断言搬到设备上跑：编译兼容性 + 运行时行为一致性')
          .fontSize(12)
          .fontColor('#666666')
          .width('100%')
        Row({ space: 8 }) {
          Text(this.statusLine)
            .fontSize(14)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.summary.failed === 0 && !this.running ? '#0A8F4C' : '#C0392B')
          if (this.running) {
            LoadingProgress().width(16).height(16)
          }
        }
        .width('100%')
        .margin({ top: 4 })
      }
      .padding(16)
      .width('100%')
      .backgroundColor('#F5F7FA')

      // 结果列表
      List({ space: 1 }) {
        ForEach(this.summary.results, (r: CheckResult) => {
          ListItem() {
            Row({ space: 10 }) {
              Text(r.passed ? '✓' : '✗')
                .fontSize(16)
                .fontWeight(FontWeight.Bold)
                .fontColor(r.passed ? '#0A8F4C' : '#C0392B')
                .width(20)
              Column({ space: 2 }) {
                Text(r.name)
                  .fontSize(13)
                  .width('100%')
                if (!r.passed) {
                  Text(r.detail)
                    .fontSize(11)
                    .fontColor('#C0392B')
                    .width('100%')
                }
              }
              .layoutWeight(1)
              .alignItems(HorizontalAlign.Start)
            }
            .width('100%')
            .padding({ left: 14, right: 14, top: 9, bottom: 9 })
          }
        }, (r: CheckResult, i: number) => r.name + i.toString())
      }
      .layoutWeight(1)
      .width('100%')
      .backgroundColor(Color.White)

      // 底部：重跑
      Row({ space: 12 }) {
        Button('重新运行')
          .fontSize(14)
          .height(38)
          .layoutWeight(1)
          .onClick(() => { this.start(); })
        Button('存档往返')
          .fontSize(14)
          .height(38)
          .layoutWeight(1)
          .backgroundColor('#E6E6E6')
          .fontColor(Color.Black)
          .onClick(() => {
            this.statusLine = '存档往返已包含在自测里（见"存档恢复后仍能检索"）';
          })
      }
      .padding(12)
      .width('100%')
      .backgroundColor('#F5F7FA')
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#F5F7FA')
  }
}
