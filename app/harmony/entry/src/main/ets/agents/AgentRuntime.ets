/**
 * Three-agent orchestration runtime.
 *
 * The loop mirrors the offline harness exactly:
 *   Planner --[message rendered with the scheduled MsgForm]--> Executor
 *           --[message rendered with the scheduled MsgForm]--> Verifier
 *
 * The verifier must FIND the tool arguments inside the message it receives. That
 * is what makes the message-representation decision observable on the device: a
 * lossy representation shows up as a verification failure rather than as an
 * invisible cost. With the 40-character truncating summary the arguments do not
 * survive, so the step fails -- which is precisely the phenomenon the offline
 * experiments quantified.
 *
 * The "model" here is a deterministic lexical chooser, not an LLM. On-device LLM
 * deployment is not available on phone-targeted HarmonyOS (CANN LLM Engine is
 * 2in1-only), which is the finding that shaped this whole architecture.
 */
import { AgentMsg, Budget, LedgerState, MsgForm, NetState, StepPlan, ToolSpec } from '../model/Types';
import { encodeMsg, msgCost } from '../core/MessageCodec';
import { contextTokens, eagerSchemas, selectTopK } from '../agents/ToolRegistry';
import { planStep } from '../core/BudgetPolicy';

export interface RunResult {
  plan: StepPlan;
  success: boolean;
  toolChosen: string;
  contextTokens: number;
  baselineTokens: number;
  messageTokens: number;
  totalTokens: number;
  trace: string[];
}

export class AgentRuntime {
  /** Deterministic local stand-in for a model's tool choice. */
  private chooseTool(utterance: string, k: number): ToolSpec | null {
    const picked = selectTopK(utterance, k);
    return picked.length > 0 ? picked[0] : null;
  }

  run(
    utterance: string, difficulty: number, net: NetState,
    budget: Budget, ledger: LedgerState, topK: number
  ): RunResult {
    const trace: string[] = [];

    // ---- decision ----
    const plan = planStep(utterance, difficulty, net, budget, ledger, topK);
    trace.push(`[plan] route=${plan.route} msg=${plan.msgForm} tools=${plan.toolStrategy}`);
    trace.push(`[plan] ${plan.reason}`);

    // ---- planner ----
    const tool = this.chooseTool(utterance, 1);
    if (tool === null) {
      trace.push('[planner] no tool selected');
      return {
        plan: plan, success: false, toolChosen: '-', contextTokens: plan.toolTokens,
        baselineTokens: contextTokens(eagerSchemas()), messageTokens: 0,
        totalTokens: plan.toolTokens, trace: trace
      };
    }
    trace.push(`[planner] chose ${tool.name}`);

    // Arguments are derived from the tool's declared parameters, exactly as the
    // offline planner does.
    const argObj: Record<string, string> = {};
    for (let i = 0; i < tool.params.length; i++) {
      argObj[tool.params[i]] = `<${tool.params[i]} from task>`;
    }
    const argsJson = JSON.stringify(argObj);

    // ---- planner -> executor ----
    const m1: AgentMsg = { from: 'planner', to: 'executor', intent: 'instruction', payload: argsJson };
    const msg1 = encodeMsg(m1, plan.msgForm);
    const c1 = msgCost(m1, plan.msgForm);
    trace.push(`[msg1/${plan.msgForm}] ${msg1}`);

    // ---- executor ----
    const execOut = 'EXECUTED: ' + msg1;
    trace.push('[executor] executed the received instruction');

    // ---- executor -> verifier ----
    const m2: AgentMsg = { from: 'executor', to: 'verifier', intent: 'result', payload: execOut };
    const msg2 = encodeMsg(m2, plan.msgForm);
    const c2 = msgCost(m2, plan.msgForm);
    trace.push(`[msg2/${plan.msgForm}] ${msg2}`);

    // ---- verifier: the arguments must still be findable ----
    const missing: string[] = [];
    for (let i = 0; i < tool.params.length; i++) {
      if (msg2.indexOf(tool.params[i]) < 0) {
        missing.push(tool.params[i]);
      }
    }
    const success = missing.length === 0;
    trace.push(success
      ? '[verifier] VERDICT OK -- all arguments present'
      : `[verifier] VERDICT FAIL -- missing ${missing.join(',')}`);

    const baselineTokens = contextTokens(eagerSchemas());
    return {
      plan: plan,
      success: success,
      toolChosen: tool.name,
      contextTokens: plan.toolTokens,
      baselineTokens: baselineTokens,
      messageTokens: c1 + c2,
      totalTokens: plan.toolTokens + c1 + c2,
      trace: trace
    };
  }
}
