//! The file version of a Windows executable, read from its version resource (VS_FIXEDFILEINFO).
//!
//! Plain byte parsing, so it works on every OS: a client folder copied to a Mac or Linux PC is detected the
//! same way as on Windows. The resource's fixed block starts with the signature 0xFEEF04BD followed by the
//! structure version 0x00010000, then the file version as two u32s (major.minor, patch.build).

use std::fs;
use std::io;
use std::path::Path;

const SIGNATURE: [u8; 4] = 0xFEEF_04BDu32.to_le_bytes();
const STRUC_VERSION: u32 = 0x0001_0000;

/// A four-part file version, like 3.3.5.12340.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct FileVersion {
    pub major: u16,
    pub minor: u16,
    pub patch: u16,
    pub build: u16,
}

impl std::fmt::Display for FileVersion {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}.{}.{}.{}", self.major, self.minor, self.patch, self.build)
    }
}

fn u32_at(b: &[u8], at: usize) -> Option<u32> {
    b.get(at..at + 4).map(|s| u32::from_le_bytes([s[0], s[1], s[2], s[3]]))
}

/// The file version in an executable's bytes, or None when it is not a PE file or has no version resource.
pub fn parse(bytes: &[u8]) -> Option<FileVersion> {
    if !bytes.starts_with(b"MZ") {
        return None;
    }
    let mut from = 0;
    while let Some(off) = find(&bytes[from..], &SIGNATURE) {
        let at = from + off;
        if u32_at(bytes, at + 4) == Some(STRUC_VERSION) {
            let ms = u32_at(bytes, at + 8)?;
            let ls = u32_at(bytes, at + 12)?;
            return Some(FileVersion {
                major: (ms >> 16) as u16,
                minor: (ms & 0xffff) as u16,
                patch: (ls >> 16) as u16,
                build: (ls & 0xffff) as u16,
            });
        }
        from = at + 1;
    }
    None
}

fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

/// Read the version of the executable at `path`. Ok(None) when the file has no version resource.
pub fn read(path: &Path) -> io::Result<Option<FileVersion>> {
    Ok(parse(&fs::read(path)?))
}

/// Build a minimal fake PE with a version resource (tests here and in `clients`).
#[cfg(test)]
pub fn fake_exe(major: u16, minor: u16, patch: u16, build: u16) -> Vec<u8> {
    let mut b = b"MZ".to_vec();
    b.extend_from_slice(&[0u8; 200]);
    b.extend_from_slice(&SIGNATURE);
    b.extend_from_slice(&STRUC_VERSION.to_le_bytes());
    b.extend_from_slice(&(((major as u32) << 16) | minor as u32).to_le_bytes());
    b.extend_from_slice(&(((patch as u32) << 16) | build as u32).to_le_bytes());
    b.extend_from_slice(&[0u8; 64]);
    b
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_the_fixed_file_info() {
        let v = parse(&fake_exe(3, 3, 5, 12340)).unwrap();
        assert_eq!(v, FileVersion { major: 3, minor: 3, patch: 5, build: 12340 });
        assert_eq!(v.to_string(), "3.3.5.12340");
        assert_eq!(parse(&fake_exe(1, 12, 1, 5875)).unwrap().build, 5875);
    }

    #[test]
    fn not_a_pe_or_no_resource() {
        assert_eq!(parse(b"hello"), None);
        assert_eq!(parse(b"MZ\0\0\0\0"), None);
    }

    #[test]
    fn skips_a_stray_signature() {
        // A signature without the structure version is ignored; the real block later is found.
        let mut b = b"MZ".to_vec();
        b.extend_from_slice(&SIGNATURE);
        b.extend_from_slice(&[9, 9, 9, 9]);
        b.extend_from_slice(&fake_exe(1, 12, 1, 5875)[2..]);
        assert_eq!(parse(&b).unwrap().to_string(), "1.12.1.5875");
    }
}
