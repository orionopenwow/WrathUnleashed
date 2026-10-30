//! The NAT check for direct connections: STUN Binding requests (RFC 5389) over UDP to two servers, to learn
//! this PC's public address and whether the router keeps the same mapping for different destinations.
//!
//! Only used when `p2p_hosting` is on. A STUN server sees this PC's public IP address, as any website does;
//! nothing else is sent. Plain std UDP, no crate.

use serde::Serialize;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, ToSocketAddrs, UdpSocket};
use std::time::Duration;

const MAGIC: u32 = 0x2112_A442;
const BINDING_REQUEST: u16 = 0x0001;
const BINDING_SUCCESS: u16 = 0x0101;
const ATTR_MAPPED: u16 = 0x0001;
const ATTR_XOR_MAPPED: u16 = 0x0020;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NatKind {
    /// The public address is this PC's own: no NAT.
    Open,
    /// The same public address and port for every destination: direct connections can work.
    EndpointIndependent,
    /// A different port per destination: direct connections will not work; use the relay.
    Symmetric,
    /// Only one server answered, so it cannot tell.
    Unknown,
    /// No server answered: UDP is blocked or there is no network.
    Blocked,
}

impl NatKind {
    pub fn direct_capable(self) -> bool {
        matches!(self, NatKind::Open | NatKind::EndpointIndependent)
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct NatReport {
    pub kind: NatKind,
    pub public: Option<SocketAddr>,
    pub local: Option<SocketAddr>,
    /// What each server said (server, mapped address or error).
    pub answers: Vec<(String, Result<SocketAddr, String>)>,
}

/// A Binding request with transaction id `tid`.
pub fn request(tid: [u8; 12]) -> [u8; 20] {
    let mut b = [0u8; 20];
    b[0..2].copy_from_slice(&BINDING_REQUEST.to_be_bytes());
    b[4..8].copy_from_slice(&MAGIC.to_be_bytes());
    b[8..20].copy_from_slice(&tid);
    b
}

/// The mapped address in a Binding success response for `tid`.
pub fn parse_response(b: &[u8], tid: [u8; 12]) -> Result<SocketAddr, String> {
    if b.len() < 20 || u16::from_be_bytes([b[0], b[1]]) != BINDING_SUCCESS {
        return Err("not a STUN success response".into());
    }
    if u32::from_be_bytes([b[4], b[5], b[6], b[7]]) != MAGIC || b[8..20] != tid {
        return Err("a STUN response for another request".into());
    }
    let len = u16::from_be_bytes([b[2], b[3]]) as usize;
    let attrs = b.get(20..20 + len).ok_or("a short STUN response")?;
    let mut i = 0;
    let mut plain = None;
    while i + 4 <= attrs.len() {
        let t = u16::from_be_bytes([attrs[i], attrs[i + 1]]);
        let l = u16::from_be_bytes([attrs[i + 2], attrs[i + 3]]) as usize;
        let v = attrs.get(i + 4..i + 4 + l).ok_or("a short STUN attribute")?;
        if t == ATTR_XOR_MAPPED || t == ATTR_MAPPED {
            let xor = t == ATTR_XOR_MAPPED;
            if v.len() < 8 {
                return Err("a short address".into());
            }
            let port = u16::from_be_bytes([v[2], v[3]]) ^ if xor { (MAGIC >> 16) as u16 } else { 0 };
            let ip = match v[1] {
                1 => {
                    let mut o = [v[4], v[5], v[6], v[7]];
                    if xor {
                        for (x, m) in o.iter_mut().zip(MAGIC.to_be_bytes()) {
                            *x ^= m;
                        }
                    }
                    IpAddr::V4(Ipv4Addr::from(o))
                }
                2 if v.len() >= 20 => {
                    let mut o: [u8; 16] = v[4..20].try_into().unwrap();
                    if xor {
                        let mut key = [0u8; 16];
                        key[..4].copy_from_slice(&MAGIC.to_be_bytes());
                        key[4..].copy_from_slice(&tid);
                        for (x, k) in o.iter_mut().zip(key) {
                            *x ^= k;
                        }
                    }
                    IpAddr::V6(Ipv6Addr::from(o))
                }
                _ => return Err("an unknown address family".into()),
            };
            let a = SocketAddr::new(ip, port);
            if xor {
                return Ok(a);
            }
            plain = Some(a);
        }
        i += 4 + l.div_ceil(4) * 4;
    }
    plain.ok_or_else(|| "no address in the STUN response".into())
}

fn tid() -> [u8; 12] {
    let mut t = [0u8; 12];
    let n = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let mix = n ^ ((std::process::id() as u128) << 64) ^ (&t as *const _ as usize as u128);
    t.copy_from_slice(&mix.to_le_bytes()[..12]);
    t
}

/// Ask one STUN server (`host:port`) from `sock`; two tries.
pub fn ask(sock: &UdpSocket, server: &str, timeout: Duration) -> Result<SocketAddr, String> {
    let addr = server.to_socket_addrs().map_err(|e| format!("{server}: {e}"))?.find(|a| a.is_ipv4()).ok_or("no IPv4 address")?;
    sock.set_read_timeout(Some(timeout)).map_err(|e| e.to_string())?;
    let t = tid();
    let mut buf = [0u8; 576];
    for _ in 0..2 {
        sock.send_to(&request(t), addr).map_err(|e| e.to_string())?;
        loop {
            match sock.recv_from(&mut buf) {
                Ok((n, from)) if from == addr => match parse_response(&buf[..n], t) {
                    Ok(a) => return Ok(a),
                    Err(_) => continue,
                },
                Ok(_) => continue,
                Err(_) => break,
            }
        }
    }
    Err(format!("{server}: no answer"))
}

/// Classify this PC's NAT with up to two STUN servers, from one UDP socket.
pub fn check(servers: &[String], timeout: Duration) -> NatReport {
    let sock = match UdpSocket::bind("0.0.0.0:0") {
        Ok(s) => s,
        Err(e) => return NatReport { kind: NatKind::Blocked, public: None, local: None, answers: vec![("bind".into(), Err(e.to_string()))] },
    };
    let local = sock.local_addr().ok();
    let answers: Vec<(String, Result<SocketAddr, String>)> = servers.iter().take(2).map(|s| (s.clone(), ask(&sock, s, timeout))).collect();
    let got: Vec<SocketAddr> = answers.iter().filter_map(|(_, r)| r.as_ref().ok().copied()).collect();
    let kind = match got.as_slice() {
        [] => NatKind::Blocked,
        [a, rest @ ..] if local.is_some_and(|l| l.port() == a.port() && !a.ip().is_loopback() && local_ip_is(a.ip())) && rest.iter().all(|r| r == a) => NatKind::Open,
        [_] => NatKind::Unknown,
        [a, b, ..] if a == b => NatKind::EndpointIndependent,
        _ => NatKind::Symmetric,
    };
    NatReport { kind, public: got.first().copied(), local, answers }
}

/// The public address is bound on this machine (no NAT). Best effort: connect a UDP socket and compare.
fn local_ip_is(ip: IpAddr) -> bool {
    UdpSocket::bind("0.0.0.0:0").and_then(|s| s.connect((ip, 9)).and_then(|_| s.local_addr())).map(|a| a.ip() == ip).unwrap_or(false)
}

#[cfg(test)]
pub mod tests {
    use super::*;

    /// A STUN server on 127.0.0.1 that answers every Binding request with `mapped` (or the real source
    /// when None).
    pub fn fake_stun(mapped: Option<SocketAddr>) -> String {
        let s = UdpSocket::bind("127.0.0.1:0").unwrap();
        let port = s.local_addr().unwrap().port();
        std::thread::spawn(move || {
            let mut buf = [0u8; 576];
            while let Ok((n, from)) = s.recv_from(&mut buf) {
                if n < 20 {
                    continue;
                }
                let a = mapped.unwrap_or(from);
                let SocketAddr::V4(v4) = a else { continue };
                let mut r = vec![0x01, 0x01, 0, 12];
                r.extend_from_slice(&buf[4..20]);
                r.extend_from_slice(&[0x00, 0x20, 0, 8, 0, 1]);
                r.extend_from_slice(&(v4.port() ^ (MAGIC >> 16) as u16).to_be_bytes());
                let o = v4.ip().octets();
                for (x, m) in o.iter().zip(MAGIC.to_be_bytes()) {
                    r.push(x ^ m);
                }
                let _ = s.send_to(&r, from);
            }
        });
        format!("127.0.0.1:{port}")
    }

    #[test]
    fn rfc5769_style_response() {
        let t = [1u8; 12];
        // XOR-MAPPED-ADDRESS 192.0.2.1:32853, as in RFC 5769 2.2.
        let mut r = vec![0x01, 0x01, 0, 12];
        r.extend_from_slice(&MAGIC.to_be_bytes());
        r.extend_from_slice(&t);
        r.extend_from_slice(&[0x00, 0x20, 0x00, 0x08, 0x00, 0x01, 0xa1, 0x47, 0xe1, 0x12, 0xa6, 0x43]);
        assert_eq!(parse_response(&r, t).unwrap(), "192.0.2.1:32853".parse().unwrap());
        assert!(parse_response(&r, [2u8; 12]).is_err(), "another transaction");
        assert!(parse_response(&r[..10], t).is_err());
        assert_eq!(request(t)[0..2], [0, 1]);
    }

    #[test]
    fn classifies_with_local_servers() {
        let same: SocketAddr = "203.0.113.5:50000".parse().unwrap();
        let a = fake_stun(Some(same));
        let b = fake_stun(Some(same));
        let r = check(&[a.clone(), b], Duration::from_millis(500));
        assert_eq!((r.kind, r.public), (NatKind::EndpointIndependent, Some(same)));
        assert!(r.kind.direct_capable());
        let c = fake_stun(Some("203.0.113.5:50001".parse().unwrap()));
        assert_eq!(check(&[a.clone(), c], Duration::from_millis(500)).kind, NatKind::Symmetric);
        let dead = {
            let s = UdpSocket::bind("127.0.0.1:0").unwrap();
            let p = s.local_addr().unwrap().port();
            drop(s);
            format!("127.0.0.1:{p}")
        };
        assert_eq!(check(&[a, dead.clone()], Duration::from_millis(200)).kind, NatKind::Unknown);
        assert_eq!(check(&[dead], Duration::from_millis(200)).kind, NatKind::Blocked);
        assert!(!NatKind::Symmetric.direct_capable());
    }
}
