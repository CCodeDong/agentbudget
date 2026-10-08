/**
 * Domain types for the on-device multi-agent orchestration demo.
 *
 * These mirror the Cangjie library `agentbudget4cj` deliberately: the ArkTS side
 * is the *orchestration* layer, and the decision vocabulary must match the
 * research artifact exactly or the demo and the experiments describe different
 * systems.
 */

/** Where a step should execute. Mirrors RouteTarget in the Cangjie library. */
export enum RouteTarget {
  OnDevice = 'on-device',
  Edge = 'edge',
  Cloud = 'cloud'
}

/** Inter-agent message representation. Mirrors MsgForm in the Cangjie library. */
export enum MsgForm {
  Natural = 'natural',
  Summary = 'summary',
  Structured = 'structured'
}

/** Wide-area link quality. */
export enum NetTier {
  Wifi = 'wifi',
  Cellular = 'cellular',
  Weak = 'weak',
  Offline = 'offline'
}

export interface NetState {
  tier: NetTier;
  rttMs: number;
  metered: boolean;
  /** Whether an edge inference node is reachable on the local network. */
  lanAvailable: boolean;
}

export interface Budget {
  tokenCap: number;
  latencyCapMs: number;
  cloudCallCap: number;
  trafficCapKb: number;
}

export interface LedgerState {
  tokensSpent: number;
  latencySpentMs: number;
  cloudCalls: number;
}

export interface ToolSpec {
  name: string;
  oneLine: string;
  params: string[];
  fullSchema: string;
}

export interface StepPlan {
  route: RouteTarget;
  msgForm: MsgForm;
  toolStrategy: string;
  toolTokens: number;
  selected: string[];
  reason: string;
}

export interface AgentMsg {
  from: string;
  to: string;
  intent: string;
  payload: string;
}

/** One recorded step, for the on-screen trace. */
export interface TraceEntry {
  agent: string;
  detail: string;
}
