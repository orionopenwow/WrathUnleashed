// mpq.js — a read-only MPQ reader in plain JavaScript, for "Use my own game files".
//
// Runs unchanged in a page, a (classic or module) worker, a service worker (importScripts) and
// Node (require). It exposes one global, `WUMpq`, and the same object as `module.exports`.
//
// Mirrors crates/benilla-mpq (the client's own reader) and goes past it where the browser path
// needs to be self-sufficient:
//   * header: `MPQ\x1A` at the first 512-aligned offset, or where a `MPQ\x1B` user-data header
//     points; format v1, v2 (the 44-byte header's hi-block table and the high 16 bits of the table
//     positions are honoured; benilla-mpq ignores them, which is the same answer below 4 GiB);
//     v3/v4 archives are read through their classic hash/block tables like benilla-mpq does.
//   * hash table + block table decrypted with the standard Storm crypt table.
//   * name lookup exactly as benilla-mpq: case-insensitive, `/` == `\`, first matching hash entry
//     in the open-addressed probe (locale is NOT consulted — 3.3.5a's chain is locale-by-folder).
//   * files: stored, sectored COMPRESS, single-unit, IMPLODE-only; encrypted files (key from the
//     base name, KEY_V2/FIX_KEY adjusted by block offset and size); sector-CRC tables skipped;
//     delete markers (0x02000000) reported, never read.
//   * sector codecs: zlib (0x02, a synchronous table-driven inflate; DecompressionStream is
//     kept as codecs.inflateStream but costs ~0.3 ms of setup per 4 KiB sector),
//     bzip2 (0x10), PKWARE DCL implode (0x08 / IMPLODE flag), Huffman (0x01), IMA ADPCM mono
//     (0x40) and stereo (0x80), sparse (0x20), in StormLib's decompression order for combined
//     masks. LZMA (0x12) and PTCH patch files (0x00100000) are reported as unsupported.
// The codec ports follow StormLib (MIT, Ladislav Zezula) function by function.
(function (root) {
  'use strict';

  const SIGNATURE = 0x1a51504d; // 'MPQ\x1A'
  const USERDATA_SIGNATURE = 0x1b51504d; // 'MPQ\x1B'

  const FLAG = {
    IMPLODE: 0x00000100,
    COMPRESS: 0x00000200,
    ENCRYPTED: 0x00010000,
    KEY_V2: 0x00020000,
    PATCH_FILE: 0x00100000,
    SINGLE_UNIT: 0x01000000,
    DELETE_MARKER: 0x02000000,
    SECTOR_CRC: 0x04000000,
    EXISTS: 0x80000000,
  };
  const HASH_EMPTY = 0xffffffff;
  const HASH_DELETED = 0xfffffffe;

  class MpqError extends Error {
    constructor(code, message) {
      super(message);
      this.code = code; // 'notfound' | 'deleted' | 'unsupported' | 'corrupt' | 'decompress' | 'notmpq'
    }
  }

  // ---------------------------------------------------------------------------------------------
  // Storm crypto

  const CRYPT = (() => {
    const t = new Uint32Array(0x500);
    let seed = 0x00100001;
    for (let i1 = 0; i1 < 0x100; i1++) {
      for (let i2 = 0; i2 < 5; i2++) {
        seed = (seed * 125 + 3) % 0x2aaaab;
        const t1 = (seed & 0xffff) << 16;
        seed = (seed * 125 + 3) % 0x2aaaab;
        const t2 = seed & 0xffff;
        t[i1 + i2 * 0x100] = (t1 | t2) >>> 0;
      }
    }
    return t;
  })();

  const HASH_TABLE_OFFSET = 0x000;
  const HASH_NAME_A = 0x100;
  const HASH_NAME_B = 0x200;
  const HASH_FILE_KEY = 0x300;

  const utf8 = typeof TextEncoder !== 'undefined' ? new TextEncoder() : null;
  function nameBytes(name) {
    // Fast path for ASCII (every real chain name); UTF-8 bytes otherwise, as benilla hashes bytes.
    let ascii = true;
    for (let i = 0; i < name.length; i++) if (name.charCodeAt(i) > 0x7f) { ascii = false; break; }
    if (!ascii) return utf8.encode(name);
    const b = new Uint8Array(name.length);
    for (let i = 0; i < name.length; i++) b[i] = name.charCodeAt(i);
    return b;
  }

  /// Blizzard's string hash: `/` reads as `\`, and only `a`-`z` are uppercased.
  function hashBytes(bytes, type) {
    let s1 = 0x7fed7fed;
    let s2 = 0xeeeeeeee;
    for (let i = 0; i < bytes.length; i++) {
      let ch = bytes[i];
      if (ch === 0x2f) ch = 0x5c;
      else if (ch >= 0x61 && ch <= 0x7a) ch -= 0x20;
      s1 = (CRYPT[type + ch] ^ ((s1 + s2) >>> 0)) >>> 0;
      s2 = (ch + s1 + s2 + (s2 << 5) + 3) >>> 0;
    }
    return s1;
  }
  function hashString(name, type) {
    return hashBytes(nameBytes(name), type);
  }

  /// The three lookup hashes of a name, computed once and reused against every archive.
  function nameHashes(name) {
    const b = nameBytes(name);
    return { name, start: hashBytes(b, HASH_TABLE_OFFSET), a: hashBytes(b, HASH_NAME_A), b: hashBytes(b, HASH_NAME_B) };
  }

  /// Decrypt `count` little-endian u32 words of `u8` in place (trailing bytes are not encrypted).
  function decryptBytes(u8, key) {
    key >>>= 0;
    if (key === 0) return u8;
    const n = u8.length >>> 2;
    const dv = new DataView(u8.buffer, u8.byteOffset, n * 4);
    let seed = 0xeeeeeeee;
    for (let i = 0; i < n; i++) {
      seed = (seed + CRYPT[0x400 + (key & 0xff)]) >>> 0;
      const ch = (dv.getUint32(i * 4, true) ^ ((key + seed) >>> 0)) >>> 0;
      dv.setUint32(i * 4, ch, true);
      key = ((((~key) << 0x15) + 0x11111111) | (key >>> 0x0b)) >>> 0;
      seed = (ch + seed + (seed << 5) + 3) >>> 0;
    }
    return u8;
  }

  /// The inverse, for tests that build encrypted data.
  function encryptBytes(u8, key) {
    key >>>= 0;
    const n = u8.length >>> 2;
    const dv = new DataView(u8.buffer, u8.byteOffset, n * 4);
    let seed = 0xeeeeeeee;
    for (let i = 0; i < n; i++) {
      seed = (seed + CRYPT[0x400 + (key & 0xff)]) >>> 0;
      const plain = dv.getUint32(i * 4, true);
      dv.setUint32(i * 4, (plain ^ ((key + seed) >>> 0)) >>> 0, true);
      key = ((((~key) << 0x15) + 0x11111111) | (key >>> 0x0b)) >>> 0;
      seed = (plain + seed + (seed << 5) + 3) >>> 0;
    }
    return u8;
  }

  // ---------------------------------------------------------------------------------------------
  // Byte sources: { size, read(offset, length) -> Promise<Uint8Array> }

  /// A source over a Blob/File: every read is one `slice()` — only the bytes asked for leave disk.
  function blobSource(blob, label) {
    return {
      size: blob.size,
      label: label || blob.name || 'blob',
      async read(offset, length) {
        if (length <= 0) return new Uint8Array(0);
        const ab = await blob.slice(offset, offset + length).arrayBuffer();
        return new Uint8Array(ab);
      },
    };
  }

  /// A source over bytes already in memory (tests, small archives).
  function bytesSource(bytes, label) {
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    return {
      size: u8.length,
      label: label || 'bytes',
      async read(offset, length) {
        return u8.slice(offset, offset + length);
      },
    };
  }

  // ---------------------------------------------------------------------------------------------
  // Archive

  const u32 = (u8, o) => (u8[o] | (u8[o + 1] << 8) | (u8[o + 2] << 16) | (u8[o + 3] << 24)) >>> 0;
  const u16 = (u8, o) => u8[o] | (u8[o + 1] << 8);

  async function findHeader(src) {
    const CHUNK = 1 << 20;
    for (let base = 0; base + 4 <= src.size; base += CHUNK) {
      const len = Math.min(CHUNK + 16, src.size - base);
      const buf = await src.read(base, len);
      for (let off = 0; off + 4 <= buf.length && off < CHUNK; off += 512) {
        const sig = u32(buf, off);
        if (sig === SIGNATURE) return base + off;
        if (sig === USERDATA_SIGNATURE) {
          const more = off + 12 <= buf.length ? buf : await src.read(base + off, 12);
          const at = more === buf ? off : 0;
          return base + off + u32(more, at + 8);
        }
      }
    }
    throw new MpqError('notmpq', `${src.label}: not an MPQ archive (no header signature found)`);
  }

  class MpqArchive {
    /// Open an archive: header, then the decrypted hash and block tables (cached for the
    /// archive's lifetime — every later lookup is memory-only).
    static async open(src, label) {
      const a = new MpqArchive();
      a.src = src;
      a.label = label || src.label;
      const off = await findHeader(src);
      const hdr = await src.read(off, Math.min(208, src.size - off));
      if (hdr.length < 32 || u32(hdr, 0) !== SIGNATURE) throw new MpqError('notmpq', `${a.label}: bad header`);
      const headerSize = u32(hdr, 4);
      a.formatVersion = u16(hdr, 12);
      const shift = u16(hdr, 14);
      if (shift > 23) throw new MpqError('corrupt', `${a.label}: block size shift ${shift} exceeds the sanity cap`);
      a.archiveOffset = off;
      a.sectorSize = 512 * 2 ** shift;
      let hashPos = u32(hdr, 16);
      let blockPos = u32(hdr, 20);
      a.hashCount = u32(hdr, 24);
      a.blockCount = u32(hdr, 28);
      let hiBlockPos = 0;
      if (a.formatVersion >= 1 && headerSize >= 44 && hdr.length >= 44) {
        hiBlockPos = u32(hdr, 32) + u32(hdr, 36) * 2 ** 32;
        hashPos += u16(hdr, 40) * 2 ** 32;
        blockPos += u16(hdr, 42) * 2 ** 32;
      }
      const readTable = async (pos, count, keyName, what) => {
        const abs = off + pos;
        if (count * 16 > Math.max(0, src.size - abs)) {
          throw new MpqError('corrupt', `${a.label}: ${what}: header claims ${count} entries, only room for ${Math.floor(Math.max(0, src.size - abs) / 16)} in the archive`);
        }
        const bytes = await src.read(abs, count * 16);
        decryptBytes(bytes, hashString(keyName, HASH_FILE_KEY));
        return new Uint32Array(bytes.buffer, bytes.byteOffset, count * 4);
      };
      a.hashTable = await readTable(hashPos, a.hashCount, '(hash table)', 'hash table');
      a.blockTable = await readTable(blockPos, a.blockCount, '(block table)', 'block table');
      a.hiBlock = null;
      if (hiBlockPos) {
        const abs = off + hiBlockPos;
        if (abs + a.blockCount * 2 <= src.size) {
          const b = await src.read(abs, a.blockCount * 2);
          a.hiBlock = new Uint16Array(b.buffer.slice(b.byteOffset, b.byteOffset + a.blockCount * 2));
        }
      }
      return a;
    }

    /// Block index for a name (or its precomputed `nameHashes`), or -1. benilla-mpq's probe:
    /// an empty slot ends it, a deleted slot is skipped, the first A/B match wins.
    find(nameOrHashes) {
      const h = typeof nameOrHashes === 'string' ? nameHashes(nameOrHashes) : nameOrHashes;
      const len = this.hashCount;
      if (len === 0) return -1;
      const mask = (len - 1) >>> 0;
      const start = (h.start & mask) >>> 0;
      const H = this.hashTable;
      for (let i = 0; i < len; i++) {
        const e = ((start + i) % len) * 4;
        const bi = H[e + 3];
        if (bi === HASH_EMPTY) return -1;
        if (bi === HASH_DELETED) continue;
        if (H[e] === h.a && H[e + 1] === h.b) return bi < this.blockCount ? bi : -1;
      }
      return -1;
    }

    entry(bi) {
      const B = this.blockTable;
      const rel = B[bi * 4];
      const hi = this.hiBlock ? this.hiBlock[bi] : 0;
      return {
        index: bi,
        relPos: rel,
        filePos: this.archiveOffset + rel + hi * 2 ** 32,
        csize: B[bi * 4 + 1],
        fsize: B[bi * 4 + 2],
        flags: B[bi * 4 + 3] >>> 0,
      };
    }

    contains(name) {
      return this.find(name) >= 0;
    }
    isDeleteMarker(name) {
      const bi = this.find(name);
      return bi >= 0 && (this.entry(bi).flags & FLAG.DELETE_MARKER) !== 0;
    }
    fileSize(name) {
      const bi = this.find(name);
      return bi >= 0 ? this.entry(bi).fsize : null;
    }

    /// Read and decompress a file by internal path (`/` or `\`, any case).
    async readFile(name) {
      const h = typeof name === 'string' ? nameHashes(name) : name;
      const bi = this.find(h);
      if (bi < 0) throw new MpqError('notfound', `file not in archive: ${h.name}`);
      return this.readEntry(this.entry(bi), h.name);
    }

    async readEntry(e, name) {
      const flags = e.flags;
      if ((flags & FLAG.EXISTS) === 0) throw new MpqError('notfound', `file not in archive: ${name}`);
      if (flags & FLAG.DELETE_MARKER) throw new MpqError('deleted', `file deleted (delete marker): ${name}`);
      if (flags & FLAG.PATCH_FILE) throw new MpqError('unsupported', `${name}: PTCH patch files are not supported`);
      const fsize = e.fsize;
      if (fsize === 0) return new Uint8Array(0);
      const avail = Math.max(0, this.src.size - e.filePos);
      let key = 0;
      if (flags & FLAG.ENCRYPTED) {
        const base = name.slice(Math.max(name.lastIndexOf('\\'), name.lastIndexOf('/')) + 1);
        key = hashString(base, HASH_FILE_KEY);
        if (flags & FLAG.KEY_V2) key = (((key + e.relPos) >>> 0) ^ fsize) >>> 0;
      }
      const compressed = (flags & (FLAG.COMPRESS | FLAG.IMPLODE)) !== 0;
      const implodeOnly = (flags & FLAG.IMPLODE) !== 0 && (flags & FLAG.COMPRESS) === 0;

      if (compressed && flags & FLAG.SINGLE_UNIT) {
        if (e.csize > avail) throw new MpqError('corrupt', `${name}: single unit (${e.csize}) larger than the archive`);
        const raw = await this.src.read(e.filePos, e.csize);
        if (key) decryptBytes(raw, key);
        return checkLen(await decodeSector(raw, fsize, implodeOnly, name), fsize, name, 0);
      }
      if (!compressed) {
        if (fsize > avail) throw new MpqError('corrupt', `${name}: stored size (${fsize}) larger than the archive`);
        const raw = await this.src.read(e.filePos, fsize);
        if (key) {
          if (flags & FLAG.SINGLE_UNIT) decryptBytes(raw, key);
          else for (let i = 0, at = 0; at < fsize; i++, at += this.sectorSize) {
            decryptBytes(raw.subarray(at, Math.min(fsize, at + this.sectorSize)), (key + i) >>> 0);
          }
        }
        return raw;
      }

      // Sectored: `count + 1` offsets measured from the file's start (a SECTOR_CRC table sits
      // after them and is skipped for free, as in benilla-mpq).
      const ss = this.sectorSize;
      const count = Math.ceil(fsize / ss);
      const otabLen = (count + 1) * 4;
      if (otabLen > avail) throw new MpqError('corrupt', `${name}: sector offset table (${count + 1} entries) larger than the archive`);
      const otabBytes = await this.src.read(e.filePos, otabLen);
      if (key) decryptBytes(otabBytes, (key - 1) >>> 0);
      const offs = new Array(count + 1);
      for (let i = 0; i <= count; i++) offs[i] = u32(otabBytes, i * 4);
      for (let i = 0; i < count; i++) {
        if (offs[i + 1] < offs[i]) throw new MpqError('decompress', `${name}: sector ${i} offsets reversed`);
        if (offs[i + 1] === offs[i]) throw new MpqError('corrupt', `${name}: sector ${i} is empty`);
      }
      if (offs[count] > avail) throw new MpqError('corrupt', `${name}: sector ${count - 1} past the end of the archive`);
      // One read for the whole file's sectors, then every sector decoded concurrently.
      const span = await this.src.read(e.filePos + offs[0], offs[count] - offs[0]);
      const out = new Uint8Array(fsize);
      const jobs = [];
      for (let i = 0; i < count; i++) {
        const want = Math.min(ss, fsize - i * ss);
        let s = span.subarray(offs[i] - offs[0], offs[i + 1] - offs[0]);
        if (key) s = decryptBytes(s.slice(), (key + i) >>> 0);
        jobs.push(
          decodeSector(s, want, implodeOnly, name).then((bytes) => {
            checkLen(bytes, want, name, i);
            out.set(bytes, i * ss);
          })
        );
      }
      await Promise.all(jobs);
      return out;
    }
  }

  function checkLen(bytes, want, name, i) {
    if (bytes.length !== want) {
      throw new MpqError('decompress', `${name}: sector ${i} inflates to ${bytes.length} bytes, not ${want}`);
    }
    return bytes;
  }

  /// One sector: verbatim when it did not shrink, else codec mask byte + payload (or a bare
  /// PKWARE stream for IMPLODE-only files).
  function decodeSector(raw, want, implodeOnly, name) {
    if (raw.length >= want) return Promise.resolve(raw.subarray(0, want));
    if (implodeOnly) return Promise.resolve(explode(raw, want));
    return decompressMask(raw[0], raw.subarray(1), want, name);
  }

  // StormLib's dcmp_table order: the last compression applied is undone first.
  const CODECS = [
    [0x10, 'bzip2'],
    [0x08, 'pkware'],
    [0x02, 'zlib'],
    [0x01, 'huffman'],
    [0x80, 'adpcm-stereo'],
    [0x40, 'adpcm-mono'],
    [0x20, 'sparse'],
  ];

  async function decompressMask(mask, data, want, name) {
    if (mask === 0x12) throw new MpqError('unsupported', `${name}: LZMA (0x12) sectors are not supported`);
    let rest = mask;
    for (const [bit] of CODECS) rest &= ~bit;
    if (mask === 0 || rest !== 0) {
      throw new MpqError('unsupported', `${name}: sector codec 0x${mask.toString(16).padStart(2, '0').toUpperCase()} not implemented`);
    }
    let cur = data;
    for (const [bit, codec] of CODECS) {
      if (!(mask & bit)) continue;
      let out;
      try {
        switch (codec) {
          case 'bzip2': out = bunzip2(cur, want); break;
          case 'pkware': out = explode(cur, want); break;
          case 'zlib': out = await inflate(cur, want); break;
          case 'huffman': out = huffmanDecompress(cur, want); break;
          case 'adpcm-stereo': out = adpcmDecompress(cur, want, 2); break;
          case 'adpcm-mono': out = adpcmDecompress(cur, want, 1); break;
          case 'sparse': out = sparseDecompress(cur, want); break;
        }
      } catch (e) {
        if (e instanceof MpqError) throw e;
        throw new MpqError('decompress', `${name}: ${codec}: ${e && e.message ? e.message : e}`);
      }
      if (!out || out.length === 0) throw new MpqError('decompress', `${name}: ${codec} produced no data`);
      cur = out;
    }
    return cur;
  }

  // ---------------------------------------------------------------------------------------------
  // zlib (0x02)

  // MPQ sectors are 4 KiB zlib streams: a DecompressionStream per sector costs ~0.3 ms of stream
  // setup each (measured: 12 MiB/s on a 16 MiB file), so the default is this synchronous inflate
  // (RFC 1950/1951, table-driven), with DecompressionStream kept as `inflateStream`.
  const LEN_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
  const LEN_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  const DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577];
  const DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
  const CL_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];

  /// A full lookup table indexed by the next `bits` (LSB-first) bits: entry = sym << 4 | len.
  function huffTable(lengths, n) {
    const count = new Uint16Array(16);
    let maxLen = 0;
    for (let i = 0; i < n; i++) { count[lengths[i]]++; if (lengths[i] > maxLen) maxLen = lengths[i]; }
    count[0] = 0;
    const next = new Uint16Array(16);
    let code = 0;
    for (let len = 1; len <= 15; len++) { code = (code + count[len - 1]) << 1; next[len] = code; }
    const size = 1 << maxLen;
    const table = new Int32Array(size || 1).fill(-1);
    for (let sym = 0; sym < n; sym++) {
      const len = lengths[sym];
      if (!len) continue;
      let c = next[len]++;
      let rev = 0;
      for (let i = 0; i < len; i++) { rev = (rev << 1) | (c & 1); c >>= 1; }
      for (let k = rev; k < size; k += 1 << len) table[k] = (sym << 4) | len;
    }
    return { table, bits: maxLen, mask: size - 1 };
  }
  let FIXED = null;
  function fixedTables() {
    if (!FIXED) {
      const l = new Uint8Array(288);
      l.fill(8, 0, 144); l.fill(9, 144, 256); l.fill(7, 256, 280); l.fill(8, 280, 288);
      FIXED = { lit: huffTable(l, 288), dist: huffTable(new Uint8Array(30).fill(5), 30) };
    }
    return FIXED;
  }

  function inflateSync(src, maxOut) {
    if (src.length < 2) throw new Error('zlib: stream too short');
    const cmf = src[0], flg = src[1];
    if ((cmf & 0x0f) !== 8 || ((cmf << 8) | flg) % 31 !== 0) throw new Error('zlib: bad header');
    if (flg & 0x20) throw new Error('zlib: preset dictionary not supported');
    let p = 2, buf = 0, cnt = 0;
    const end = src.length;
    const need = (n) => {
      while (cnt < n) {
        if (p >= end + 4) throw new Error('zlib: unexpected end of data');
        buf |= (p < end ? src[p] : 0) << cnt;
        p++;
        cnt += 8;
      }
    };
    const take = (n) => {
      if (n === 0) return 0;
      need(n);
      const v = buf & ((1 << n) - 1);
      buf >>>= n;
      cnt -= n;
      return v;
    };
    const sym = (t) => {
      need(t.bits);
      const e = t.table[buf & t.mask];
      if (e < 0) throw new Error('zlib: bad Huffman code');
      const len = e & 15;
      buf >>>= len;
      cnt -= len;
      return e >> 4;
    };
    const out = new Uint8Array(maxOut);
    let o = 0;
    let final = 0;
    while (!final && o < maxOut) {
      final = take(1);
      const type = take(2);
      if (type === 0) {
        p -= cnt >> 3; // give back whole unread bytes, drop to the byte boundary
        buf = 0;
        cnt = 0;
        if (p + 4 > end) throw new Error('zlib: truncated stored block');
        const len = src[p] | (src[p + 1] << 8);
        p += 4;
        const n = Math.min(len, maxOut - o);
        if (p + n > end) throw new Error('zlib: truncated stored block');
        out.set(src.subarray(p, p + n), o);
        o += n;
        p += len;
        continue;
      }
      let lit, dist;
      if (type === 1) ({ lit, dist } = fixedTables());
      else if (type === 2) {
        const hlit = take(5) + 257, hdist = take(5) + 1, hclen = take(4) + 4;
        const cl = new Uint8Array(19);
        for (let i = 0; i < hclen; i++) cl[CL_ORDER[i]] = take(3);
        const clt = huffTable(cl, 19);
        const lens = new Uint8Array(hlit + hdist);
        for (let i = 0; i < hlit + hdist; ) {
          const s = sym(clt);
          if (s < 16) lens[i++] = s;
          else {
            let rep, v = 0;
            if (s === 16) { if (i === 0) throw new Error('zlib: repeat with no previous length'); v = lens[i - 1]; rep = 3 + take(2); }
            else if (s === 17) rep = 3 + take(3);
            else rep = 11 + take(7);
            if (i + rep > hlit + hdist) throw new Error('zlib: too many code lengths');
            lens.fill(v, i, i + rep);
            i += rep;
          }
        }
        lit = huffTable(lens.subarray(0, hlit), hlit);
        dist = huffTable(lens.subarray(hlit), hdist);
      } else throw new Error('zlib: invalid block type');
      for (;;) {
        const s = sym(lit);
        if (s < 256) {
          out[o++] = s;
        } else if (s === 256) break;
        else {
          const li = s - 257;
          if (li >= 29) throw new Error('zlib: bad length code');
          const len = LEN_BASE[li] + take(LEN_EXTRA[li]);
          const di = sym(dist);
          if (di >= 30) throw new Error('zlib: bad distance code');
          const d = DIST_BASE[di] + take(DIST_EXTRA[di]);
          if (d > o) throw new Error('zlib: distance too far back');
          const stop = Math.min(o + len, maxOut);
          while (o < stop) { out[o] = out[o - d]; o++; }
        }
        if (o >= maxOut) break; // bounded like benilla's `take(expected)`: the rest is never needed
      }
    }
    return o === maxOut ? out : out.subarray(0, o);
  }

  async function inflate(data, maxOut) {
    return inflateSync(data, maxOut);
  }

  let nodeZlib = null;
  async function inflateStream(data, maxOut) {
    if (typeof DecompressionStream === 'undefined') {
      if (!nodeZlib && typeof require === 'function') nodeZlib = require('zlib');
      if (!nodeZlib) throw new Error('no DecompressionStream in this context');
      const out = nodeZlib.inflateSync(data, { finishFlush: nodeZlib.constants.Z_SYNC_FLUSH, maxOutputLength: Math.max(maxOut, 1) });
      return new Uint8Array(out.buffer, out.byteOffset, Math.min(out.length, maxOut));
    }
    const ds = new DecompressionStream('deflate'); // RFC 1950 zlib framing, which MPQ sectors use
    const writer = ds.writable.getWriter();
    writer.write(data).catch(() => {});
    writer.close().catch(() => {});
    const reader = ds.readable.getReader();
    const out = new Uint8Array(maxOut);
    let n = 0;
    try {
      while (n < maxOut) {
        const { done, value } = await reader.read();
        if (done) break;
        const take = Math.min(value.length, maxOut - n);
        out.set(take === value.length ? value : value.subarray(0, take), n);
        n += take;
      }
    } catch (e) {
      // A stream that ends without its adler32 trailer still yielded every byte we need.
      if (n < maxOut) throw e;
    } finally {
      reader.cancel().catch(() => {});
    }
    return n === maxOut ? out : out.subarray(0, n);
  }

  // ---------------------------------------------------------------------------------------------
  // bzip2 (0x10) — a straight decoder of the bzip2 format (block sort + MTF + Huffman + RLE).

  function bunzip2(src, maxOut) {
    let p = 0, bitBuf = 0, bitCnt = 0;
    const bits = (n) => {
      while (bitCnt < n) {
        if (p >= src.length + 4) throw new Error('bzip2: unexpected end of data');
        bitBuf = ((bitBuf & 0xffffff) << 8) | (p < src.length ? src[p] : 0);
        p++;
        bitCnt += 8;
      }
      bitCnt -= n;
      return (bitBuf >>> bitCnt) & ((1 << n) - 1);
    };
    const bit = () => bits(1);
    if (bits(8) !== 0x42 || bits(8) !== 0x5a || bits(8) !== 0x68) throw new Error('bzip2: bad stream header');
    const level = bits(8) - 0x30;
    if (level < 1 || level > 9) throw new Error('bzip2: bad block size');
    const tt = new Uint32Array(level * 100000);
    const out = new Uint8Array(maxOut);
    let o = 0;
    // RLE1 state carried across blocks
    let last = -1, run = 0;
    const emit = (b) => {
      if (run === 4) {
        for (let k = 0; k < b && o < maxOut; k++) out[o++] = last;
        run = 0;
        last = -1;
        return;
      }
      if (b === last) run++;
      else { last = b; run = 1; }
      if (o < maxOut) out[o++] = b;
    };
    for (;;) {
      const m1 = bits(24), m2 = bits(24);
      if (m1 === 0x177245 && m2 === 0x385090) break; // end of stream
      if (m1 !== 0x314159 || m2 !== 0x265359) throw new Error('bzip2: bad block magic');
      bits(16); bits(16); // block CRC (not verified; the sector length check is the guard)
      if (bit()) throw new Error('bzip2: randomised blocks are not supported');
      const origPtr = bits(24);
      // symbol map
      const used16 = bits(16);
      const seqToUnseq = [];
      for (let i = 0; i < 16; i++) {
        if (used16 & (0x8000 >> i)) {
          const b16 = bits(16);
          for (let j = 0; j < 16; j++) if (b16 & (0x8000 >> j)) seqToUnseq.push(i * 16 + j);
        }
      }
      const nInUse = seqToUnseq.length;
      if (nInUse === 0) throw new Error('bzip2: empty symbol map');
      const alphaSize = nInUse + 2;
      const nGroups = bits(3);
      if (nGroups < 2 || nGroups > 6) throw new Error('bzip2: bad group count');
      const nSelectors = bits(15);
      if (nSelectors < 1) throw new Error('bzip2: no selectors');
      const mtfG = [0, 1, 2, 3, 4, 5].slice(0, nGroups);
      const selectors = new Uint8Array(nSelectors);
      for (let i = 0; i < nSelectors; i++) {
        let j = 0;
        while (bit()) { j++; if (j >= nGroups) throw new Error('bzip2: bad selector'); }
        const v = mtfG[j];
        for (let k = j; k > 0; k--) mtfG[k] = mtfG[k - 1];
        mtfG[0] = v;
        selectors[i] = v;
      }
      const groups = [];
      for (let t = 0; t < nGroups; t++) {
        const len = new Uint8Array(alphaSize);
        let curr = bits(5);
        for (let i = 0; i < alphaSize; i++) {
          for (;;) {
            if (curr < 1 || curr > 20) throw new Error('bzip2: bad code length');
            if (!bit()) break;
            curr += bit() ? -1 : 1;
          }
          len[i] = curr;
        }
        let minLen = 32, maxLen = 0;
        for (let i = 0; i < alphaSize; i++) { if (len[i] > maxLen) maxLen = len[i]; if (len[i] < minLen) minLen = len[i]; }
        const perm = new Int32Array(258), base = new Int32Array(23), limit = new Int32Array(23);
        let pp = 0;
        for (let i = minLen; i <= maxLen; i++) for (let j = 0; j < alphaSize; j++) if (len[j] === i) perm[pp++] = j;
        for (let i = 0; i < alphaSize; i++) base[len[i] + 1]++;
        for (let i = 1; i < 23; i++) base[i] += base[i - 1];
        let vec = 0;
        for (let i = minLen; i <= maxLen; i++) { vec += base[i + 1] - base[i]; limit[i] = vec - 1; vec <<= 1; }
        for (let i = minLen + 1; i <= maxLen; i++) base[i] = ((limit[i - 1] + 1) << 1) - base[i];
        groups.push({ minLen, maxLen, perm, base, limit });
      }
      const EOB = nInUse + 1;
      let groupNo = -1, groupPos = 0, g = null;
      const nextSym = () => {
        if (groupPos === 0) {
          groupNo++;
          if (groupNo >= nSelectors) throw new Error('bzip2: selector overflow');
          groupPos = 50;
          g = groups[selectors[groupNo]];
        }
        groupPos--;
        let zn = g.minLen;
        let zvec = bits(zn);
        for (;;) {
          if (zn > 20) throw new Error('bzip2: bad Huffman code');
          if (zvec <= g.limit[zn]) break;
          zn++;
          zvec = (zvec << 1) | bit();
        }
        const idx = zvec - g.base[zn];
        if (idx < 0 || idx >= 258) throw new Error('bzip2: bad Huffman code');
        return g.perm[idx];
      };
      const yy = new Uint8Array(256);
      for (let i = 0; i < 256; i++) yy[i] = i;
      const unzftab = new Int32Array(256);
      let nblock = 0;
      const cap = tt.length;
      let sym = nextSym();
      for (;;) {
        if (sym === EOB) break;
        if (sym <= 1) {
          let es = 0, N = 1;
          do {
            es += sym === 0 ? N : 2 * N;
            N *= 2;
            if (N > 2 * 1024 * 1024) throw new Error('bzip2: run too long');
            sym = nextSym();
          } while (sym <= 1);
          const uc = seqToUnseq[yy[0]];
          unzftab[uc] += es;
          if (nblock + es > cap) throw new Error('bzip2: block overflow');
          for (let k = 0; k < es; k++) tt[nblock++] = uc;
          continue;
        }
        const nn = sym - 1;
        const v = yy[nn];
        yy.copyWithin(1, 0, nn);
        yy[0] = v;
        const uc = seqToUnseq[v];
        unzftab[uc]++;
        if (nblock >= cap) throw new Error('bzip2: block overflow');
        tt[nblock++] = uc;
        sym = nextSym();
      }
      if (origPtr >= nblock) throw new Error('bzip2: bad origPtr');
      const cftab = new Int32Array(257);
      for (let i = 0; i < 256; i++) cftab[i + 1] = cftab[i] + unzftab[i];
      for (let i = 0; i < nblock; i++) {
        const uc = tt[i] & 0xff;
        tt[cftab[uc]] = (tt[cftab[uc]] | (i << 8)) >>> 0;
        cftab[uc]++;
      }
      let tPos = tt[origPtr] >>> 8;
      for (let k = 0; k < nblock; k++) {
        tPos = tt[tPos];
        emit(tPos & 0xff);
        tPos >>>= 8;
      }
      if (o >= maxOut) break;
    }
    return o === maxOut ? out : out.subarray(0, o);
  }

  // ---------------------------------------------------------------------------------------------
  // PKWARE DCL explode (0x08, and IMPLODE-flagged files). Tables from StormLib's explode.c.

  const PK = {
    DistBits: [2, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8],
    DistCode: [0x03, 0x0d, 0x05, 0x19, 0x09, 0x11, 0x01, 0x3e, 0x1e, 0x2e, 0x0e, 0x36, 0x16, 0x26, 0x06, 0x3a, 0x1a, 0x2a, 0x0a, 0x32, 0x12, 0x22, 0x42, 0x02, 0x7c, 0x3c, 0x5c, 0x1c, 0x6c, 0x2c, 0x4c, 0x0c, 0x74, 0x34, 0x54, 0x14, 0x64, 0x24, 0x44, 0x04, 0x78, 0x38, 0x58, 0x18, 0x68, 0x28, 0x48, 0x08, 0xf0, 0x70, 0xb0, 0x30, 0xd0, 0x50, 0x90, 0x10, 0xe0, 0x60, 0xa0, 0x20, 0xc0, 0x40, 0x80, 0x00],
    ExLenBits: [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8],
    LenBase: [0x0000, 0x0001, 0x0002, 0x0003, 0x0004, 0x0005, 0x0006, 0x0007, 0x0008, 0x000a, 0x000e, 0x0016, 0x0026, 0x0046, 0x0086, 0x0106],
    LenBits: [3, 2, 3, 3, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 7, 7],
    LenCode: [0x05, 0x03, 0x01, 0x06, 0x0a, 0x02, 0x0c, 0x14, 0x04, 0x18, 0x08, 0x30, 0x10, 0x20, 0x40, 0x00],
    ChBitsAsc: [
      0x0b, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x08, 0x07, 0x0c, 0x0c, 0x07, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0d, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c,
      0x04, 0x0a, 0x08, 0x0c, 0x0a, 0x0c, 0x0a, 0x08, 0x07, 0x07, 0x08, 0x09, 0x07, 0x06, 0x07, 0x08, 0x07, 0x06, 0x07, 0x07, 0x07, 0x07, 0x08, 0x07, 0x07, 0x08, 0x08, 0x0c, 0x0b, 0x07, 0x09, 0x0b,
      0x0c, 0x06, 0x07, 0x06, 0x06, 0x05, 0x07, 0x08, 0x08, 0x06, 0x0b, 0x09, 0x06, 0x07, 0x06, 0x06, 0x07, 0x0b, 0x06, 0x06, 0x06, 0x07, 0x09, 0x08, 0x09, 0x09, 0x0b, 0x08, 0x0b, 0x09, 0x0c, 0x08,
      0x0c, 0x05, 0x06, 0x06, 0x06, 0x05, 0x06, 0x06, 0x06, 0x05, 0x0b, 0x07, 0x05, 0x06, 0x05, 0x05, 0x06, 0x0a, 0x05, 0x05, 0x05, 0x05, 0x08, 0x07, 0x08, 0x08, 0x0a, 0x0b, 0x0b, 0x0c, 0x0c, 0x0c,
      0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d,
      0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c,
      0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c, 0x0c,
      0x0d, 0x0c, 0x0d, 0x0d, 0x0d, 0x0c, 0x0d, 0x0d, 0x0d, 0x0c, 0x0d, 0x0d, 0x0d, 0x0d, 0x0c, 0x0d, 0x0d, 0x0d, 0x0c, 0x0c, 0x0c, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d, 0x0d,
    ],
    ChCodeAsc: [
      0x0490, 0x0fe0, 0x07e0, 0x0be0, 0x03e0, 0x0de0, 0x05e0, 0x09e0, 0x01e0, 0x00b8, 0x0062, 0x0ee0, 0x06e0, 0x0022, 0x0ae0, 0x02e0,
      0x0ce0, 0x04e0, 0x08e0, 0x00e0, 0x0f60, 0x0760, 0x0b60, 0x0360, 0x0d60, 0x0560, 0x1240, 0x0960, 0x0160, 0x0e60, 0x0660, 0x0a60,
      0x000f, 0x0250, 0x0038, 0x0260, 0x0050, 0x0c60, 0x0390, 0x00d8, 0x0042, 0x0002, 0x0058, 0x01b0, 0x007c, 0x0029, 0x003c, 0x0098,
      0x005c, 0x0009, 0x001c, 0x006c, 0x002c, 0x004c, 0x0018, 0x000c, 0x0074, 0x00e8, 0x0068, 0x0460, 0x0090, 0x0034, 0x00b0, 0x0710,
      0x0860, 0x0031, 0x0054, 0x0011, 0x0021, 0x0017, 0x0014, 0x00a8, 0x0028, 0x0001, 0x0310, 0x0130, 0x003e, 0x0064, 0x001e, 0x002e,
      0x0024, 0x0510, 0x000e, 0x0036, 0x0016, 0x0044, 0x0030, 0x00c8, 0x01d0, 0x00d0, 0x0110, 0x0048, 0x0610, 0x0150, 0x0060, 0x0088,
      0x0fa0, 0x0007, 0x0026, 0x0006, 0x003a, 0x001b, 0x001a, 0x002a, 0x000a, 0x000b, 0x0210, 0x0004, 0x0013, 0x0032, 0x0003, 0x001d,
      0x0012, 0x0190, 0x000d, 0x0015, 0x0005, 0x0019, 0x0008, 0x0078, 0x00f0, 0x0070, 0x0290, 0x0410, 0x0010, 0x07a0, 0x0ba0, 0x03a0,
      0x0240, 0x1c40, 0x0c40, 0x1440, 0x0440, 0x1840, 0x0840, 0x1040, 0x0040, 0x1f80, 0x0f80, 0x1780, 0x0780, 0x1b80, 0x0b80, 0x1380,
      0x0380, 0x1d80, 0x0d80, 0x1580, 0x0580, 0x1980, 0x0980, 0x1180, 0x0180, 0x1e80, 0x0e80, 0x1680, 0x0680, 0x1a80, 0x0a80, 0x1280,
      0x0280, 0x1c80, 0x0c80, 0x1480, 0x0480, 0x1880, 0x0880, 0x1080, 0x0080, 0x1f00, 0x0f00, 0x1700, 0x0700, 0x1b00, 0x0b00, 0x1300,
      0x0da0, 0x05a0, 0x09a0, 0x01a0, 0x0ea0, 0x06a0, 0x0aa0, 0x02a0, 0x0ca0, 0x04a0, 0x08a0, 0x00a0, 0x0f20, 0x0720, 0x0b20, 0x0320,
      0x0d20, 0x0520, 0x0920, 0x0120, 0x0e20, 0x0620, 0x0a20, 0x0220, 0x0c20, 0x0420, 0x0820, 0x0020, 0x0fc0, 0x07c0, 0x0bc0, 0x03c0,
      0x0dc0, 0x05c0, 0x09c0, 0x01c0, 0x0ec0, 0x06c0, 0x0ac0, 0x02c0, 0x0cc0, 0x04c0, 0x08c0, 0x00c0, 0x0f40, 0x0740, 0x0b40, 0x0340,
      0x0300, 0x0d40, 0x1d00, 0x0d00, 0x1500, 0x0540, 0x0500, 0x1900, 0x0900, 0x0940, 0x1100, 0x0100, 0x1e00, 0x0e00, 0x0140, 0x1600,
      0x0600, 0x1a00, 0x0e40, 0x0640, 0x0a40, 0x0a00, 0x1200, 0x0200, 0x1c00, 0x0c00, 0x1400, 0x0400, 0x1800, 0x0800, 0x1000, 0x0000,
    ],
  };
  // Prefix codes are stored LSB-first, so a code of length L is the low L bits of the stream:
  // one flat lookup table per alphabet (indexed by the next `tableBits` bits) decodes it.
  function pkTable(codes, lens, tableBits) {
    const t = new Int16Array(1 << tableBits).fill(-1);
    for (let s = 0; s < codes.length; s++) {
      const step = 1 << lens[s];
      for (let k = codes[s] & (step - 1); k < t.length; k += step) t[k] = s;
    }
    return t;
  }
  let PK_TABLES = null;
  function pkTables() {
    if (!PK_TABLES) {
      PK_TABLES = {
        len: pkTable(PK.LenCode, PK.LenBits, 7),
        dist: pkTable(PK.DistCode, PK.DistBits, 8),
        lit: pkTable(PK.ChCodeAsc, PK.ChBitsAsc, 13),
      };
    }
    return PK_TABLES;
  }

  function explode(src, maxOut) {
    if (src.length <= 4) throw new Error('pkware: bad data');
    const ctype = src[0];
    const dbits = src[1];
    if (dbits < 4 || dbits > 6) throw new Error('pkware: invalid dictionary size');
    if (ctype !== 0 && ctype !== 1) throw new Error('pkware: invalid mode');
    const T = pkTables();
    let p = 2, buf = 0, cnt = 0;
    const need = (n) => {
      while (cnt < n) {
        buf |= (p < src.length ? src[p] : 0) << cnt;
        p++;
        cnt += 8;
      }
    };
    const peek = (n) => { need(n); return buf & ((1 << n) - 1); };
    const skip = (n) => { need(n); buf >>>= n; cnt -= n; };
    const take = (n) => { const v = peek(n); skip(n); return v; };
    const out = new Uint8Array(maxOut);
    let o = 0;
    while (o < maxOut) {
      if (p > src.length + 2) break; // ran out of input without an end marker
      if (take(1)) {
        const code = T.len[peek(7)];
        skip(PK.LenBits[code]);
        const extra = PK.ExLenBits[code];
        const len = PK.LenBase[code] + (extra ? take(extra) : 0);
        if (len === 0x205) break; // end of stream (literal 0x305)
        const rep = len + 2;
        const dcode = T.dist[peek(8)];
        skip(PK.DistBits[dcode]);
        const dist = (rep === 2 ? (dcode << 2) | take(2) : (dcode << dbits) | take(dbits)) + 1;
        for (let k = 0; k < rep && o < maxOut; k++, o++) out[o] = o - dist >= 0 ? out[o - dist] : 0;
      } else if (ctype === 0) {
        out[o++] = take(8);
      } else {
        const s = T.lit[peek(13)];
        if (s < 0) throw new Error('pkware: bad literal code');
        skip(PK.ChBitsAsc[s]);
        out[o++] = s;
      }
    }
    return o === maxOut ? out : out.subarray(0, o);
  }

  // ---------------------------------------------------------------------------------------------
  // Huffman (0x01) — StormLib's adaptive (FGK) tree, ported item for item (quick-links omitted:
  // they only cache tree walks and never change which bits are consumed).

  const HUFF_DIST = (() => {
    const z = (n) => new Array(n).fill(0);
    const row = (arr) => arr;
    const sparse = [0x0a, ...z(254), 0x02, 0, 0];
    const binary = row([
      0x54, 0x16, 0x16, 0x0d, 0x0c, 0x08, 0x06, 0x05, 0x06, 0x05, 0x06, 0x03, 0x04, 0x04, 0x03, 0x05, 0x0e, 0x0b, 0x14, 0x13, 0x13, 0x09, 0x0b, 0x06, 0x05, 0x04, 0x03, 0x02, 0x03, 0x02, 0x02, 0x02,
      0x0d, 0x07, 0x09, 0x06, 0x06, 0x04, 0x03, 0x02, 0x04, 0x03, 0x03, 0x03, 0x03, 0x03, 0x02, 0x02, 0x09, 0x06, 0x04, 0x04, 0x04, 0x04, 0x03, 0x02, 0x03, 0x02, 0x02, 0x02, 0x02, 0x03, 0x02, 0x04,
      0x08, 0x03, 0x04, 0x07, 0x09, 0x05, 0x03, 0x03, 0x03, 0x03, 0x02, 0x02, 0x02, 0x03, 0x02, 0x02, 0x03, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x01, 0x01, 0x01, 0x02, 0x01, 0x02, 0x02,
      0x06, 0x0a, 0x08, 0x08, 0x06, 0x07, 0x04, 0x03, 0x04, 0x04, 0x02, 0x02, 0x04, 0x02, 0x03, 0x03, 0x04, 0x03, 0x07, 0x07, 0x09, 0x06, 0x04, 0x03, 0x03, 0x02, 0x01, 0x02, 0x02, 0x02, 0x02, 0x02,
      0x0a, 0x02, 0x02, 0x03, 0x02, 0x02, 0x01, 0x01, 0x02, 0x02, 0x02, 0x06, 0x03, 0x05, 0x02, 0x03, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x03, 0x01, 0x01, 0x01,
      0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x04, 0x04, 0x04, 0x07, 0x09, 0x08, 0x0c, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x03,
      0x04, 0x01, 0x02, 0x04, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x04, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01,
      0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x03, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x02, 0x01, 0x01, 0x02, 0x02, 0x02, 0x06, 0x4b,
    ]);
    const text = [
      0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x27, 0x00, 0x00, 0x23, 0x00, 0x00, ...z(16),
      0xff, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x02, 0x01, 0x01, 0x06, 0x0e, 0x10, 0x04, 0x06, 0x08, 0x05, 0x04, 0x04, 0x03, 0x03, 0x02, 0x02, 0x03, 0x03, 0x01, 0x01, 0x02, 0x01, 0x01,
      0x01, 0x04, 0x02, 0x04, 0x02, 0x02, 0x02, 0x01, 0x01, 0x04, 0x01, 0x01, 0x02, 0x03, 0x03, 0x02, 0x03, 0x01, 0x03, 0x06, 0x04, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x02, 0x01, 0x01,
      0x01, 0x29, 0x07, 0x16, 0x12, 0x40, 0x0a, 0x0a, 0x11, 0x25, 0x01, 0x03, 0x17, 0x10, 0x26, 0x2a, 0x10, 0x01, 0x23, 0x23, 0x2f, 0x10, 0x06, 0x07, 0x02, 0x09, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00,
      ...z(128), 0, 0,
    ];
    const general = [
      0xff, 0x0b, 0x07, 0x05, 0x0b, 0x02, 0x02, 0x02, 0x06, 0x02, 0x02, 0x01, 0x04, 0x02, 0x01, 0x03, 0x09, 0x01, 0x01, 0x01, 0x03, 0x04, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01,
      0x05, 0x01, 0x01, 0x01, 0x0d, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x03, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01,
      0x0a, 0x04, 0x02, 0x01, 0x06, 0x03, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x03, 0x01, 0x01, 0x01, 0x05, 0x02, 0x03, 0x04, 0x03, 0x03, 0x03, 0x02, 0x01, 0x01, 0x01, 0x02, 0x01, 0x02, 0x03, 0x03,
      0x01, 0x03, 0x01, 0x01, 0x02, 0x05, 0x01, 0x01, 0x04, 0x03, 0x05, 0x01, 0x03, 0x01, 0x03, 0x03, 0x02, 0x01, 0x04, 0x03, 0x0a, 0x06, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01,
      0x02, 0x02, 0x01, 0x0a, 0x02, 0x05, 0x01, 0x01, 0x02, 0x07, 0x02, 0x17, 0x01, 0x05, 0x01, 0x01, 0x0e, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01,
      0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01,
      0x06, 0x02, 0x01, 0x04, 0x05, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01,
      0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x07, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x11,
      0, 0,
    ];
    const adpcm4 = [0xff, 0xfb, 0x98, 0x9a, 0x84, 0x85, 0x63, 0x64, 0x3e, 0x3e, 0x22, 0x22, 0x13, 0x13, 0x18, 0x17, ...z(242)];
    const adpcm6 = [
      0xff, 0xf1, 0x9d, 0x9e, 0x9a, 0x9b, 0x9a, 0x97, 0x93, 0x93, 0x8c, 0x8e, 0x86, 0x88, 0x80, 0x82, 0x7c, 0x7c, 0x72, 0x73, 0x69, 0x6b, 0x5f, 0x60, 0x55, 0x56, 0x4a, 0x4b, 0x40, 0x41, 0x37, 0x37,
      0x2f, 0x2f, 0x27, 0x27, 0x21, 0x21, 0x1b, 0x1c, 0x17, 0x17, 0x13, 0x13, 0x10, 0x10, 0x0d, 0x0d, 0x0b, 0x0b, 0x09, 0x09, 0x08, 0x08, 0x07, 0x07, 0x06, 0x05, 0x05, 0x04, 0x04, 0x04, 0x19, 0x18,
      ...z(194),
    ];
    const st3 = [0xc3, 0xcb, 0xf5, 0x41, 0xff, 0x7b, 0xf7, 0x21, ...z(56), 0xbf, 0xcc, 0xf2, 0x40, 0xfd, 0x7c, 0xf7, 0x22, ...z(56), 0x7a, 0x46, ...z(126)];
    const st4 = [
      0xc3, 0xd9, 0xef, 0x3d, 0xf9, 0x7c, 0xe9, 0x1e, 0xfd, 0xab, 0xf1, 0x2c, 0xfc, 0x5b, 0xfe, 0x17, ...z(48),
      0xbd, 0xd9, 0xec, 0x3d, 0xf5, 0x7d, 0xe8, 0x1d, 0xfb, 0xae, 0xf0, 0x2c, 0xfb, 0x5c, 0xff, 0x18, ...z(48),
      0x70, 0x6c, ...z(126),
    ];
    const st5 = [
      0xba, 0xc5, 0xda, 0x33, 0xe3, 0x6d, 0xd8, 0x18, 0xe5, 0x94, 0xda, 0x23, 0xdf, 0x4a, 0xd1, 0x10, 0xee, 0xaf, 0xe4, 0x2c, 0xea, 0x5a, 0xde, 0x15, 0xf4, 0x87, 0xe9, 0x21, 0xf6, 0x43, 0xfc, 0x12, ...z(32),
      0xb0, 0xc7, 0xd8, 0x33, 0xe3, 0x6b, 0xd6, 0x18, 0xe7, 0x95, 0xd8, 0x23, 0xdb, 0x49, 0xd0, 0x11, 0xe9, 0xb2, 0xe2, 0x2b, 0xe8, 0x5c, 0xdd, 0x15, 0xf1, 0x87, 0xe7, 0x20, 0xf7, 0x44, 0xff, 0x13, ...z(32),
      0x5f, 0x9e, ...z(126),
    ];
    const all = [sparse, binary, text, general, adpcm4, adpcm6, st3, st4, st5];
    for (const t of all) if (t.length < 256) throw new Error('huffman table length ' + t.length);
    return all;
  })();

  function huffmanDecompress(src, maxOut) {
    // Input bit stream (LSB-first), as TInputStream.
    let p = 0, bitBuf = 0, bitCnt = 0;
    const get1 = () => {
      if (bitCnt === 0) {
        if (p >= src.length) return -1;
        bitBuf = src[p++];
        bitCnt = 8;
      }
      const v = bitBuf & 1;
      bitBuf >>>= 1;
      bitCnt--;
      return v;
    };
    const get8 = () => {
      if (bitCnt < 8) {
        if (p >= src.length) return -1;
        bitBuf |= src[p++] << bitCnt;
        bitCnt += 8;
      }
      const v = bitBuf & 0xff;
      bitBuf >>>= 8;
      bitCnt -= 8;
      return v;
    };
    if (maxOut === 0) return new Uint8Array(0);
    const dataType = get8();
    if (dataType < 0) return new Uint8Array(0);
    const isSparse = dataType === 0;
    const dt = dataType & 0x0f;
    if (dt >= HUFF_DIST.length) throw new Error('huffman: bad data type');
    const dist = HUFF_DIST[dt];

    // The weight-sorted circular list with a sentinel head (next = higher weight end).
    const head = { next: null, prev: null, value: 0, weight: 0, parent: null, childLo: null };
    head.next = head.prev = head;
    let used = 0;
    const byByte = new Array(258).fill(null);
    const removeItem = (it) => {
      if (it.next !== null) {
        it.prev.next = it.next;
        it.next.prev = it.prev;
        it.next = it.prev = null;
      }
    };
    const linkTwo = (i1, i2) => {
      i2.next = i1.next;
      i2.prev = i1.next.prev;
      i1.next.prev = i2;
      i1.next = i2;
    };
    const insertItem = (it, after, at) => {
      removeItem(it);
      if (at === null) at = head;
      if (after) linkTwo(at, it);
      else linkTwo(at.prev, it);
    };
    const findHigherOrEqual = (it, weight) => {
      if (it !== null) {
        while (it !== head) {
          if (it.weight >= weight) return it;
          it = it.prev;
        }
      }
      return head;
    };
    const createItem = (value, weight, after) => {
      if (used >= 515) return null;
      used++;
      const it = { next: null, prev: null, value, weight, parent: null, childLo: null };
      insertItem(it, after, null);
      return it;
    };
    const fixupByWeight = (it, maxWeight) => {
      if (it.weight < maxWeight) {
        const higher = findHigherOrEqual(head.prev, it.weight);
        removeItem(it);
        linkTwo(higher, it);
      } else {
        maxWeight = it.weight;
      }
      return maxWeight;
    };
    // BuildTree
    let maxWeight = 0;
    for (let i = 0; i < 0x100; i++) {
      if (dist[i] !== 0) {
        const it = (byByte[i] = createItem(i, dist[i], true));
        maxWeight = fixupByWeight(it, maxWeight);
      }
    }
    byByte[0x100] = createItem(0x100, 1, false);
    byByte[0x101] = createItem(0x101, 1, false);
    let lo = head.prev;
    while (lo !== head) {
      const hi = lo.prev;
      if (hi === head) break;
      const parent = createItem(0, hi.weight + lo.weight, true);
      if (parent === null) throw new Error('huffman: tree overflow');
      lo.parent = parent;
      hi.parent = parent;
      parent.childLo = lo;
      maxWeight = fixupByWeight(parent, maxWeight);
      lo = hi.prev;
    }
    const incWeights = (it) => {
      for (; it !== null; it = it.parent) {
        it.weight++;
        const higher = findHigherOrEqual(it.prev, it.weight);
        const childHi = higher.next;
        if (childHi !== it) {
          removeItem(childHi);
          linkTwo(it, childHi);
          removeItem(it);
          linkTwo(higher, it);
          const childLo = childHi.parent.childLo;
          let parent = it.parent;
          if (parent.childLo === it) parent.childLo = childHi;
          if (childLo === childHi) childHi.parent.childLo = it;
          parent = it.parent;
          it.parent = childHi.parent;
          childHi.parent = parent;
        }
      }
    };
    const insertNewBranch = (v1, v2) => {
      const last = head.prev;
      const childHi = createItem(v1, last.weight, false);
      if (childHi === null) return false;
      childHi.parent = last;
      byByte[v1] = childHi;
      const childLo = createItem(v2, 0, false);
      if (childLo === null) return false;
      childLo.parent = last;
      last.childLo = childLo;
      byByte[v2] = childLo;
      incWeights(childLo);
      return true;
    };
    const decodeOne = () => {
      if (head.next === head) return 0x1ff;
      let it = head.next;
      while (it.childLo !== null) {
        const b = get1();
        if (b < 0) return 0x1ff;
        it = b ? it.childLo.prev : it.childLo;
      }
      return it.value;
    };
    const out = new Uint8Array(maxOut);
    let o = 0;
    for (;;) {
      let v = decodeOne();
      if (v === 0x100) break;
      if (v === 0x1ff) throw new Error('huffman: corrupt stream');
      if (v === 0x101) {
        v = get8();
        if (v < 0) throw new Error('huffman: corrupt stream');
        if (!insertNewBranch(head.prev.value, v)) throw new Error('huffman: tree overflow');
        if (!isSparse) incWeights(byByte[v]);
      }
      if (o >= maxOut) break;
      out[o++] = v;
      if (isSparse) incWeights(byByte[v]);
    }
    return o === maxOut ? out : out.subarray(0, o);
  }

  // ---------------------------------------------------------------------------------------------
  // IMA ADPCM (0x40 mono, 0x80 stereo), as StormLib's DecompressADPCM.

  const ADPCM_NEXT = [-1, 0, -1, 4, -1, 2, -1, 6, -1, 1, -1, 5, -1, 3, -1, 7, -1, 1, -1, 5, -1, 3, -1, 7, -1, 2, -1, 4, -1, 6, -1, 8];
  const ADPCM_STEP = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493,
    10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
  ];
  function adpcmDecompress(src, maxOut, channels) {
    const out = new Uint8Array(maxOut);
    let o = 0, p = 0;
    const writeWord = (v) => {
      if (maxOut - o < 2) return false;
      out[o++] = v & 0xff;
      out[o++] = (v >> 8) & 0xff;
      return true;
    };
    const pred = [0, 0];
    const stepIdx = [0x2c, 0x2c];
    if (p < src.length) p++;
    let shift = 0;
    if (p < src.length) shift = src[p++];
    for (let i = 0; i < channels; i++) {
      if (src.length - p < 2) return out.subarray(0, o);
      const s = ((src[p] | (src[p + 1] << 8)) << 16) >> 16;
      p += 2;
      pred[i] = s;
      if (!writeWord(s)) return out.subarray(0, o);
    }
    let ch = channels - 1;
    while (p < src.length) {
      const enc = src[p++];
      ch = (ch + 1) % channels;
      if (enc === 0x80) {
        if (stepIdx[ch] !== 0) stepIdx[ch]--;
        if (!writeWord(pred[ch])) return out.subarray(0, o);
      } else if (enc === 0x81) {
        stepIdx[ch] += 8;
        if (stepIdx[ch] > 0x58) stepIdx[ch] = 0x58;
        ch = (ch + 1) % channels;
      } else {
        const si = stepIdx[ch];
        const step = ADPCM_STEP[si];
        let diff = step >> shift;
        if (enc & 0x01) diff += step >> 0;
        if (enc & 0x02) diff += step >> 1;
        if (enc & 0x04) diff += step >> 2;
        if (enc & 0x08) diff += step >> 3;
        if (enc & 0x10) diff += step >> 4;
        if (enc & 0x20) diff += step >> 5;
        let s = pred[ch];
        if (enc & 0x40) { s -= diff; if (s <= -32768) s = -32768; }
        else { s += diff; if (s >= 32767) s = 32767; }
        pred[ch] = (s << 16) >> 16;
        if (!writeWord(pred[ch])) break;
        let ni = si + ADPCM_NEXT[enc & 0x1f];
        if (ni < 0) ni = 0; else if (ni > 88) ni = 88;
        stepIdx[ch] = ni;
      }
    }
    return out.subarray(0, o);
  }

  // ---------------------------------------------------------------------------------------------
  // Sparse (0x20)

  function sparseDecompress(src, maxOut) {
    if (src.length < 5) throw new Error('sparse: too short');
    let total = ((src[0] << 24) | (src[1] << 16) | (src[2] << 8) | src[3]) >>> 0;
    if (total > maxOut) throw new Error('sparse: output larger than the sector');
    const out = new Uint8Array(total);
    let p = 4, o = 0, left = total;
    while (p < src.length) {
      const b = src[p++];
      if (b & 0x80) {
        let n = (b & 0x7f) + 1;
        if (p + n > src.length) throw new Error('sparse: chunk past the end');
        const c = Math.min(n, left);
        out.set(src.subarray(p, p + c), o);
        p += n;
        o += c;
        left -= c;
      } else {
        const c = Math.min((b & 0x7f) + 3, left);
        o += c; // already zero
        left -= c;
      }
    }
    return out;
  }

  const api = {
    FLAG,
    MpqError,
    MpqArchive,
    blobSource,
    bytesSource,
    hashString,
    nameHashes,
    decryptBytes,
    encryptBytes,
    HASH: { TABLE_OFFSET: HASH_TABLE_OFFSET, NAME_A: HASH_NAME_A, NAME_B: HASH_NAME_B, FILE_KEY: HASH_FILE_KEY },
    codecs: { inflate, inflateSync, inflateStream, bunzip2, explode, huffmanDecompress, adpcmDecompress, sparseDecompress, decompressMask },
  };
  root.WUMpq = api;
  if (typeof module === 'object' && module && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : self);
