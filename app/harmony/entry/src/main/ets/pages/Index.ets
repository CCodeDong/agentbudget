/**
 * Multi-agent orchestration console.
 *
 * This page exists to make the paper's decision visible on a phone: for one
 * task it shows WHERE the step runs, HOW the tool context is rendered, WHAT
 * message form the agents use, and WHY -- plus the trace that proves the
 * verifier actually received the arguments.
 *
 * A deliberately visible failure mode: set the budget slider past 30% while the
 * network is weak, and the `summary` form truncates the tool arguments so the
 * verifier reports FAIL. That is the "cheap where it is broken, complete where it
 * is not cheap" property of truncating summarisation, reproduced interactively.
 */
import { Budget, LedgerState, NetState, NetTier, RouteTarget } from '../model/Types';
import { AgentRuntime, RunResult } from '../agents/AgentRuntime';
import { AgentWire, WireExchange } from '../agents/AgentWire';
import { probeNetwork } from '../core/NetworkProbe';
import { ALL_TOOLS } from '../agents/ToolRegistry';

const TIERS: NetTier[] = [NetTier.Wifi, NetTier.Cellular, NetTier.Weak, NetTier.Offline];

@Entry
@Component
struct Index {
  @State utterance: string = 'search my files for the quarterly report';
  @State tier: NetTier = NetTier.Weak;
  @State lanOn: boolean = true;
  @State util: number = 0.85;
  // -50 selects the score-driven adaptive policy at alpha = 50% of the top
  // score, matching the Cangjie CLI's default sentinel. 0 would select the
  // budget-driven policy, which is a baseline the paper measured to be dominated
  // by a fixed k -- it must never be the shipped default.
  @State topK: number = -50;

  // WIRE ENCODING, not the @hms.ai.A2A binding.
  // Importing the kit directly aborts the process at load time on any device
  // without the AgentKit HSP -- measured on the Pura 90 Pro emulator (phone,
  // API 26) and on the 2in1 MateBook Pro (API 23). The real binding lives in
  // agents/A2AAgentServer.ets and is deliberately kept out of the load graph.
  private wire: AgentWire = new AgentWire();
  @State a2aRan: boolean = false;
  @State a2aWireBytes: number = 0;
  @State a2aForm: string = '-';
  @State a2aStrategy: string = '-';

  @State outRoute: string = '-';
  @State outForm: string = '-';
  @State outStrategy: string = '-';
  @State outReason: string = '-';
  @State outTool: string = '-';
  @State ctxTokens: number = 0;
  @State baseTokens: number = 0;
  @State msgTokens: number = 0;
  @State ok: boolean = false;
  @State ran: boolean = false;
  @State trace: string[] = [];

  private runtime: AgentRuntime = new AgentRuntime();

  private runStep(): void {
    const net: NetState = probeNetwork(this.lanOn);
    // Respect the user's tier choice; the probe supplies RTT/metering detail.
    net.tier = this.tier;

    const budget: Budget = {
      tokenCap: 8000, latencyCapMs: 60000, cloudCallCap: 10, trafficCapKb: 50000
    };
    const ledger: LedgerState = {
      tokensSpent: Math.round(8000 * this.util), latencySpentMs: 0, cloudCalls: 0
    };

    const res: RunResult = this.runtime.run(
      this.utterance, 0.8, net, budget, ledger, this.topK
    );

    this.outRoute = res.plan.route;
    this.outForm = res.plan.msgForm;
    this.outStrategy = res.plan.toolStrategy;
    this.outReason = res.plan.reason;
    this.outTool = res.toolChosen;
    this.ctxTokens = res.contextTokens;
    this.baseTokens = res.baselineTokens;
    this.msgTokens = res.messageTokens;
    this.ok = res.success;
    this.ran = true;

    const head: string[] = [
      `tool context: ${res.contextTokens} tok  (eager baseline: ${res.baselineTokens} tok)`,
      `inter-agent messages: ${res.messageTokens} tok`,
      res.success ? 'VERDICT: OK' : 'VERDICT: FAIL'
    ];
    this.trace = head.concat(res.trace);
  }

  private tierLabel(t: NetTier): string {
    if (t === NetTier.Wifi) { return 'WiFi'; }
    if (t === NetTier.Cellular) { return '5G'; }
    if (t === NetTier.Weak) { return '弱网'; }
    return '离线';
  }

  /**
   * Cycle adaptive -> 1 -> 3 -> 5 -> 8 -> adaptive.
   *
   * Adaptive is first and is the default because it is the policy the library
   * actually ships; the fixed values exist so the demo can reproduce the
   * baselines the paper compares against.
   */
  private nextTopK(current: number): number {
    if (current < 0) { return 1; }
    if (current === 1) { return 3; }
    if (current === 3) { return 5; }
    if (current === 5) { return 8; }
    return -50;
  }

  private topKLabel(): string {
    return this.topK < 0 ? 'top-k 自适应' : `top-k ${this.topK}`;
  }

