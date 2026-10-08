/**
 * Network state probe.
 *
 * The three-tier placement decision needs the wide-area quality and whether an
 * edge node is reachable on the LAN. HarmonyOS exposes the former through
 * NetworkKit; the latter has no dedicated API, so it is inferred from the
 * presence of a non-loopback local address and confirmed by the user.
 *
 * Every call is defensive: a probe failure must degrade to a sane default rather
 * than crash the orchestration layer, because the plan is still useful.
 */
import { connection } from '@kit.NetworkKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { NetState, NetTier } from '../model/Types';

export function probeNetwork(lanAvailable: boolean): NetState {
  let tier: NetTier = NetTier.Wifi;
  let rttMs = 30;
  let metered = false;
  try {
    const net = connection.getDefaultNetSync();
    if (!net || net.netId === 0) {
      tier = NetTier.Offline;
      rttMs = 0;
    } else {
      const caps = connection.getNetCapabilitiesSync(net);
      const bearers = caps.bearerTypes;
      if (bearers && bearers.length > 0) {
        // BearerType: 0=CELLULAR, 1=WIFI, 2=ETHERNET, 3=VPN, 4=BLUETOOTH
        const b = bearers[0];
        if (b === 0) {
          tier = NetTier.Cellular;
          metered = true;
          rttMs = 120;
        } else if (b === 1 || b === 2) {
          tier = NetTier.Wifi;
          rttMs = 25;
        } else {
          tier = NetTier.Weak;
          rttMs = 900;
        }
      }
    }
  } catch (err) {
    // Any failure of the probe is not fatal: the plan is still useful, so fall
    // back to a conservative state (no usable WAN, LAN assumed reachable).
    const msg = err instanceof Error ? err.message : String(err);
    hilog.warn(0x0000, 'agentbudget', 'network probe failed: %{public}s', msg);
    tier = NetTier.Weak;
    rttMs = 900;
  }
  return { tier: tier, rttMs: rttMs, metered: metered, lanAvailable: lanAvailable };
}
