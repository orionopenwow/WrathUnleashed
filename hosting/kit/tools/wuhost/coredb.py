"""The realm's databases on the host kit's other cores (cores.py), with the same calls as agent.RealmDB
(AzerothCore): set_realm_address, create_account, grant_gm, status. Picked with WU_CORE (the profile's compose
file sets it, with WU_DB_AUTH / WU_DB_CHARS / WU_EXPANSION).

Accounts arrive from the relay as AzerothCore keeps them: salt and verifier as 32 little-endian bytes in hex,
computed in the player's browser (wunet/srp6.py; the host never sees a password). The SRP6 itself is the same on
every core here (N, g = 7, k = 3, SHA1, x = SHA1(salt | SHA1(USER:PASS))), only the storage differs:

  * cmangos (1.12.1, 2.4.3): account.s / account.v are upper-case hex of the big-endian number
    (BigNumber::AsHexStr). The realmd sends the salt as s.AsByteArray() with no fixed width and hashes it
    the same way, so a salt whose most significant byte is 0 would come out 31 bytes long and the login fails:
    such a salt is refused ("bad_salt"; the join pages never draw one). GM rights: account.gmlevel.
    The test vector is the core's own: sql/base/realmd.sql's ADMINISTRATOR row (hosting/tests).
  * trinitycore (4.3.4, the preservation fork): account.salt / account.verifier binary(32), the same bytes as
    AzerothCore. GM rights: account_access (AccountID, SecurityLevel, RealmID = -1).

VMaNGOS (the paused Hordes profile) has its own module, wuhost/vmangos.py, on that branch; db_class() uses it
when it is there.
"""
import os
import time

from .agent import RealmDB


def to_mangos_hex(le_hex):
    """32 little-endian bytes as hex (AzerothCore, the relay) -> the MaNGOS family's big-endian upper-case hex."""
    b = bytes.fromhex(le_hex)
    if len(b) != 32:
        raise ValueError("salt and verifier are 32 bytes")
    return format(int.from_bytes(b, "little"), "X")


def from_mangos_hex(hx):
    """The other way (tests, the self-check): MaNGOS hex -> 32 little-endian bytes."""
    return int(hx, 16).to_bytes(32, "little")


def salt_ok(le_hex):
    """A salt every core stores and sends at 32 bytes: its most significant (last) byte is not 0."""
    b = bytes.fromhex(le_hex)
    return len(b) == 32 and b[-1] != 0


class CmangosDB(RealmDB):
    def __init__(self, host, port, user, password, realm_db_id=1, auth="classicrealmd", chars="classiccharacters",
                 expansion=0):
        super().__init__(host, port, user, password, realm_db_id)
        self.AUTH, self.CHARS, self.expansion = auth, chars, int(expansion)

    def set_realm_address(self, name, address, port):
        c = self._conn(self.AUTH)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT name, address, port FROM realmlist WHERE id = %s", (self.realm_db_id,))
                row = cur.fetchone()
                if row is None:
                    return "no realmlist row yet"
                if tuple(row) == (name, address, port):
                    return "unchanged"
                cur.execute("UPDATE realmlist SET name = %s, address = %s, port = %s WHERE id = %s",
                            (name, address, port, self.realm_db_id))
                return "updated"
        finally:
            c.close()

    def create_account(self, username, salt, verifier, gmlevel=0):
        if not salt_ok(salt):
            return "bad_salt"
        s, v = to_mangos_hex(salt), to_mangos_hex(verifier)
        c = self._conn(self.AUTH)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM account WHERE username = %s", (username,))
                if cur.fetchone():
                    return "taken"
                cur.execute("INSERT INTO account (username, gmlevel, v, s, joindate, expansion) "
                            "VALUES (%s, %s, %s, %s, NOW(), %s)", (username, int(gmlevel), v, s, self.expansion))
                # as the core's own `account create` does (AccountMgr::CreateAccount)
                cur.execute("INSERT INTO realmcharacters (realmid, acctid, numchars) SELECT realmlist.id, account.id, 0 "
                            "FROM realmlist, account LEFT JOIN realmcharacters ON acctid = account.id "
                            "WHERE acctid IS NULL")
                return "ok"
        finally:
            c.close()

    def set_login(self, username, salt, verifier):
        """Hero Key sign-in: a new salt + verifier (see agent.RealmDB.set_login)."""
        if not salt_ok(salt):
            return "bad_salt"
        c = self._conn(self.AUTH)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM account WHERE username = %s", (username,))
                if not cur.fetchone():
                    return "missing"
                cur.execute("UPDATE account SET v = %s, s = %s WHERE username = %s",
                            (to_mangos_hex(verifier), to_mangos_hex(salt), username))
                return "updated"
        finally:
            c.close()

    def grant_gm(self, username, gmlevel=3):
        c = self._conn(self.AUTH)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT gmlevel FROM account WHERE username = %s", (username.upper(),))
                row = cur.fetchone()
                if not row:
                    return "missing"
                if int(row[0]) == gmlevel:
                    return "unchanged"
                cur.execute("UPDATE account SET gmlevel = %s WHERE username = %s", (gmlevel, username.upper()))
                return "ok"
        finally:
            c.close()

    def status(self):
        c = self._conn(self.CHARS)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM characters WHERE online = 1")
                players = cur.fetchone()[0]
                cur.execute(f"SELECT starttime FROM `{self.AUTH}`.uptime WHERE realmid = %s ORDER BY starttime DESC "
                            "LIMIT 1", (self.realm_db_id,))
                row = cur.fetchone()
            return {"players": int(players or 0), "bots": 0,
                    "uptime_s": int(time.time() - row[0]) if row else None, "bots_method": "none"}
        finally:
            c.close()


