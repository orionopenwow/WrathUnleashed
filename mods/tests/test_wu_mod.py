#!/usr/bin/env python3
"""Tests for wu-mod.py. Run from anywhere:  python3 tests/test_wu_mod.py

Each rule has a failing fixture: the template is copied to a temp folder, one thing is broken,
and the test checks that `check` reports that rule's code and exits non-zero.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "wu-mod.py")
TEMPLATE = os.path.join(ROOT, "template")
REALM = "realm/dalaran_dice.lua"

spec = importlib.util.spec_from_file_location("wu_mod", TOOL)
wu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wu)

LUA = shutil.which("lua5.1") or shutil.which("lua")


def run(*args, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, env=e)


class Base(unittest.TestCase):
    def setUp(self):
        if getattr(self, "tmp", None):
            shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp = tempfile.mkdtemp(prefix="wu-mod-test-")
        self.mod = os.path.join(self.tmp, "dalaran-dice")
        shutil.copytree(TEMPLATE, self.mod)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers ---------------------------------------------------------------
    def path(self, rel):
        return os.path.join(self.mod, rel)

    def write(self, rel, text, mode="w"):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), mode) as f:
            f.write(text)

    def read(self, rel):
        with open(self.path(rel)) as f:
            return f.read()

    def manifest(self, **changes):
        m = json.loads(self.read("mod.json"))
        for k, v in changes.items():
            if v is None:
                m.pop(k, None)
            else:
                m[k] = v
        self.write("mod.json", json.dumps(m, indent=2))

    def append_realm(self, lua):
        self.write(REALM, self.read(REALM) + "\n" + lua + "\n")

    def report(self):
        return wu.check_package(self.mod)

    def assertFails(self, code, level="ERROR"):
        r = self.report()
        self.assertIn(code, r.codes(level), "expected %s %s, got:\n%s" % (level, code, self.dump(r)))
        if level == "ERROR":
            p = run("check", self.mod)
            self.assertEqual(p.returncode, 1, p.stdout)
            self.assertIn("[%s]" % code, p.stdout)
            self.assertIn("fix:", p.stdout)
        return r

    def assertPasses(self):
        r = self.report()
        self.assertEqual(r.errors, [], self.dump(r))
        return r

    @staticmethod
    def dump(r):
        return "\n".join("%s %s [%s] %s" % i[:4] for i in r.items)


class GoodMod(Base):
    def test_template_passes_with_luac(self):
        r = self.assertPasses()
        self.assertEqual(r.items, [], self.dump(r))
        p = run("check", self.mod)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("OK", p.stdout)

    def test_template_passes_with_builtin_parser(self):
        p = run("check", self.mod, env={"WU_MOD_NO_LUAC": "1"})
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("built-in parser", p.stdout)

    @unittest.skipUnless(LUA, "no lua interpreter")
    def test_template_lua_tests_pass(self):
        for test, target in (("tests/test_dalaran_dice.lua", REALM),
                             ("tests/test_ui.lua", "ui/DalaranDice/DalaranDice.lua")):
            p = subprocess.run([LUA, test, target], cwd=self.mod, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_can_hook_with_explicit_returns_passes(self):
        self.manifest(permissions=["commands", "chat", "db", "events"])
        self.append_realm("local function canJoin(event, player)\n"
                          "    if player:GetLevel() < 15 then return false end\n"
                          "    return true\nend\nRegisterPlayerEvent(50, canJoin)\n"
                          "RegisterPlayerEvent(PLAYER_EVENT_ON_CAN_GROUP_INVITE, function(e, p, name)\n"
                          "    return name ~= ''\nend)")
        self.assertPasses()

    def test_zip_input_passes(self):
        out = os.path.join(self.tmp, "dist")
        self.assertEqual(run("pack", self.mod, "-o", out).returncode, 0)
        p = run("check", os.path.join(out, "dalaran-dice-0.1.0.zip"))
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_licence_expression_and_assets_with_credits(self):
        self.manifest(licence="MIT OR CC-BY-4.0", screenshots=["assets/shot.png"])
        self.write("assets/shot.png", b"\x89PNG\r\n\x1a\nfake", mode="wb")
        self.write("assets/CREDITS.txt", "shot.png - Your Name - CC-BY-4.0 - made for this mod\n")
        self.assertPasses()


class ManifestRules(Base):
    def test_missing_manifest(self):
        os.remove(self.path("mod.json"))
        self.assertFails("manifest-missing")

    def test_bad_json(self):
        self.write("mod.json", '{"id": "dalaran-dice",, }')
        self.assertFails("manifest-json")

    def test_missing_required_field(self):
        for field in wu.REQUIRED_FIELDS:
            self.setUp()
            self.manifest(**{field: None})
            self.assertFails("manifest-field")

    def test_bad_id(self):
        for bad in ("Dalaran_Dice", "dalaran--dice", "-dice", "dd", "1dice", "x" * 33):
            self.manifest(id=bad)
            self.assertFails("manifest-id")

    def test_bad_version(self):
        for bad in ("1.0", "v1.0.0", "01.0.0", 1):
            self.manifest(version=bad)
            self.assertFails("manifest-version")

    def test_bad_licence(self):
        self.manifest(licence="GPLv3")
        r = self.assertFails("manifest-licence")
        self.assertIn("GPL-3.0-only", self.dump(r) + "".join(str(i[4]) for i in r.items))

    def test_unknown_licence_warns(self):
        self.manifest(licence="Made-Up-1.0")
        self.assertFails("manifest-licence", level="WARN")

    def test_bad_kind(self):
        self.manifest(kind="server")
        self.assertFails("manifest-kind")

    def test_category_defaults_from_kind(self):
        self.manifest(category=None)
        self.assertEqual(self.assertPasses().manifest["category"], "addons")       # template is kind "both"
        shutil.rmtree(self.path("realm"))
        self.manifest(kind="ui", permissions=None, category=None)
        self.assertEqual(self.assertPasses().manifest["category"], "addons")
        self.setUp()
        shutil.rmtree(self.path("ui"))
        self.manifest(kind="realm", category=None)
        self.assertEqual(self.assertPasses().manifest["category"], "realm-scripts")

    def test_every_listed_category_passes(self):
        ids = [c["id"] for c in json.load(open(os.path.join(ROOT, "categories.json")))["categories"]]
        self.assertEqual(len(ids), 12)
        for c in ids:
            self.manifest(category=c)
            r = self.assertPasses()
            self.assertEqual(r.manifest["category"], c)
            self.assertNotIn("manifest-field", r.codes("WARN"))

    def test_unknown_category(self):
        self.manifest(category="weapons")
        r = self.assertFails("manifest-category")
        self.assertIn("addons", self.dump(r) + run("check", self.mod).stdout)

    def test_category_must_be_a_string(self):
        self.manifest(category=["addons"])
        self.assertFails("manifest-category")

    def test_category_list_is_one_file(self):
        ids, defaults = wu.load_categories()
        self.assertEqual(ids[0], "addons")
        self.assertEqual(defaults, {"ui": "addons", "realm": "realm-scripts", "both": "addons"})
        self.assertEqual(wu.load_categories(os.path.join(self.tmp, "none.json"))[0], None)

    def test_bad_wu(self):
        self.manifest(wu="latest")
        self.assertFails("manifest-wu")

    def test_unknown_permission(self):
        self.manifest(permissions=["commands", "chat", "db", "files"])
        self.assertFails("manifest-permissions")

    def test_missing_screenshot(self):
        self.manifest(screenshots=["assets/nope.png"])
        self.assertFails("manifest-screenshots")

    def test_http_link(self):
        self.manifest(links=[{"label": "Site", "url": "http://example.org"}])
        self.assertFails("manifest-links")


class LayoutRules(Base):
    def test_kind_ui_with_realm_folder(self):
        self.manifest(kind="ui", permissions=None)
        self.assertFails("layout-kind")

    def test_kind_both_without_ui(self):
        shutil.rmtree(self.path("ui"))
        self.assertFails("layout-kind")

    def test_sql_file_in_realm(self):
        self.write("realm/setup.sql", "CREATE TABLE mod_dalaran_dice_x (id INT);")
        self.assertFails("layout-realm")

    @unittest.skipIf(os.name == "nt", "symlinks")
    def test_symlink(self):
        os.symlink("/etc/passwd", self.path("assets_link"))
        self.assertFails("layout-symlink")

    def test_unsafe_zip(self):
        z = os.path.join(self.tmp, "evil.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../../escape.lua", "print(1)")
        p = run("check", z)
        self.assertEqual(p.returncode, 1)
        self.assertIn("[zip]", p.stdout)


class AssetRules(Base):
    def test_blocked_extensions(self):
        for ext in (".mpq", ".blp", ".m2", ".wmo", ".adt", ".dbc"):
            self.setUp()
            self.write("assets/thing" + ext, b"data", mode="wb")
            self.write("assets/CREDITS.txt", "thing%s - me - MIT - mine\n" % ext)
            self.assertFails("asset-blocked")

    def test_renamed_game_file(self):
        self.write("assets/totally_a_picture.png", b"MPQ\x1a\x00\x00\x00\x00", mode="wb")
        self.write("assets/CREDITS.txt", "totally_a_picture.png - me - MIT - mine\n")
        self.assertFails("asset-blocked")

    def test_blp_inside_ui(self):
        self.write("ui/DalaranDice/icon.blp", b"BLP2....", mode="wb")
        self.assertFails("asset-blocked")

    def test_assets_without_credits(self):
        self.write("assets/sound.ogg", b"OggS", mode="wb")
        self.assertFails("asset-credits")

    def test_asset_missing_from_credits(self):
        self.write("assets/sound.ogg", b"OggS", mode="wb")
        self.write("assets/CREDITS.txt", "other.ogg - me - MIT - mine\n")
        self.assertFails("asset-credits")


class UiRules(Base):
    TOC = "ui/DalaranDice/DalaranDice.toc"

    def test_wrong_interface(self):
        self.write(self.TOC, self.read(self.TOC).replace("30300", "11200"))
        self.assertFails("ui-toc")

    def test_toc_lists_missing_file(self):
        self.write(self.TOC, self.read(self.TOC) + "Missing.lua\n")
        self.assertFails("ui-toc")

    def test_toc_name_must_match_folder(self):
        os.rename(self.path(self.TOC), self.path("ui/DalaranDice/Dice.toc"))
        self.assertFails("ui-toc")

    def test_bad_xml(self):
        self.write("ui/DalaranDice/DalaranDice.xml", "<Ui><Frame name='x'></Ui>")
        self.assertFails("ui-xml")

    def test_loose_file_in_ui(self):
        self.write("ui/stray.lua", "print(1)")
        self.assertFails("ui-layout")

    def test_ui_lua_syntax(self):
        self.write("ui/DalaranDice/DalaranDice.lua", "function broken(\n")
        self.assertFails("lua-syntax")


class LuaSyntax(Base):
    def test_realm_syntax_error_luac(self):
        self.append_realm("local function f()\n  if x then\nend")
        self.assertFails("lua-syntax")

    def test_realm_syntax_error_builtin(self):
        self.append_realm("local function f()\n  if x then\nend")
        os.environ["WU_MOD_NO_LUAC"] = "1"
        try:
            self.assertFails("lua-syntax")
        finally:
            del os.environ["WU_MOD_NO_LUAC"]

    def test_builtin_parser_errors(self):
        for bad in ("x = 'open", "x = [[open", "--[[ open", "f(", "end", "repeat x() end", "x = 3abc"):
            with self.assertRaises(wu.LuaSyntaxError, msg=bad):
                wu.minimal_parse(wu.tokenize(bad))
        wu.minimal_parse(wu.tokenize("local s = [==[ ]] ]==] -- [[ x\nrepeat until true"))


class ForbiddenApis(Base):
    def test_each_forbidden_call(self):
        for code in ('os.execute("rm -rf /")', 'local f = io.open("x")', 'loadstring("x=1")()',
                     'dofile("x.lua")', 'local m = require("ov_modapi")', 'local e = os.getenv("HOME")',
                     'local o = os', 'print(_G["os"])', 'debug.sethook()', 'string.dump(print)',
                     'HttpRequest("GET", "https://example.org", function() end)', 'RunCommand("server shutdown 1")',
                     'AuthDBExecute("DELETE FROM account")', 'setfenv(1, {})'):
            self.setUp()
            self.append_realm(code)
            self.assertFails("forbidden-api")

    def test_os_time_and_fields_named_like_apis_are_fine(self):
        self.append_realm("local t = os.time() + os.clock()\nlocal x = {}\nx.require = 1\nlocal load = 2")
        self.assertPasses()


class Permissions(Base):
    def test_command_without_permission(self):
        self.manifest(permissions=["chat", "db"])
        self.assertFails("permission-missing")

    def test_chat_needed_for_ovmod(self):
        self.manifest(permissions=["commands", "db"])
        r = self.assertFails("permission-missing")
        self.assertIn("Send", self.dump(r))

    def test_each_permission_is_enforced(self):
        cases = {
            "gossip": "RegisterCreatureGossipEvent(90001, 1, function(e, p, c) end)",
            "spawns": "local function s(p) p:SpawnCreature(90001, 0, 0, 0, 0, 3, 60000) end",
            "events": "RegisterPlayerEvent(3, function(e, p) end)",
            "timers": "CreateLuaEvent(function() end, 1000, 1)",
            "chat": "RegisterPlayerEvent(18, function(e, p, msg) end)",
        }
        for perm, code in cases.items():
            self.setUp()
            self.manifest(permissions=[x for x in ("commands", "chat", "db") if x != perm])
            self.append_realm(code)
            r = self.assertFails("permission-missing")
            self.assertIn("`%s`" % perm, self.dump(r))

    def test_unused_permission_warns(self):
        self.manifest(permissions=["commands", "chat", "db", "timers"])
        r = self.assertFails("permission-unused", level="WARN")
        self.assertEqual(r.errors, [])

    def test_unreadable_event_id(self):
        self.append_realm("local ids = {42}\nRegisterPlayerEvent(ids[1], function() end)")
        self.assertFails("event-id")


class SqlRules(Base):
    def test_other_table(self):
        self.append_realm('CharDBExecute("UPDATE characters SET money = 0")')
        self.assertFails("sql-table")

    def test_other_mods_table(self):
        self.append_realm('CharDBExecute("DELETE FROM mod_other_mod_rolls")')
        self.assertFails("sql-table")

    def test_world_table_via_query(self):
        self.append_realm('local q = WorldDBQuery("SELECT * FROM creature_template WHERE entry = 1")')
        self.assertFails("sql-table")

    def test_other_database(self):
        self.append_realm('CharDBExecute("INSERT INTO acore_auth.mod_dalaran_dice_x VALUES (1)")')
        self.assertFails("sql-table")

    def test_table_in_variable(self):
        self.append_realm('local T = "characters"\nCharDBExecute("DELETE FROM " .. T)')
        self.assertFails("sql-literal")

    def test_no_literal(self):
        self.append_realm('local q = "x"\nCharDBExecute(q)')
        self.assertFails("sql-literal")

    def test_two_statements(self):
        self.append_realm('CharDBExecute("DELETE FROM mod_dalaran_dice_rolls; DROP TABLE characters")')
        self.assertFails("sql-forbidden")

    def test_grant(self):
        self.append_realm('CharDBExecute("GRANT ALL ON mod_dalaran_dice_rolls TO x")')
        self.assertFails("sql-forbidden")

    def test_upsert_and_on_update_are_fine(self):
        self.append_realm('CharDBExecute("CREATE TABLE IF NOT EXISTS mod_dalaran_dice_v (g INT PRIMARY KEY, n INT, '
                          't TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")\n'
                          'CharDBExecute("INSERT INTO mod_dalaran_dice_v (g, n) VALUES (1, 1) '
                          'ON DUPLICATE KEY UPDATE n = n + 1")')
        self.assertPasses()

    def test_insert_select_from_other_table(self):
        self.append_realm('CharDBExecute("INSERT INTO mod_dalaran_dice_rolls SELECT * FROM characters")')
        self.assertFails("sql-table")

    def test_quoted_values_do_not_confuse_it(self):
        self.append_realm("CharDBExecute(\"INSERT INTO mod_dalaran_dice_rolls (char_name) VALUES ('from characters')\")")
        self.assertPasses()


class CanHookRule(Base):
    def setUp(self):
        Base.setUp(self)
        self.manifest(permissions=["commands", "chat", "db", "events"])

    def test_falls_through(self):
        self.append_realm("local function canJoin(event, player)\n"
                          "    if player:GetLevel() < 15 then return false end\nend\n"
                          "RegisterPlayerEvent(50, canJoin)")
        r = self.assertFails("can-hook-return")
        self.assertIn("Dungeon Finder", self.dump(r))

    def test_bare_return(self):
        self.append_realm("RegisterPlayerEvent(48, function(e, p, t)\n    if p then return end\n    return true\nend)")
        self.assertFails("can-hook-return")

    def test_return_nil(self):
        self.append_realm("local function f(e, p) return nil end\nRegisterPlayerEvent(59, f)")
        self.assertFails("can-hook-return")

    def test_non_boolean_value(self):
        self.append_realm("local function f(e, p) local ok = p:IsAlive()\n return ok end\n"
                          "RegisterPlayerEvent(55, f)")
        self.assertFails("can-hook-return")

    def test_and_or_is_not_proven_boolean(self):
        self.append_realm("local function f(e, p, mail) return mail and mail.ok end\nRegisterPlayerEvent(49, f)")
        self.assertFails("can-hook-return")

    def test_named_constant_and_local_constant(self):
        self.append_realm("local CAN_SKILL = 60\nlocal function f(e, p, s) if s == 1 then return true end end\n"
                          "RegisterPlayerEvent(CAN_SKILL, f)")
        self.assertFails("can-hook-return")

    def test_handler_not_found(self):
        self.append_realm("local H = {}\nRegisterPlayerEvent(50, H.canJoin)")
        self.assertFails("can-hook-return")

    def test_nested_function_returns_do_not_count(self):
        self.append_realm("local function f(e, p)\n  local g = function() return true end\n  g()\nend\n"
                          "RegisterPlayerEvent(50, f)")
        self.assertFails("can-hook-return")

    def test_non_can_events_are_not_checked(self):
        self.append_realm("RegisterPlayerEvent(3, function(e, p) if p then return end end)")
        self.assertPasses()


class GlobalsWarning(Base):
    def test_global_function_and_variable_warn(self):
        self.append_realm("function helper() end\ncounter = 0")
        r = self.assertFails("global", level="WARN")
        self.assertEqual(r.errors, [])

    def test_table_fields_and_prefixed_globals_are_fine(self):
        self.append_realm("local T = {\n  a = 1,\n  b = 2,\n}\nDALARAN_DICE_TEST = T")
        r = self.assertPasses()
        self.assertNotIn("global", r.codes())


class NewCommand(Base):
    def test_new_creates_a_passing_mod(self):
        p = run("new", "goblin-races", "--dir", self.tmp)
        self.assertEqual(p.returncode, 0, p.stderr)
        d = os.path.join(self.tmp, "goblin-races")
        m = json.load(open(os.path.join(d, "mod.json")))
        self.assertEqual((m["id"], m["name"], m["version"]), ("goblin-races", "Goblin Races", "0.1.0"))
        self.assertTrue(os.path.isfile(os.path.join(d, "realm/goblin_races.lua")))
        self.assertTrue(os.path.isfile(os.path.join(d, "ui/GoblinRaces/GoblinRaces.toc")))
        lua = open(os.path.join(d, "realm/goblin_races.lua")).read()
        self.assertIn("mod_goblin_races_rolls", lua)
        self.assertNotIn("dalaran_dice", lua)
        c = run("check", d)
        self.assertEqual(c.returncode, 0, c.stdout)
        if LUA:
            for test, target in (("tests/test_goblin_races.lua", "realm/goblin_races.lua"),
                                 ("tests/test_ui.lua", "ui/GoblinRaces/GoblinRaces.lua")):
                t = subprocess.run([LUA, test, target], cwd=d, capture_output=True, text=True)
                self.assertEqual(t.returncode, 0, t.stdout + t.stderr)

    def test_new_rejects_bad_id_and_existing_folder(self):
        self.assertEqual(run("new", "Bad_Id", "--dir", self.tmp).returncode, 2)
        self.assertEqual(run("new", "dalaran-dice", "--dir", self.tmp).returncode, 2)


class PackCommand(Base):
    def sha(self, p):
        return hashlib.sha256(open(p, "rb").read()).hexdigest()

    def test_pack_is_deterministic(self):
        a, b = os.path.join(self.tmp, "a"), os.path.join(self.tmp, "b")
        self.assertEqual(run("pack", self.mod, "-o", a).returncode, 0)
        os.utime(self.path(REALM), (1, 1))            # new mtime must not change the zip
        self.assertEqual(run("pack", self.mod, "-o", b).returncode, 0)
        za, zb = os.path.join(a, "dalaran-dice-0.1.0.zip"), os.path.join(b, "dalaran-dice-0.1.0.zip")
        self.assertEqual(self.sha(za), self.sha(zb))
        line = open(za + ".sha256").read()
        self.assertEqual(line, "%s  dalaran-dice-0.1.0.zip\n" % self.sha(za))
        names = zipfile.ZipFile(za).namelist()
        self.assertEqual(names, sorted(names))
        self.assertTrue(all(n.startswith("dalaran-dice/") for n in names))
        self.assertIn("dalaran-dice/mod.json", names)

    def test_pack_refuses_a_bad_mod(self):
        self.append_realm('os.execute("x")')
        out = os.path.join(self.tmp, "out")
        p = run("pack", self.mod, "-o", out)
        self.assertEqual(p.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(out, "dalaran-dice-0.1.0.zip")))


CATALOG = os.path.join(ROOT, "catalog")
LUAC = shutil.which("luac5.1")


def catalog_ids():
    return sorted(d for d in os.listdir(CATALOG) if os.path.isdir(os.path.join(CATALOG, d)))


def lua_tests(mod_dir):
    """(test file, target) pairs: test_ui.lua runs against each addon's main file, test_<x>.lua against realm/<x>.lua."""
    out = []
    for t in sorted(os.listdir(os.path.join(mod_dir, "tests"))):
        if not t.endswith(".lua"):
            continue
        if t == "test_ui.lua":
            for a in sorted(os.listdir(os.path.join(mod_dir, "ui"))):
                out.append(("tests/" + t, "ui/%s/%s.lua" % (a, a)))
        else:
            out.append(("tests/" + t, "realm/%s.lua" % t[len("test_"):-len(".lua")]))
    return out


