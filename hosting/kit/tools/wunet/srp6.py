"""WoW SRP6 as AzerothCore 3.3.5a does it (src/common/Cryptography/Authentication/SRP6.cpp).

N = 0x894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7, g = 7, k = 3.
Every number is little endian on the wire and in the database (salt, verifier: 32 bytes).

  x  = SHA1(salt | SHA1(UPPER(user) ":" UPPER(pass)))          (little-endian integer)
  v  = g^x mod N                                                  (account.verifier)
  B  = (k*v + g^b) mod N            A = g^a mod N                 u = SHA1(A | B)
  S  = (B - k*g^x)^(a + u*x) mod N  (client) = (A * v^u)^b mod N  (server)
  K  = SHA1-interleave(S)           (40 bytes, the session key)
  M1 = SHA1(SHA1(N) xor SHA1(g) | SHA1(UPPER(user)) | salt | A | B | K)
  M2 = SHA1(A | M1 | K)

Interleave and width: AzerothCore hashes A, B, salt at 32 bytes; its interleave skips leading
zero bytes of S (the low end, S being little endian), as the real client does. The client below
redraws `a` until S has a non-zero low byte and A a non-zero high byte, so every implementation
(trimming or not) computes the same K: the same rule benilla-srp follows.
"""
import hashlib
import os

N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
G = 7
K_MULT = 3
N_BYTES = N.to_bytes(32, "little")


def sha1(*parts: bytes) -> bytes:
    h = hashlib.sha1()
    for p in parts:
        h.update(p)
    return h.digest()


def le(b: bytes) -> int:
    return int.from_bytes(b, "little")


def to32(n: int) -> bytes:
    return n.to_bytes(32, "little")


def calc_x(user: str, password: str, salt: bytes) -> int:
    inner = sha1(f"{user.upper()}:{password.upper()}".encode())
    return le(sha1(salt, inner))


def new_salt() -> bytes:
    """32 random bytes whose most significant (last) byte is not 0: the MaNGOS-family cores (the host kit's 1.12.1
    and 2.4.3 profiles) store and send the salt without leading zeros, so such a salt would come out 31 bytes."""
    while True:
        s = os.urandom(32)
        if s[-1]:
            return s


def make_verifier(user: str, password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """(salt, verifier) for acore_auth.account, as AzerothCore's account create makes them."""
    salt = salt or new_salt()
    v = pow(G, calc_x(user, password, salt), N)
    return salt, to32(v)


def interleave(S: bytes) -> bytes:
    """AzerothCore SRP6::SHA1Interleave (skips leading zero bytes in pairs)."""
    p = 0
    while p < 32 and S[p] == 0:
        p += 1
    if p & 1:
        p += 1
    p //= 2
    even = bytes(S[2 * i] for i in range(16))[p:]
    odd = bytes(S[2 * i + 1] for i in range(16))[p:]
    h0, h1 = sha1(even), sha1(odd)
    out = bytearray(40)
    for i in range(20):
        out[2 * i] = h0[i]
        out[2 * i + 1] = h1[i]
    return bytes(out)


def ng_hash() -> bytes:
    hn, hg = sha1(N_BYTES), sha1(bytes([G]))
    return bytes(a ^ b for a, b in zip(hn, hg))


def client_proof(user: str, salt: bytes, A: bytes, B: bytes, K: bytes) -> bytes:
    return sha1(ng_hash(), sha1(user.upper().encode()), salt, A, B, K)


def server_proof(A: bytes, M1: bytes, K: bytes) -> bytes:
    return sha1(A, M1, K)


class Client:
    """The client side of one logon: feed it the server's B and salt, read A and M1."""

    def __init__(self, user: str, password: str):
        self.user, self.password = user.upper(), password.upper()
        self.A = self.M1 = self.K = None

    def process(self, B: bytes, salt: bytes, g: int = G, n: int = N, rand=os.urandom):
        if g != G or n != N:
            raise ValueError("server uses unexpected SRP6 parameters")
        Bi = le(B)
        if Bi % N == 0:
            raise ValueError("server sent B = 0 mod N")
        x = calc_x(self.user, self.password, salt)
        for _ in range(64):
            a = le(rand(19)) | 1
            Ai = pow(G, a, N)
            A = to32(Ai)
            if A[31] == 0:
                continue
            u = le(sha1(A, B))
            if u == 0:
                continue
            S = to32(pow((Bi - K_MULT * pow(G, x, N)) % N, a + u * x, N))
            if S[0] == 0:
                continue
            self.A, self.K = A, interleave(S)
            self.M1 = client_proof(self.user, salt, A, B, self.K)
            return self.A, self.M1
        raise RuntimeError("could not draw an unambiguous SRP6 key")

    def check_server(self, M2: bytes) -> bool:
        return M2 == server_proof(self.A, self.M1, self.K)


class Server:
    """The server side (for the fake authserver in tests), mirroring AzerothCore."""

    def __init__(self, user: str, salt: bytes, verifier: bytes, rand=os.urandom):
        self.user, self.salt, self.v = user.upper(), salt, le(verifier)
        self.b = le(rand(19))
        self.B = to32((K_MULT * self.v + pow(G, self.b, N)) % N)

    def verify(self, A: bytes, M1: bytes):
        """The session key K and M2 when M1 is right, else None."""
        Ai = le(A)
        if Ai % N == 0:
            return None
        u = le(sha1(A, self.B))
        S = to32(pow(Ai * pow(self.v, u, N), self.b, N))
        K = interleave(S)
        if client_proof(self.user, self.salt, A, self.B, K) != M1:
            return None
        return K, server_proof(A, M1, K)
