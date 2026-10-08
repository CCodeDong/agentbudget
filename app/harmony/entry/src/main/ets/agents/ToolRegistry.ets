/**
 * Tool registry.
 *
 * The 15 tools mirror `defaultPool()` in the Cangjie library and `TOOLS` in
 * experiments/experiment.py exactly -- 5 gold tools plus 10 distractors chosen
 * to compete lexically. Demo and experiment must describe the same catalogue,
 * otherwise the on-screen numbers mean nothing offline.
 */
import { ToolSpec } from '../model/Types';
import { estimateTokens } from '../core/Tokens';

function makeSchema(name: string, desc: string, params: string[]): string {
  const props: string[] = [];
  const req: string[] = [];
  for (let i = 0; i < params.length; i++) {
    const p = params[i];
    props.push(`"${p}":{"type":"string","description":"the ${p} argument"}`);
    req.push(`"${p}"`);
  }
  const verbose = `${desc} -- a verbose description mirroring what an MCP server really ships, ` +
    'including usage notes that inflate the injected context';
  return `{"name":"${name}","description":"${verbose}","inputSchema":{"type":"object",` +
    `"properties":{${props.join(',')}},"required":[${req.join(',')}]}}`;
}

function tool(name: string, oneLine: string, params: string[]): ToolSpec {
  return { name: name, oneLine: oneLine, params: params, fullSchema: makeSchema(name, oneLine, params) };
}

export const ALL_TOOLS: ToolSpec[] = [
  tool('calendar.create', 'create a calendar event', ['title', 'start']),
  tool('contact.lookup', 'look up a contact by name', ['name']),
  tool('file.search', 'search files by keyword', ['query', 'limit']),
  tool('notice.send', 'send a notification', ['text']),
  tool('web.search', 'search the web', ['query', 'limit']),
  // Distractors. A five-tool pool makes top-k retrieval trivially correct and
  // hides the cost side of context compression entirely.
  tool('sms.send', 'send a text message', ['to', 'body']),
  tool('email.compose', 'compose an email', ['to', 'subject', 'body']),
  tool('music.play', 'play music by name', ['track']),
  tool('map.navigate', 'navigate to a destination', ['place']),
  tool('timer.set', 'set a countdown timer', ['minutes']),
  tool('alarm.create', 'create an alarm', ['time']),
  tool('weather.query', 'query the weather forecast', ['city']),
  tool('translate.text', 'translate text', ['text', 'target']),
  tool('clipboard.read', 'read the clipboard', []),
  tool('battery.status', 'report battery status', [])
];

const STOPWORDS: string[] = [
  'the', 'a', 'an', 'and', 'for', 'from', 'with', 'about', 'that', 'this',
  'my', 'me', 'to', 'of', 'in', 'on', 'at', 'is', 'it', 'up', 'get',
  'look', 'please', 'next', 'last'
];

function isStopword(w: string): boolean {
  return STOPWORDS.indexOf(w) >= 0;
}

/**
 * Query normalisation: lower-case, stopword filtering, and DEDUPLICATION.
 *
 * The deduplication is not cosmetic. Without it, a repeated stopword inflates a
 * tool's score: in "search my contact list for the person from the vendor" the
 * word "the" occurs twice, so every tool whose description merely contains "the"
 * collected +6 and outranked the correct `contact.lookup`. That single artefact
 * accounted for the ENTIRE accuracy loss of the compressed arm in the offline
 * experiments, which is why this is normalised before anything else.
 */
export function normalizeQueryWords(query: string): string[] {
  const lower = query.toLowerCase();
  const raw = lower.split(' ');
  const seen: string[] = [];
  const out: string[] = [];
  for (let i = 0; i < raw.length; i++) {
    const w = raw[i];
    if (w.length >= 2 && !isStopword(w) && seen.indexOf(w) < 0) {
      seen.push(w);
      out.push(w);
    }
  }
  return out;
}

function scoreOne(t: ToolSpec, qLower: string, words: string[]): number {
  let s = 0;
  if (qLower.indexOf(t.name.toLowerCase()) >= 0) {
    s += 10;
  }
  const desc = t.oneLine.toLowerCase();
  let params = '';
  for (let i = 0; i < t.params.length; i++) {
    params += ' ' + t.params[i].toLowerCase();
  }
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    if (desc.indexOf(w) >= 0) {
      s += 3;
    }
    if (params.indexOf(w) >= 0) {
      s += 1;
    }
  }
  return s;
}

/** Relevance score of every tool, in catalogue order. */
export function scoreAll(query: string): number[] {
  const qLower = query.toLowerCase();
  const words = normalizeQueryWords(query);
  const scores: number[] = [];
  for (let i = 0; i < ALL_TOOLS.length; i++) {
    scores.push(scoreOne(ALL_TOOLS[i], qLower, words));
  }
  return scores;
}

/**
 * Threshold as a percentage of the top score. Must match ALPHA_PCT in
 * the Cangjie library's `adaptiveKByScore`.
 */