  /** Run the reply path locally and show what would go on the wire. */
  private runA2ADryRun(): void {
    const ex: WireExchange = this.wire.dryRun(this.utterance, 'agentbudget-executor', this.tier);
    this.a2aWireBytes = ex.wireBytes;
    this.a2aForm = ex.msgFormLabel;
    this.a2aStrategy = ex.toolStrategy;
    this.a2aRan = true;
  }

  build() {
    Column({ space: 10 }) {
      Text('边端多智能体编排')
        .fontSize(20).fontWeight(FontWeight.Bold).width('100%')

      Text('任务')
        .fontSize(13).fontColor('#666666').width('100%')
      TextInput({ text: this.utterance })
        .fontSize(14)
        .onChange((v: string) => { this.utterance = v; })

      Text('网络档位（决定执行位置）')
        .fontSize(13).fontColor('#666666').width('100%')
      Row({ space: 6 }) {
        ForEach(TIERS, (t: NetTier) => {
          Button(this.tierLabel(t))
            .fontSize(13)
            .layoutWeight(1)
            .backgroundColor(this.tier === t ? '#0A59F7' : '#E6E6E6')
            .fontColor(this.tier === t ? Color.White : Color.Black)
            .onClick(() => { this.tier = t; })
        }, (t: NetTier) => t)
      }.width('100%')

      Row({ space: 8 }) {
        Text('局域网边缘节点可达').fontSize(13).layoutWeight(1)
        Toggle({ type: ToggleType.Switch, isOn: this.lanOn })
          .onChange((v: boolean) => { this.lanOn = v; })
      }.width('100%')

      Text(`预算已用 ${(this.util * 100).toFixed(0)}%   ·   工具池 ${ALL_TOOLS.length} 个   ·   ${this.topKLabel()}`)
        .fontSize(13).fontColor('#666666').width('100%')
      Slider({ value: this.util * 100, min: 0, max: 95, step: 5 })
        .width('100%')
        .onChange((v: number, mode: SliderChangeMode) => { this.util = v / 100; })

      Row({ space: 6 }) {
        Button('运行一步')
          .fontSize(14).layoutWeight(2)
          .onClick(() => { this.runStep(); })
        Button(this.topKLabel())
          .fontSize(13).layoutWeight(1)
          .backgroundColor(this.topK < 0 ? '#0A59F7' : '#E6E6E6')
          .fontColor(this.topK < 0 ? Color.White : Color.Black)
          .onClick(() => { this.topK = this.nextTopK(this.topK); })
      }.width('100%')

      Row({ space: 6 }) {
        Button('A2A 试运行')
          .fontSize(13).layoutWeight(1)
          .backgroundColor('#E6E6E6').fontColor(Color.Black)
          .onClick(() => { this.runA2ADryRun(); })
        // Deliberately NOT claiming the real kit: the app no longer imports
        // @hms.ai.A2A, because that import aborts the process on any device
        // without the AgentKit HSP. This button runs the same scheduling +
        // encoding path and reports the resulting wire bytes.
        Text('协议编码路径（无传输层，不依赖 AgentKit HSP）')
          .fontSize(11).fontColor('#999999').layoutWeight(2)
      }.width('100%')

      if (this.a2aRan) {
        Text(`线缆编码  ${this.a2aForm} 形式  ·  ${this.a2aWireBytes} 字节  ·  ${this.a2aStrategy}`)
          .fontSize(12).fontColor('#0A59F7').width('100%')
      }

      if (this.ran) {
        Column({ space: 4 }) {
          Text(`执行位置  ${this.outRoute}`).fontSize(14).fontWeight(FontWeight.Bold).width('100%')
          Text(`消息形式  ${this.outForm}`).fontSize(14).width('100%')
          Text(`工具注入  ${this.outStrategy}`).fontSize(14).width('100%')
          Text(`决策理由  ${this.outReason}`).fontSize(12).fontColor('#666666').width('100%')
          Text(`选中工具  ${this.outTool}`).fontSize(12).fontColor('#666666').width('100%')
          Text(`上下文    ${this.ctxTokens} tok  （全量注入需 ${this.baseTokens} tok）`)
            .fontSize(13).width('100%')
          Text(`消息开销  ${this.msgTokens} tok`).fontSize(13).width('100%')
          Text(this.ok ? '✓ 验证通过' : '✗ 验证失败')
            .fontSize(15).fontWeight(FontWeight.Bold)
            .fontColor(this.ok ? '#1B8A2F' : '#D93026').width('100%')
        }
        .width('100%').padding(10)
        .backgroundColor('#F5F5F5').borderRadius(8)
      }

      Text('执行轨迹').fontSize(13).fontColor('#666666').width('100%')
      Scroll() {
        Column({ space: 3 }) {
          ForEach(this.trace, (item: string) => {
            Text(item).fontSize(11).width('100%').textAlign(TextAlign.Start)
          }, (item: string) => item)
        }.width('100%')
      }
      .layoutWeight(1).width('100%')
      .backgroundColor('#FAFAFA').borderRadius(6)
    }
    .width('100%').height('100%').padding(14)
    .alignItems(HorizontalAlign.Start)
  }
}
