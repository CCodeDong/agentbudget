/**
 * Network-aware placement across three tiers (research gap: where to execute).
 *
 * Placement reality on HarmonyOS: the phone cannot host its own LLM
 * (`SystemCapability.AI.CANN.LLMEngine` is 2in1-only, verified in the local SDK
 * metadata), but it *can* host the agent orchestration (`@hms.ai.A2A`,
 * `AgentExtensionAbility`, `AgentCard` are all phone-available and require no
 * `ohos.permission.*`). So the interesting decision is not "on-device vs cloud"
 * but a three-way choice over an *edge* node on the local network.
 *
 * The property that makes an edge tier worth modelling: the LAN usually
 * survives wide-area degradation, so it is the only remote option that still
 * works on a weak or dead cellular link.
 */
package agentbudget4cj

import std.deriving.*

/** Coarse quality class of the wide-area link. */
@Derive[Equatable, ToString]
public enum NetTier {
    | Wifi
    | Cellular
    | Weak
    | Offline
}

/** Observable network state at decision time. */
public struct NetState {
    public let tier: NetTier
    public let rttMs: Int64
    public let metered: Bool
    /** Whether an edge inference node is reachable on the local network. */
    public let lanAvailable: Bool

    public init(tier: NetTier, rttMs: Int64, metered: Bool, lanAvailable: Bool) {
        this.tier = tier
        this.rttMs = rttMs
        this.metered = metered
        this.lanAvailable = lanAvailable
    }

    /** True when a wide-area round trip is plausibly worth its cost. */
    public func cloudViable(): Bool {
        match (this.tier) {
            case Offline => false
            case Weak => false
            case Wifi => true
            case Cellular => this.rttMs <= 400
        }
    }

    /**
     * The edge node is on the local network, so its viability does not depend
     * on the wide-area tier at all.
     */
    public func edgeViable(): Bool {
        return this.lanAvailable
    }

    public func label(): String {
        match (this.tier) {
            case Wifi => "wifi"
            case Cellular => "cellular"
            case Weak => "weak"
            case Offline => "offline"
        }
    }
}

/** Where a step should execute. */
@Derive[Equatable, ToString]
public enum RouteTarget {
    | OnDevice
    | Edge
    | Cloud
}

/** A routing decision plus a human-auditable reason. */
public struct RouteDecision {
    public let target: RouteTarget
    public let reason: String

    public init(target: RouteTarget, reason: String) {
        this.target = target
        this.reason = reason
    }

    public func label(): String {
        match (this.target) {
            case OnDevice => "on-device"
            case Edge => "edge"
            case Cloud => "cloud"
        }
    }
}
