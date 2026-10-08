/**
 * Budget-aware joint policy.
 *
 * IMPORTANT -- READ BEFORE CITING ANY BEHAVIOUR FROM THIS FILE
 *   The canonical implementation of this policy is the Cangjie library
 *   `projects/agentbudget4cj`, which is the artifact the research measures.
 *   This ArkTS version exists so the mobile application is self-contained and
 *   demonstrable before the Cangjie <-> ArkTS bridge is wired. It is a faithful
 *   port of the same decision ladder, but ANY measurement must come from the
 *   Cangjie side; this one must never be used to produce reported numbers.
 *
 *   The reason is not purity for its own sake: if the app decided differently
 *   from the library, the demo and the experiments would describe two different
 *   systems while claiming to describe one.
 */
import {
  Budget, LedgerState, MsgForm, NetState, NetTier, RouteTarget, StepPlan, ToolSpec
} from '../model/Types';
import {
  contextTokens, eagerSchemas, selectTopK, stagedSchemas, adaptiveK, adaptiveKByBudget, ALL_TOOLS
} from '../agents/ToolRegistry';

export function tokenUtilization(b: Budget, l: LedgerState): number {
  if (b.tokenCap <= 0) {
    return 1.0;
  }
  const u = l.tokensSpent / b.tokenCap;
  return u < 0 ? 0 : (u > 1 ? 1 : u);
}

export function cloudViable(n: NetState): boolean {
  if (n.tier === NetTier.Offline || n.tier === NetTier.Weak) {
    return false;
  }
  if (n.tier === NetTier.Wifi) {
    return true;
  }
  return n.rttMs <= 400;
}

/** The edge node is on the LAN, so its viability is independent of the WAN. */
export function edgeViable(n: NetState): boolean {
  return n.lanAvailable;
}

/**
 * Jointly decide tool injection, message representation and placement.
 *
 * Note the deliberate choice at u < 0.5: the scheduler keeps the eager
 * all-schemas context when headroom looks ample. Compression is not
 * unconditionally good -- it should be paid for only when needed.
 */
export function planStep(
  query: string, difficulty: number, net: NetState, budget: Budget, ledger: LedgerState, topK: number
): StepPlan {
  const u = tokenUtilization(budget, ledger);
  const tokensLeft = budget.tokenCap - ledger.tokensSpent;

  const eager = eagerSchemas();
  const eagerTokens = contextTokens(eager);

  // ---- 0. how many tools get a full schema ----
  // Selector semantics are identical to the Cangjie CLI, so the app can
  // reproduce every arm of the paper's comparison:
  //   k < 0  score-driven adaptive, |k| = threshold percent of the top score
  //          (the proposed method; the CLI default is -50)
  //   k = 0  BUDGET-driven adaptive -- a baseline the paper measured to be
  //          dominated by a fixed k, kept so the failure can be demonstrated
  //   k > 0  pinned to that many full schemas (baselines)
  let k = topK;
  if (k < 0) {
    k = adaptiveK(query);
  } else if (k === 0) {
    k = adaptiveKByBudget(eagerTokens, ALL_TOOLS.length, tokensLeft);
  }

  // ---- 1. tool injection ----
  let toolContext: string;
  let toolStrategy: string;
  if (u < 0.5 && eagerTokens * 3 <= tokensLeft) {
    toolContext = eager;
    toolStrategy = 'eager';
  } else {
    toolContext = stagedSchemas(query, k);
    toolStrategy = `two-stage-top${k}`;
  }
  const toolTokens = contextTokens(toolContext);

  // ---- 2. message representation ----
  let form = MsgForm.Natural;
  if (u >= 0.6) {
    form = MsgForm.Structured;
  } else if (u >= 0.3) {
    form = MsgForm.Summary;
  }

  // ---- 3. placement across three tiers ----
  // Priority: cloud only for genuinely hard steps with headroom left; otherwise
  // fall to the edge node, which stays reachable on the LAN even when the
  // wide-area link is weak or down.
  let route = RouteTarget.OnDevice;
  let reason = 'no remote tier viable';
  const cloudCallsLeft = budget.cloudCallCap - ledger.cloudCalls;
  if (cloudViable(net) && cloudCallsLeft > 0 && difficulty >= 0.6 && u < 0.8) {
    route = RouteTarget.Cloud;
    reason = 'hard step, wide-area viable, headroom left';
  } else if (edgeViable(net)) {
    route = RouteTarget.Edge;
    reason = cloudViable(net)
      ? 'edge reachable on LAN'
      : `wide-area ${net.tier} unusable; LAN survives`;
  }

  const selected: ToolSpec[] = (toolStrategy === 'eager')
    ? []
    : selectTopK(query, k);
  const names: string[] = [];
  for (let i = 0; i < selected.length; i++) {
    names.push(selected[i].name);
  }

  return {
    route: route,
    msgForm: form,
    toolStrategy: toolStrategy,
    toolTokens: toolTokens,
    selected: names,
    reason: reason
  };
}
