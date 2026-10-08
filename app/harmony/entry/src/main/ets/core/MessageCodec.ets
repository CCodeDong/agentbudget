/**
 * Inter-agent message codec.
 *
 * Mirrors `Codec` in the Cangjie library, including the 40-character summary
 * budget. The truncating `summary` form is deliberately kept: the offline
 * experiments showed it is strictly dominated (it costs almost as much as the
 * structured form yet destroys the tool arguments the verifier needs), and
 * keeping it here lets the demo exhibit that failure live.
 */
import { AgentMsg, MsgForm } from '../model/Types';
import { estimateTokens } from '../core/Tokens';

export const SUMMARY_CHAR_BUDGET = 40;

/** Truncate to at most maxRunes characters without splitting a character. */
export function truncateRunes(s: string, maxRunes: number): string {
  if (maxRunes <= 0) {
    return '';
  }
  const chars = Array.from(s);
  if (chars.length <= maxRunes) {
    return s;
  }
  return chars.slice(0, maxRunes).join('');
}

export function encodeMsg(m: AgentMsg, form: MsgForm): string {
  if (form === MsgForm.Natural) {
    return `Agent ${m.from} is sending the following ${m.intent} to agent ${m.to}: ${m.payload}`;
  }
  if (form === MsgForm.Summary) {
    return `[${m.from}->${m.to}] ${m.intent}: ${truncateRunes(m.payload, SUMMARY_CHAR_BUDGET)}`;
  }
  return `${m.from}|${m.to}|${m.intent}|${m.payload}`;
}

export function msgCost(m: AgentMsg, form: MsgForm): number {
  return estimateTokens(encodeMsg(m, form));
}
