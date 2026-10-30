//! Groundwork for direct peer connections to a hosted realm, behind `p2p_hosting`.
//!
//! Today every player reaches a hosted realm through the relay, and that stays the default and the fallback:
//! it keeps the host's home address hidden and works behind any router. A direct connection would skip the
//! relay, but it shows each side the other's IP address, so it happens only when ALL of these hold:
//! * the `p2p_hosting` flag is on (site or this PC);
//! * the host chose "allow direct connections" for the realm (the realm's `direct` offer);
//! * the player chose it too (per connection, in the launcher);
//! * both NAT checks say a direct path can work (`nat::NatKind::direct_capable`).
//!
//! What is not built yet: the agent publishing a direct offer through the relay, and UDP/TCP hole punching.
//! `decide` is the one place the rule lives, so those can be added without touching the relay path.

use super::flags::Flags;
use super::nat::NatKind;
use serde::Serialize;
use std::net::SocketAddr;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case", tag = "route")]
pub enum Route {
    Relay { why: String },
    Direct { addr: SocketAddr },
}

/// A host's offer of a direct path, as the relay would pass it on.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Offer {
    pub host_allows: bool,
    pub host_nat: NatKind,
    pub addr: Option<SocketAddr>,
}

pub fn decide(flags: &Flags, offer: Option<&Offer>, player_allows: bool, player_nat: NatKind) -> Route {
    let relay = |why: &str| Route::Relay { why: why.to_string() };
    if !flags.p2p_hosting {
        return relay("direct connections are off");
    }
    let Some(o) = offer else { return relay("the host does not offer a direct path") };
    if !o.host_allows {
        return relay("the host keeps its address private");
    }
    if !player_allows {
        return relay("you keep your address private");
    }
    if !o.host_nat.direct_capable() {
        return relay("the host's network cannot take direct connections");
    }
    if !player_nat.direct_capable() {
        return relay("your network cannot make direct connections");
    }
    match o.addr {
        Some(a) if !a.ip().is_loopback() && !a.ip().is_unspecified() && a.port() != 0 => Route::Direct { addr: a },
        _ => relay("the host's address is not known"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relay_unless_everyone_agrees() {
        let on = Flags { p2p_hosting: true, ..Default::default() };
        let offer = Offer { host_allows: true, host_nat: NatKind::EndpointIndependent, addr: Some("203.0.113.5:40000".parse().unwrap()) };
        assert!(matches!(decide(&on, Some(&offer), true, NatKind::Open), Route::Direct { .. }));
        assert!(matches!(decide(&Flags::default(), Some(&offer), true, NatKind::Open), Route::Relay { .. }));
        assert!(matches!(decide(&on, None, true, NatKind::Open), Route::Relay { .. }));
        assert!(matches!(decide(&on, Some(&offer), false, NatKind::Open), Route::Relay { .. }));
        assert!(matches!(decide(&on, Some(&offer), true, NatKind::Symmetric), Route::Relay { .. }));
        let shy = Offer { host_allows: false, ..offer.clone() };
        assert!(matches!(decide(&on, Some(&shy), true, NatKind::Open), Route::Relay { .. }));
        let lo = Offer { addr: Some("127.0.0.1:1".parse().unwrap()), ..offer };
        assert!(matches!(decide(&on, Some(&lo), true, NatKind::Open), Route::Relay { .. }));
    }
}
