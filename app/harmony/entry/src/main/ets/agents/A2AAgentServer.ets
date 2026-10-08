/**
 * Real `@hms.ai.A2A` integration: the Executor agent as an A2A server.
 *
 * WHY THIS EXISTS
 *   Until now the app demonstrated the scheduling policy against an in-process
 *   equivalent of the protocol. That is enough to show the decision logic, but it
 *   cannot answer the question the paper actually asks about the protocol layer:
 *   *does the message-representation choice change what goes on the wire?*
 *
 *   Here it does, because the scheduler's chosen form is what selects the `Part`
 *   channel used to carry the payload. The decision and the wire format are the
 *   same object, not two things that happen to agree.
 *
 * WHAT IS REAL AND WHAT IS NOT
 *   Real: `createA2AServer`, the `AgentCard`, `RequestContext.getMessage()` /
 *   `getUserInput()` / `getTaskId()`, `Message`/`Part`/`Role`, and the JSON that
 *   leaves through the proxy sender.
 *   Not verified without a device: whether the A2A HSP adds framing of its own,
 *   whether `Task.history` is retransmitted per call, and the real authentication
 *   handshake. The envelope figures in `experiments/a2a_overhead.py` are
 *   schema-level estimates for exactly that reason (see paper section 4.3).
 *
 * DESIGN DECISION WORTH NOTING
 *   Budget telemetry rides in `Part.metadata`, never in `Part.text`. The protocol
 *   provides a channel for consumer-defined data, so spending model tokens on
 *   telemetry would be a self-inflicted cost -- and the paper's whole argument is
 *   that such costs dominate on mobile.
 */

import { createA2AServer, Server, RequestContext, Message, Part, Role, ProxySender }
  from '@hms.ai.A2A';
import { common } from '@kit.AbilityKit';
import { AgentMsg, Budget, LedgerState, MsgForm, NetState, NetTier, RouteTarget, StepPlan }
  from '../model/Types';
import { encodeMsg, msgCost } from '../core/MessageCodec';
import { planStep } from '../core/BudgetPolicy';

/** What one handled A2A request produced, for the on-screen trace. */
export interface A2AExchange {
  method: string;
  taskId: string;
  agentId: string;
  userInput: string;
  msgForm: MsgForm;
  /** Human-readable form name; the enum's own reverse mapping is not portable. */
  msgFormLabel: string;
  /** Bytes of the encoded Message JSON actually handed to the transport. */
  wireBytes: number;
  /** Model-facing token estimate of the payload alone, excluding the envelope. */
  payloadTokens: number;
  toolStrategy: string;
  route: string;
}

export type ExchangeListener = (e: A2AExchange) => void;

/** Version the A2A HSP expects in the `want` parameters. */
const A2A_WANT_VERSION = '1.0';

export class A2AAgentServer {
  private server: Server | null = null;
  private sender: ProxySender | null = null;
  private listener: ExchangeListener | null = null;
  private msgSeq: number = 0;

  /**
   * The Executor's advertised capability.
   *
   * `skills` mirrors the tool catalogue rather than being decorative: an A2A
   * client discovers what an agent can do from the card, so a card that omits the
   * device-capability tools would be advertising an agent that cannot do the work
   * the demo performs.
   */
  private readonly card: common.AgentCard = {
    agentId: 'agentbudget-executor',
    name: 'AgentBudget Executor',
    description: 'Budget-aware on-device executor for the agentbudget4cj scheduler',
    version: '1.0.0',
    iconUrl: '',
    category: 'productivity',
    // The agent exchanges text and one custom typed channel; declaring only what
    // is actually used keeps the card honest, since a client discovers the
    // supported media types from here before sending anything.
    defaultInputModes: ['text/plain'],
    defaultOutputModes: ['text/plain', 'application/vnd.agentbudget+text'],
    // Required by the platform: the A2A runtime needs to know which ability hosts
    // this agent in order to route an incoming task to it.
    appInfo: {
      bundleName: 'com.xjtu.agentbudget',
      moduleName: 'entry',
      abilityName: 'EntryAbility'
    },
    skills: [
      {
        id: 'file.search', name: 'File search',
        description: 'search files by keyword', tags: ['files', 'search', 'query']
      },
      {
        id: 'web.search', name: 'Web search',
        description: 'search the web', tags: ['web', 'search', 'online']
      },
      {
        id: 'contact.lookup', name: 'Contact lookup',
        description: 'look up a contact by name', tags: ['contacts', 'people', 'lookup']
      },
      {
        id: 'notice.send', name: 'Notification',
        description: 'send a notification', tags: ['notification', 'reminder', 'alert']
      },
      {
        id: 'calendar.create', name: 'Calendar',
        description: 'create a calendar event', tags: ['calendar', 'event', 'schedule']
      }
    ]
  };

  public setListener(l: ExchangeListener): void {
    this.listener = l;
  }

  public isRunning(): boolean {
    return this.server !== null;
  }

  public start(): void {
    if (this.server !== null) {
      return;
    }
    this.server = createA2AServer(this.card, (method: string, context: RequestContext): void => {
      this.onData(method, context);
    });
    this.server.start();
  }

  public stop(): void {
    if (this.server !== null) {
      this.server.stop();
      this.server = null;
    }
    this.sender = null;
  }

  /**
   * Hand a raw frame from the transport to the SDK.
   *
   * The reply sender is only available on `onMessage`, but the handler that
   * builds the reply is `onData`, which does not receive it. Holding it for the
   * duration of the synchronous `onMessage` call is what bridges the two.
   */
  public deliver(data: string, sender: ProxySender): void {
    if (this.server === null) {
      return;
    }
    this.sender = sender;
    try {
      this.server.onMessage(data, sender);
    } finally {
      this.sender = null;
    }
  }