class CatalogMods(unittest.TestCase):
    def test_catalog_has_the_three_mods(self):
        self.assertEqual(catalog_ids(), ["dalaran-dice", "emote-wheel", "pings"])

    def test_every_catalog_mod_passes_check_without_warnings(self):
        for mid in catalog_ids():
            r = wu.check_package(os.path.join(CATALOG, mid))
            self.assertEqual(r.items, [], "%s:\n%s" % (mid, Base.dump(r)))
            for env in ({}, {"WU_MOD_NO_LUAC": "1"}):
                p = run("check", os.path.join(CATALOG, mid), env=env)
                self.assertEqual(p.returncode, 0, p.stdout)

    def test_kinds_and_permissions(self):
        m = {mid: json.load(open(os.path.join(CATALOG, mid, "mod.json"))) for mid in catalog_ids()}
        self.assertEqual((m["pings"]["kind"], m["pings"]["permissions"]), ("both", ["chat", "timers"]))
        self.assertEqual(m["emote-wheel"]["kind"], "ui")
        self.assertNotIn("permissions", m["emote-wheel"])

    def test_dalaran_dice_matches_the_template(self):
        for rel in ("realm/dalaran_dice.lua", "ui/DalaranDice/DalaranDice.lua", "ui/DalaranDice/DalaranDice.xml"):
            self.assertEqual(open(os.path.join(TEMPLATE, rel)).read(),
                             open(os.path.join(CATALOG, "dalaran-dice", rel)).read(), rel)

    def test_pings_realm_uses_ovmod_without_require(self):
        src = open(os.path.join(CATALOG, "pings", "realm", "pings.lua")).read()
        self.assertNotIn("require", src)
        self.assertIn('OVMod.On(MOD, "map", onMap)', src)

    @unittest.skipUnless(LUA, "no lua interpreter")
    def test_catalog_lua_tests_pass(self):
        ran = 0
        for mid in catalog_ids():
            d = os.path.join(CATALOG, mid)
            for test, target in lua_tests(d):
                p = subprocess.run([LUA, test, target], cwd=d, capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, "%s %s\n%s%s" % (mid, test, p.stdout[-800:], p.stderr))
                self.assertRegex(p.stdout, r"\n(\d+)/\1 passed")
                ran += 1
        self.assertGreaterEqual(ran, 5)


class CatalogCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wu-cat-test-")
        self.cat = os.path.join(self.tmp, "catalog")
        shutil.copytree(CATALOG, self.cat)
        self.out = os.path.join(self.tmp, "catalog.json")
        self.dist = os.path.join(self.tmp, "dist")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, *extra):
        return run("catalog", self.cat, "-o", self.out, "--dist", self.dist, *extra)

    def test_writes_the_catalog(self):
        p = self.build()
        self.assertEqual(p.returncode, 0, p.stdout)
        doc = json.load(open(self.out))
        self.assertEqual(doc["format"], 1)
        mods = {m["id"]: m for m in doc["mods"]}
        self.assertEqual(sorted(mods), ["dalaran-dice", "emote-wheel", "pings"])
        for k in ("id", "name", "version", "author", "licence", "kind", "category", "description", "permissions",
                  "screenshots", "sha256", "zip", "addons"):
            self.assertIn(k, mods["pings"], k)
        for m in mods.values():
            z = os.path.join(self.dist, m["zip"])
            self.assertEqual(m["sha256"], hashlib.sha256(open(z, "rb").read()).hexdigest())
            self.assertEqual(m["size"], os.path.getsize(z))
            self.assertTrue(os.path.isfile(z + ".sha256"))
        self.assertEqual(mods["pings"]["addons"], ["WUPings"])
        self.assertEqual(mods["pings"]["realm_files"], ["pings.lua"])
        self.assertEqual(mods["emote-wheel"]["realm_files"], [])
        self.assertEqual(mods["pings"]["screenshots"], ["assets/preview.png"])

    def test_deterministic(self):
        self.assertEqual(self.build().returncode, 0)
        a = open(self.out, "rb").read()
        self.assertEqual(self.build().returncode, 0)
        self.assertEqual(open(self.out, "rb").read(), a)

    def test_committed_catalog_json_is_current(self):
        self.assertEqual(run("catalog", CATALOG, "-o", self.out, "--dist", self.dist).returncode, 0)
        self.assertEqual(open(self.out).read(), open(os.path.join(ROOT, "catalog.json")).read(),
                         "run: python3 mods/wu-mod.py catalog --dist /tmp/x  (and commit mods/catalog.json)")

    def test_a_bad_mod_stops_everything(self):
        with open(os.path.join(self.cat, "pings", "realm", "pings.lua"), "a") as f:
            f.write('\nlocal f = io.open("x")\n')
        p = self.build()
        self.assertEqual(p.returncode, 1)
        self.assertIn("pings", p.stdout)
        self.assertIn("forbidden-api", p.stdout)
        self.assertFalse(os.path.exists(self.out))

    def test_folder_must_be_the_id(self):
        os.rename(os.path.join(self.cat, "pings"), os.path.join(self.cat, "map-pings"))
        p = self.build()
        self.assertEqual(p.returncode, 1)
        self.assertIn("[catalog-id]", p.stdout)

    def test_addon_names_are_unique_and_not_reserved(self):
        shutil.copytree(os.path.join(self.cat, "emote-wheel", "ui", "WUEmoteWheel"),
                        os.path.join(self.cat, "pings", "ui", "WUEmoteWheel"))
        p = self.build()
        self.assertEqual(p.returncode, 1)
        self.assertIn("already used by", p.stdout)
        shutil.rmtree(os.path.join(self.cat, "pings", "ui", "WUEmoteWheel"))
        ui = os.path.join(self.cat, "emote-wheel", "ui")
        os.rename(os.path.join(ui, "WUEmoteWheel"), os.path.join(ui, "WrathUnleashedUI"))
        os.rename(os.path.join(ui, "WrathUnleashedUI", "WUEmoteWheel.toc"), os.path.join(ui, "WrathUnleashedUI", "WrathUnleashedUI.toc"))
        p = self.build()
        self.assertEqual(p.returncode, 1)
        self.assertIn("[catalog-addon]", p.stdout)

    def test_empty_catalog(self):
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        self.assertEqual(run("catalog", empty, "-o", self.out, "--dist", self.dist).returncode, 1)

    def test_lua_mod_list_addon(self):
        m = json.load(open(os.path.join(self.cat, "pings", "mod.json")))
        m["description"] = 'Quotes " and \\ and a\nnew line'
        json.dump(m, open(os.path.join(self.cat, "pings", "mod.json"), "w"))
        gen = os.path.join(self.tmp, "addons")
        self.assertEqual(self.build("--lua", gen).returncode, 0)
        toc = open(os.path.join(gen, "WUModCatalog", "WUModCatalog.toc")).read()
        self.assertIn("## Interface: 30300", toc)
        lua = os.path.join(gen, "WUModCatalog", "WUModCatalog.lua")
        self.assertIn('id = "pings"', open(lua).read())
        if LUA:
            p = subprocess.run([LUA, "-e", 'dofile(arg and arg[1] or "%s") for _, m in ipairs(WU_MOD_CATALOG) do '
                                'if m.id == "pings" then io.write(m.description, "|", #WU_MOD_CATALOG, "|", m.addons[1]) end end'
                                % lua.replace("\\", "/")], capture_output=True, text=True)
            self.assertEqual(p.stdout, 'Quotes " and \\ and a\nnew line|3|WUPings', p.stderr)


class Cli(unittest.TestCase):
    def test_usage(self):
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run("bogus").returncode, 2)
        self.assertEqual(run("--version").returncode, 0)

    def test_not_a_package(self):
        self.assertEqual(run("check", "/nonexistent/path").returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