export const ADAPTIVE_ALPHA_PCT: number = 50;

/**
 * Choose k from the SHAPE of the retrieval score distribution.
 *
 * This mirrors `adaptiveKByScore()` in the Cangjie library, and the reason is
 * not stylistic. `docs/13` measured that binding k to the remaining token budget
 * is dominated by a fixed k at every operating point: budget says nothing about
 * whether retrieval is easy. `docs/14` showed that using the retrieval score
 * distribution instead dominates every fixed k.
 *
 * Keeping two different rules in the library and the app would make the demo
 * and the experiments describe two different systems while claiming to describe
 * one -- which is exactly what this file's header warns against. The ceiling
 * formula below is written the same way as the library's so the correspondence
 * is checkable by eye rather than inferred.
 *
 * If no tool scores above zero there is no lexical signal at all, so a fixed
 * value is used rather than pretending to decide.
 */
export function adaptiveK(query: string): number {
  const scores = scoreAll(query);
  if (scores.length === 0) {
    return 1;
  }
  let top = 0;
  for (let i = 0; i < scores.length; i++) {
    if (scores[i] > top) {
      top = scores[i];
    }
  }
  if (top <= 0) {
    return 5;
  }
  // Ceiling, matching (top * alpha + 99) / 100 in the library. Truncation here
  // would silently disagree with the library at the same nominal alpha.
  let threshold = Math.floor((top * ADAPTIVE_ALPHA_PCT + 99) / 100);
  if (threshold < 1) {
    threshold = 1;
  }
  let k = 0;
  for (let i = 0; i < scores.length; i++) {
    if (scores[i] >= threshold) {
      k++;
    }
  }
  if (k < 1) {
    k = 1;
  }
  if (k > 8) {
    k = 8;
  }
  if (k > ALL_TOOLS.length) {
    k = ALL_TOOLS.length;
  }
  return k;
}

/**
 * Choose k from the remaining token budget.
 *
 * This is the policy the paper measured to be DOMINATED by a fixed k at every
 * operating point (`docs/13`): the budget says nothing about whether retrieval
 * is easy, so it overspends when there is headroom and underspends when there
 * is not. It is kept -- and reachable from the demo -- so that a negative result
 * can be reproduced interactively rather than only asserted.
 */
export function adaptiveKByBudget(eagerTokens: number, toolCount: number, tokensLeft: number): number {
  if (toolCount <= 0) {
    return 1;
  }
  const avg = Math.floor(eagerTokens / toolCount);
  if (avg <= 0) {
    return 1;
  }
  let k = Math.floor(Math.floor(tokensLeft / 2) / avg);
  if (k < 1) {
    k = 1;
  }
  if (k > 8) {
    k = 8;
  }
  if (k > toolCount) {
    k = toolCount;
  }
  return k;
}

/** Top-k tools by lexical relevance, ties broken by catalogue order. */
export function selectTopK(query: string, k: number): ToolSpec[] {
  const qLower = query.toLowerCase();
  const words = normalizeQueryWords(query);
  const scores: number[] = [];
  for (let i = 0; i < ALL_TOOLS.length; i++) {
    scores.push(scoreOne(ALL_TOOLS[i], qLower, words));
  }
  const used: boolean[] = [];
  for (let i = 0; i < ALL_TOOLS.length; i++) {
    used.push(false);
  }
  const picked: ToolSpec[] = [];
  let taken = 0;
  while (taken < k && taken < ALL_TOOLS.length) {
    let best = -1;
    let bestScore = -1;
    for (let j = 0; j < ALL_TOOLS.length; j++) {
      if (!used[j] && scores[j] > bestScore) {
        bestScore = scores[j];
        best = j;
      }
    }
    if (best < 0) {
      break;
    }
    used[best] = true;
    picked.push(ALL_TOOLS[best]);
    taken++;
  }
  return picked;
}

/** Compact summary pool: names, one-line descriptions and parameter names only. */
export function summaryPool(): string {
  const parts: string[] = [];
  for (let i = 0; i < ALL_TOOLS.length; i++) {
    const t = ALL_TOOLS[i];
    parts.push(`- ${t.name}: ${t.oneLine} | params: ${t.params.join(' ')}`);
  }
  return parts.join('\n');
}

/** Full schemas for every tool: the MCP default that the project attacks. */
export function eagerSchemas(): string {
  const parts: string[] = [];
  for (let i = 0; i < ALL_TOOLS.length; i++) {
    parts.push('FULL_SCHEMA: ' + ALL_TOOLS[i].fullSchema);
  }
  return parts.join('\n');
}

/** Two-stage load: summary pool plus full schemas only for the selected tools. */
export function stagedSchemas(query: string, k: number): string {
  const parts: string[] = [summaryPool(), ''];
  const picked = selectTopK(query, k);
  for (let i = 0; i < picked.length; i++) {
    parts.push('FULL_SCHEMA: ' + picked[i].fullSchema);
  }
  return parts.join('\n');
}

export function contextTokens(text: string): number {
  return estimateTokens(text);
}