class TrinityDB(RealmDB):
    """TrinityCore 4.3.4 (auth / characters): AzerothCore's account bytes, TrinityCore's account_access columns."""

    def __init__(self, host, port, user, password, realm_db_id=1, auth="auth", chars="characters", expansion=3):
        super().__init__(host, port, user, password, realm_db_id)
        self.AUTH, self.CHARS, self.expansion = auth, chars, int(expansion)

    def set_realm_address(self, name, address, port):
        c = self._conn(self.AUTH)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT name, address, localAddress, port FROM realmlist WHERE id = %s", (self.realm_db_id,))
                row = cur.fetchone()
                if row is None:
                    return "no realmlist row yet"
                if tuple(row) == (name, address, address, port):
                    return "unchanged"
                cur.execute("UPDATE realmlist SET name = %s, address = %s, localAddress = %s, port = %s WHERE id = %s",
                            (name, address, address, port, self.realm_db_id))
                return "updated"
        finally:
            c.close()

    def create_account(self, username, salt, verifier, gmlevel=0):
        if not salt_ok(salt):
            return "bad_salt"
        c = self._conn(self.AUTH)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM account WHERE username = %s", (username,))
                if cur.fetchone():
                    return "taken"
                cur.execute("INSERT INTO account (username, salt, verifier, expansion) VALUES (%s, %s, %s, %s)",
                            (username, bytes.fromhex(salt), bytes.fromhex(verifier), self.expansion))
                if gmlevel:
                    cur.execute("INSERT INTO account_access (AccountID, SecurityLevel, RealmID) SELECT id, %s, -1 "
                                "FROM account WHERE username = %s", (gmlevel, username))
                return "ok"
        finally:
            c.close()

    def set_login(self, username, salt, verifier):
        """Hero Key sign-in: a new salt + verifier (see agent.RealmDB.set_login)."""
        if not salt_ok(salt):
            return "bad_salt"
        c = self._conn(self.AUTH)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM account WHERE username = %s", (username,))
                if not cur.fetchone():
                    return "missing"
                cur.execute("UPDATE account SET salt = %s, verifier = %s WHERE username = %s",
                            (bytes.fromhex(salt), bytes.fromhex(verifier), username))
                return "updated"
        finally:
            c.close()

    def grant_gm(self, username, gmlevel=3):
        c = self._conn(self.AUTH)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM account WHERE username = %s", (username.upper(),))
                row = cur.fetchone()
                if not row:
                    return "missing"
                cur.execute("SELECT SecurityLevel FROM account_access WHERE AccountID = %s AND RealmID = -1", (row[0],))
                have = cur.fetchone()
                if have and int(have[0]) == gmlevel:
                    return "unchanged"
                cur.execute("INSERT INTO account_access (AccountID, SecurityLevel, RealmID) VALUES (%s, %s, -1) "
                            "ON DUPLICATE KEY UPDATE SecurityLevel = VALUES(SecurityLevel)", (row[0], gmlevel))
                return "ok"
        finally:
            c.close()

    def status(self):
        c = self._conn(self.CHARS)
        try:
            with c.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM characters WHERE online = 1")
                players = cur.fetchone()[0]
                cur.execute(f"SELECT starttime FROM `{self.AUTH}`.uptime WHERE realmid = %s ORDER BY starttime DESC "
                            "LIMIT 1", (self.realm_db_id,))
                row = cur.fetchone()
            return {"players": int(players or 0), "bots": 0,
                    "uptime_s": int(time.time() - row[0]) if row else None, "bots_method": "none"}
        finally:
            c.close()


def db_class(core):
    """The database class for the kit's core (WU_CORE). AzerothCore's RealmDB when unset."""
    if core == "cmangos":
        return CmangosDB
    if core == "trinitycore":
        return TrinityDB
    if core == "vmangos":
        try:
            from .vmangos import VmangosDB   # the Hordes branch's module, when merged
            return VmangosDB
        except ImportError:
            pass
    return RealmDB


def open_db(env=None, realm_db_id=None):
    """The realm's database from the environment (the agent's and the self-check's compose settings), or None."""
    env = os.environ if env is None else env
    if not env.get("DB_HOST"):
        return None
    core = env.get("WU_CORE")
    cls = db_class(core)
    args = (env["DB_HOST"], int(env.get("DB_PORT", "3306")), env.get("DB_USER", "root"), env.get("DB_PASSWORD", ""),
            int(realm_db_id or env.get("WU_REALM_DB_ID", "1")))
    if cls in (CmangosDB, TrinityDB):
        kw = {k: env[e] for k, e in (("auth", "WU_DB_AUTH"), ("chars", "WU_DB_CHARS"), ("expansion", "WU_EXPANSION"))
              if env.get(e)}
        return cls(*args, **kw)
    return cls(*args)
