/**
 * Token estimator.
 *
 * Mirrors `estimateTokens()` in the Cangjie library: ASCII costs roughly a
 * quarter of a token per byte while non-ASCII (CJK) costs roughly one token per
 * character. Keeping the two implementations identical in behaviour is what
 * makes the on-device UI numbers comparable with the offline experiments.
 */
export function estimateTokens(s: string): number {
  let ascii = 0;
  let wide = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c < 128) {
      ascii++;
    } else {
      wide++;
    }
  }
  return Math.floor(ascii / 4) + Math.floor((wide + 2) / 3);
}