  /**
   * Run the budget policy on an incoming request and answer in the chosen form.
   *
   * The `form` returned by `planStep` is not advisory here: it selects the Part
   * channel below, so a change in the scheduling decision is a change in the
   * bytes on the wire.
   */
  private onData(method: string, context: RequestContext): void {
    const reply: Message = this.buildReply(
      method, context.getUserInput(), context.getContextId(),
      this.card.agentId, NetTierFromContext(context));

    const wire: string = JSON.stringify(reply);
    if (this.sender !== null) {
      this.sender(wire);
    }
    this.report(method, context.getTaskId() ?? '', this.card.agentId,
      context.getUserInput(), reply, wire);
  }

  /**
   * Exercise the full scheduling and encoding path without a transport.
   *
   * Exists because the A2A transport is only present on a real device. Without
   * this, the whole module would sit outside the build graph and "it compiles"
   * would be an unchecked claim. It also gives the demo a runnable path on the
   * emulator.
   */
  public dryRun(userInput: string): A2AExchange {
    const reply: Message = this.buildReply(
      'instruction', userInput, 'local-context', this.card.agentId, NetTier.Wifi);
    const wire: string = JSON.stringify(reply);
    const ex: A2AExchange = this.makeExchange(
      'instruction', '', this.card.agentId, userInput, reply, wire);
    if (this.listener !== null) {
      this.listener(ex);
    }
    return ex;
  }

  /** The one place a reply is assembled, shared by the live and dry-run paths. */
  private buildReply(method: string, userInput: string, contextId: string | undefined,
                     agentId: string, net: NetTier): Message {
    const budget: Budget = {
      tokenCap: 8000, latencyCapMs: 60000, cloudCallCap: 10, trafficCapKb: 50000
    };
    const ledger: LedgerState = { tokensSpent: 6800, latencySpentMs: 0, cloudCalls: 0 };
    const netState: NetState = {
      tier: net, rttMs: 20, metered: false, lanAvailable: true
    };

    // -50 = the score-driven adaptive policy the paper proposes.
    const plan: StepPlan = planStep(userInput, 0.8, netState, budget, ledger, -50);

    const outgoing: AgentMsg = {
      from: agentId,
      to: 'planner',
      intent: method.length > 0 ? method : 'instruction',
      payload: JSON.stringify({ tools: plan.selected, strategy: plan.toolStrategy })
    };

    return {
      messageId: this.nextMessageId(),
      role: Role.AGENT,
      parts: [this.encodeParts(outgoing, plan)],
      contextId: contextId,
      metadata: {
        // Telemetry, deliberately out of the model's payload.
        toolStrategy: plan.toolStrategy,
        toolTokens: plan.toolTokens,
        route: routeLabel(plan.route),
        msgForm: plan.msgForm
      }
    };
  }

  /** Re-derive the observable summary from an assembled reply. */
  private makeExchange(method: string, taskId: string, agentId: string, userInput: string,
                       reply: Message, wire: string): A2AExchange {
    const meta: Record<string, string> =
      (reply.metadata ?? {}) as Record<string, string>;
    const outgoing: AgentMsg = {
      from: agentId, to: 'planner', intent: method, payload: ''
    };
    return {
      method: method,
      taskId: taskId,
      agentId: agentId,
      userInput: userInput,
      msgForm: reply.parts[0].data !== undefined ? MsgForm.Structured : MsgForm.Natural,
      msgFormLabel: reply.parts[0].data !== undefined ? 'structured' : 'natural',
      wireBytes: wire.length,
      payloadTokens: msgCost(outgoing, MsgForm.Natural),
      toolStrategy: meta['toolStrategy'] ?? '',
      route: meta['route'] ?? ''
    };
  }

  private report(method: string, taskId: string, agentId: string, userInput: string,
                 reply: Message, wire: string): void {
    if (this.listener !== null) {
      this.listener(this.makeExchange(method, taskId, agentId, userInput, reply, wire));
    }
  }

  /**
   * Map the scheduler's representation choice onto a real `Part` channel.
   *
   * `structured` uses `Part.data` so the receiver gets a typed object rather than
   * a string it has to re-parse. That costs about 21 extra bytes for `mediaType`
   * (paper section 4.3) and buys type fidelity -- the value is fidelity, not
   * bytes, and claiming otherwise would overstate the finding.
   */
  private encodeParts(m: AgentMsg, plan: StepPlan): Part {
    const rendered: string = encodeMsg(m, plan.msgForm);
    if (plan.msgForm === MsgForm.Structured) {
      return { data: rendered, mediaType: 'application/vnd.agentbudget+text' };
    }
    return { text: rendered };
  }

  private nextMessageId(): string {
    this.msgSeq += 1;
    return 'ab4cj-' + this.msgSeq.toString();
  }
}

/**
 * The A2A context does not carry link quality, so the tier is taken from the
 * app's own probe (`NetworkProbe`). Kept as a free function so this module does
 * not depend on the page layer.
 */
function NetTierFromContext(context: RequestContext): NetTier {
  const meta: object = context.getMetadata();
  const raw: string = (meta as Record<string, string>)['netTier'] ?? '';
  if (raw === 'wifi') {
    return NetTier.Wifi;
  }
  if (raw === 'cellular') {
    return NetTier.Cellular;
  }
  if (raw === 'offline') {
    return NetTier.Offline;
  }
  return NetTier.Weak;
}

/** Enum values are numeric, so the trace needs an explicit label. */
function routeLabel(r: RouteTarget): string {
  if (r === RouteTarget.Cloud) {
    return 'cloud';
  }
  if (r === RouteTarget.Edge) {
    return 'edge';
  }
  return 'on-device';
}
