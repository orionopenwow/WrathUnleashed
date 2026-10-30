//! Bencode (BEP 3), enough to read a `.torrent` file and to write one in tests. Strict: dictionary keys must be
//! sorted and unique, integers canonical, nesting at most 32 deep, and nothing may follow the top value.

use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Value {
    Int(i64),
    Bytes(Vec<u8>),
    List(Vec<Value>),
    Dict(BTreeMap<Vec<u8>, Value>),
}

impl Value {
    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Dict(d) => d.get(key.as_bytes()),
            _ => None,
        }
    }
    pub fn int(&self) -> Option<i64> {
        match self {
            Value::Int(i) => Some(*i),
            _ => None,
        }
    }
    pub fn bytes(&self) -> Option<&[u8]> {
        match self {
            Value::Bytes(b) => Some(b),
            _ => None,
        }
    }
    pub fn str(&self) -> Option<&str> {
        self.bytes().and_then(|b| std::str::from_utf8(b).ok())
    }
    pub fn list(&self) -> Option<&[Value]> {
        match self {
            Value::List(l) => Some(l),
            _ => None,
        }
    }
}

const MAX_DEPTH: usize = 32;

struct P<'a> {
    b: &'a [u8],
    i: usize,
    /// The byte range of the top-level dictionary's `info` value (for the info-hash).
    info: Option<(usize, usize)>,
}

impl P<'_> {
    fn peek(&self) -> Result<u8, String> {
        self.b.get(self.i).copied().ok_or_else(|| "the torrent file ends early".into())
    }
    fn until(&mut self, end: u8) -> Result<&str, String> {
        let start = self.i;
        while self.peek()? != end {
            self.i += 1;
        }
        let s = std::str::from_utf8(&self.b[start..self.i]).map_err(|_| "bad number in the torrent file")?;
        self.i += 1;
        Ok(s)
    }
    fn number(s: &str) -> Result<i64, String> {
        let canonical = s == "0" || (!s.starts_with('0') && !s.starts_with("-0") && !s.is_empty() && s != "-");
        if !canonical {
            return Err(format!("bad number in the torrent file: {s:?}"));
        }
        s.parse::<i64>().map_err(|_| format!("bad number in the torrent file: {s:?}"))
    }
    fn value(&mut self, depth: usize) -> Result<Value, String> {
        if depth > MAX_DEPTH {
            return Err("the torrent file is nested too deep".into());
        }
        match self.peek()? {
            b'i' => {
                self.i += 1;
                let s = self.until(b'e')?.to_string();
                Ok(Value::Int(Self::number(&s)?))
            }
            b'l' => {
                self.i += 1;
                let mut v = Vec::new();
                while self.peek()? != b'e' {
                    v.push(self.value(depth + 1)?);
                }
                self.i += 1;
                Ok(Value::List(v))
            }
            b'd' => {
                self.i += 1;
                let mut d = BTreeMap::new();
                let mut last: Option<Vec<u8>> = None;
                while self.peek()? != b'e' {
                    let k = match self.value(depth + 1)? {
                        Value::Bytes(k) => k,
                        _ => return Err("a dictionary key in the torrent file is not a string".into()),
                    };
                    if last.as_ref().is_some_and(|l| *l >= k) {
                        return Err("the torrent file's keys are not sorted".into());
                    }
                    let start = self.i;
                    let v = self.value(depth + 1)?;
                    if depth == 0 && k == b"info" {
                        self.info = Some((start, self.i));
                    }
                    last = Some(k.clone());
                    d.insert(k, v);
                }
                self.i += 1;
                Ok(Value::Dict(d))
            }
            b'0'..=b'9' => {
                let s = self.until(b':')?.to_string();
                let n = usize::try_from(Self::number(&s)?).map_err(|_| "bad length")?;
                let end = self.i.checked_add(n).filter(|e| *e <= self.b.len()).ok_or("the torrent file ends early")?;
                let v = self.b[self.i..end].to_vec();
                self.i = end;
                Ok(Value::Bytes(v))
            }
            c => Err(format!("unexpected byte {c:#04x} in the torrent file")),
        }
    }
}

/// Decode `b`. Returns the value and the raw bytes of the top-level `info` dictionary, if there is one.
pub fn decode(b: &[u8]) -> Result<(Value, Option<&[u8]>), String> {
    let mut p = P { b, i: 0, info: None };
    let v = p.value(0)?;
    if p.i != b.len() {
        return Err("extra bytes after the torrent data".into());
    }
    Ok((v, p.info.map(|(s, e)| &b[s..e])))
}

pub fn encode(v: &Value) -> Vec<u8> {
    let mut out = Vec::new();
    enc(v, &mut out);
    out
}

fn enc(v: &Value, out: &mut Vec<u8>) {
    match v {
        Value::Int(i) => out.extend_from_slice(format!("i{i}e").as_bytes()),
        Value::Bytes(b) => {
            out.extend_from_slice(format!("{}:", b.len()).as_bytes());
            out.extend_from_slice(b);
        }
        Value::List(l) => {
            out.push(b'l');
            l.iter().for_each(|x| enc(x, out));
            out.push(b'e');
        }
        Value::Dict(d) => {
            out.push(b'd');
            for (k, x) in d {
                enc(&Value::Bytes(k.clone()), out);
                enc(x, out);
            }
            out.push(b'e');
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_and_info_span() {
        let raw = b"d8:announce3:abc4:infod6:lengthi5e4:name1:xe8:url-listl3:urlee";
        let (v, info) = decode(raw).unwrap();
        assert_eq!(info.unwrap(), b"d6:lengthi5e4:name1:xe");
        assert_eq!(v.get("info").unwrap().get("length").unwrap().int(), Some(5));
        assert_eq!(encode(&v), raw.to_vec());
    }

    #[test]
    fn strict() {
        for bad in [&b"i01e"[..], b"i-0e", b"ie", b"d1:b0:1:a0:e", b"5:abc", b"l", b"i1ei2e", b"x", b"d1:ai1ee1"] {
            assert!(decode(bad).is_err(), "{:?}", String::from_utf8_lossy(bad));
        }
        let deep = format!("{}{}", "l".repeat(40), "e".repeat(40));
        assert!(decode(deep.as_bytes()).is_err());
        assert_eq!(decode(b"i-12e").unwrap().0.int(), Some(-12));
    }
}
