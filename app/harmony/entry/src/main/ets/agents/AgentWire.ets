/**
 * A2A wire encoding — the message shape that leaves the app.
 *
 * WHY THIS FILE EXISTS (and why it no longer imports `@hms.ai.A2A`)
 *   The app previously imported `@hms.ai.A2A` directly. That import is resolved
 *   at MODULE LOAD time, and on a device without the AgentKit HSP the ArkTS
 *   runtime aborts the whole process before any application code runs:
 *
 *     LastFatalMessage: [LoadJSPandaFile] load hsp failed,
 *       hsp name: com.huawei.hmsapp.hiai.hsp/agentKitHsp,
 *       errorMsg: Get shared HspPath failed
 *     Reason: Signal:SIGABRT ... SourceTextModule::Instantiate
 *
 *   Measured on the Pura 90 Pro emulator (phone, API 26) and reproduced on the
 *   MateBook Pro (2in1, API 23) — neither carries HMS Core / AgentKit.
 *
 *   So this file encodes the message using the SAME field shape the protocol
 *   defines (messageId / role / parts / metadata, and Part's text|data|mediaType)
 *   without importing the kit. The real server binding is kept in
 *   `A2AAgentServer.ets`, which is deliberately NOT imported by the app and is
 *   therefore not part of the load graph.
 *
 *   TRADE-OFF, stated plainly: the real binding is no longer type-checked by the
 *   app build. It WAS compiled and signed in an earlier revision (the HAP grew by
 *   25.7 KB when it was added), but shipping it means the app cannot start on any
 *   device we can actually test. A demo that runs without the protocol layer beats
 *   a protocol layer that prevents the demo from running at all.
 */

import { AgentMsg, Budget, LedgerState, MsgForm, NetState, NetTier, RouteTarget, StepPlan }
  from '../model/Types';
import { encodeMsg, msgCost } from '../core/MessageCodec';
import { planStep } from '../core/BudgetPolicy';

/** Protocol role values. Mirrors `Role` in `@hms.ai.A2A` (AGENT = 0, USER = 1). */
const ROLE_AGENT: number = 0;

/** One `Part` of a message. Channel presence is what the form choice decides. */
export interface WirePart {
  text?: string;
  data?: string;
  mediaType?: string;
}

/**
 * Budget telemetry carried alongside the payload.
 *
 * Declared as a named interface rather than `Record<string, string>`: ArkTS
 * rejects object literals for index-signature types (arkts-no-untyped-obj-literals),
 * and it also rejects `any`. A named interface is the only form that both
 * compiles and keeps the field set explicit.
 */
export interface WireMetadata {
  toolStrategy: string;
  toolTokens: string;
  route: string;
  msgForm: string;
}

export interface WireMessage {
  messageId: string;
  role: number;
  parts: WirePart[];
  contextId?: string;
  metadata?: WireMetadata;
}

/** What one handled request produced, for the on-screen trace. */
export interface WireExchange {
  method: string;
  agentId: string;
  userInput: string;
  msgForm: MsgForm;
  /** Human-readable form name; enum reverse mapping is not portable. */
  msgFormLabel: string;
  /** Bytes of the encoded Message JSON. */
  wireBytes: number;
  /** Model-facing token estimate of the payload alone, excluding the envelope. */
  payloadTokens: number;
  toolStrategy: string;
  route: string;
}

export class AgentWire {
  private msgSeq: number = 0;

  /**
   * Run the budget policy and assemble the reply in the form the scheduler chose.
   *
   * The chosen form is NOT advisory: it selects the `Part` channel below, so a
   * change in the scheduling decision is a change in the bytes on the wire.
   */
  public build(userInput: string, agentId: string, net: NetTier, method: string,
               contextId?: string): WireMessage {
    const budget: Budget = {
      tokenCap: 8000, latencyCapMs: 60000, cloudCallCap: 10, trafficCapKb: 50000
    };
    const ledger: LedgerState = { tokensSpent: 6800, latencySpentMs: 0, cloudCalls: 0 };
    const netState: NetState = { tier: net, rttMs: 20, metered: false, lanAvailable: true };

    // -50 = the score-driven adaptive policy the paper proposes.
    const plan: StepPlan = planStep(userInput, 0.8, netState, budget, ledger, -50);

    const outgoing: AgentMsg = {
      from: agentId,
      to: 'planner',
      intent: method.length > 0 ? method : 'instruction',
      payload: JSON.stringify({ tools: plan.selected, strategy: plan.toolStrategy })
    };

    this.msgSeq += 1;
    return {
      messageId: 'ab4cj-' + this.msgSeq.toString(),
      role: ROLE_AGENT,
      parts: [this.encodePart(outgoing, plan)],
      contextId: contextId,
      metadata: {
        // Telemetry rides in metadata, deliberately out of the model's payload.
        toolStrategy: plan.toolStrategy,
        toolTokens: plan.toolTokens.toString(),
        route: routeLabel(plan.route),
        msgForm: msgFormName(plan.msgForm)
      }
    };
  }

  /**
   * Map the representation choice onto a real `Part` channel.
   *
   * `structured` uses `Part.data` so the receiver gets a typed value rather than
   * a string to re-parse. That costs about 21 extra bytes for `mediaType`
   * (paper section 4.3) and buys type fidelity -- the value is fidelity, not
   * bytes, and claiming otherwise would overstate the finding.
   */
  private encodePart(m: AgentMsg, plan: StepPlan): WirePart {
    const rendered: string = encodeMsg(m, plan.msgForm);
    if (plan.msgForm === MsgForm.Structured) {
      return { data: rendered, mediaType: 'application/vnd.agentbudget+text' };
    }
    return { text: rendered };
  }

  /** Run the full path locally and report what would go on the wire. */
  public dryRun(userInput: string, agentId: string, net: NetTier): WireExchange {
    const msg: WireMessage = this.build(userInput, agentId, net, 'instruction');
    const wire: string = JSON.stringify(msg);
    const meta: WireMetadata | undefined = msg.metadata;
    const outgoing: AgentMsg = { from: agentId, to: 'planner', intent: 'instruction', payload: '' };
    return {
      method: 'instruction',
      agentId: agentId,
      userInput: userInput,
      msgForm: msg.parts[0].data !== undefined ? MsgForm.Structured : MsgForm.Natural,
      msgFormLabel: msg.parts[0].data !== undefined ? 'structured' : 'natural',
      wireBytes: wire.length,
      payloadTokens: msgCost(outgoing, MsgForm.Natural),
      toolStrategy: meta !== undefined ? meta.toolStrategy : '',
      route: meta !== undefined ? meta.route : ''
    };
  }
}

/** Enum values are numeric, so the trace needs explicit labels. */
export function routeLabel(r: RouteTarget): string {
  if (r === RouteTarget.Cloud) {
    return 'cloud';
  }
  if (r === RouteTarget.Edge) {
    return 'edge';
  }
  return 'on-device';
}

export function msgFormName(f: MsgForm): string {
  if (f === MsgForm.Structured) {
    return 'structured';
  }
  if (f === MsgForm.Summary) {
    return 'summary';
  }
  return 'natural';
}
