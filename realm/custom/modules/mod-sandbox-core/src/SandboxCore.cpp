/*
 * mod-sandbox-core: Gmod-style level edits for the realm's Builder (realm/custom/lua_scripts/ov_build.lua).
 *
 * What it adds to the core, for Lua (mod-ale) through the bridge described in SandboxMath.h:
 *   Spawn    a builder prop as a SandboxGameObject, with a GUID counter from a free list when one is out of
 *            quarantine, a full quaternion (yaw, pitch, roll) and a size; registered as a builder object.
 *   Move     relocates a builder prop in place: the GUID stays, the grid cell is updated
 *            (Map::GameObjectRelocation), the stationary position and the world rotation change, and every
 *            player who has it on screen gets a destroy + create for it (SandboxCore.Refresh).
 *            SandboxCore.MoveMode = 1 instead respawns it under a fresh GUID (stock 3.3.5a clients, see README).
 *   Scale    sets OBJECT_FIELD_SCALE_X, rebuilds the collision model, refreshes it for players in range and
 *            keeps the size in sandbox_go_scale (re-applied by Spawn when Lua passes no size).
 *   Despawn  removes a builder prop; its GUID counter goes to the free list once it has left the world.
 *
 * Why a subclass: the create block sends a GameObject's position from m_stationaryPosition (Object.cpp,
 * UPDATEFLAG_STATIONARY_POSITION), which only GameObject::Create sets and which is protected. Only an object
 * this module created (a SandboxGameObject) can be moved in place and still be sent at its new spot. That is
 * also the safety rule: every request names a GUID, and only a registered SandboxGameObject (dynamic_cast)
 * is ever touched. Nothing here moves, scales or deletes the world's own spawns.
 *
 * Threads: Lua runs on the world thread (commands, timers) and sometimes inside a map update (zone-change
 * events); either way the object is on the map the caller is updating, as with mod-ale's PerformIngameSpawn.
 * The registry, free lists and scale cache are shared, so they sit behind one mutex, never held across a call
 * into the map.
 */

#include "SandboxMath.h"

#include "Config.h"
#include "DBCStores.h"
#include "DatabaseEnv.h"
#include "GameObject.h"
#include "GameTime.h"
#include "Log.h"
#include "Map.h"
#include "MapMgr.h"
#include "ObjectMgr.h"
#include "Player.h"
#include "ScriptMgr.h"
#include "WorldPacket.h"
#include "WorldSession.h"

#include <mutex>
#include <unordered_map>

using namespace SandboxCore;

namespace
{
    // A GameObject whose stationary position (what create blocks carry) can follow a move.
    class SandboxGameObject : public GameObject
    {
    public:
        SandboxGameObject() : GameObject() { }

        void SetStationaryPosition(float x, float y, float z, float o)
        {
            m_stationaryPosition.Relocate(x, y, z, o);
        }

        // The collision model at the current size (GameObject::UpdateModel is protected).
        void RebuildModel() { UpdateModel(); }
    };

    struct Settings
    {
        bool enable = true;
        uint32 moveMode = 0;         // 0 in place, same GUID; 1 a fresh GUID per move
        bool destroyFirst = true;    // refresh = SMSG_DESTROY_OBJECT then a create block (else the create only)
        uint32 reuseDelaySec = 300;  // free-list quarantine
        float maxMove = 200.f;       // yards one Move may carry a prop
        float minScale = 0.1f;
        float maxScale = 5.f;
        uint32 maxOps = 400;         // requests a second, all players together (Lua has its own per-player limits)
        uint32 maxObjects = 20000;   // registered builder objects at once
    };

    struct Reg
    {
        uint32 propId;
        uint32 mapId;
        uint32 entry;
    };

    std::mutex g_lock;
    Settings g_cfg;
    std::unordered_map<uint64, Reg> g_registry;      // full GUID -> builder prop
    std::unordered_map<uint32, uint64> g_byProp;     // prop id -> full GUID (the newest one)
    std::unordered_map<uint32, FreeList> g_free;     // map id -> released GUID counters
    std::unordered_map<uint32, float> g_scale;       // prop id -> size (sandbox_go_scale)
    RateWindow g_rate;

    uint64 NowMs() { return uint64(GameTime::GetGameTimeMS().count()); }

    Settings CurrentSettings()
    {
        std::lock_guard<std::mutex> guard(g_lock);
        return g_cfg;
    }

    void Unregister(uint64 raw) // g_lock held
    {
        auto it = g_registry.find(raw);
        if (it == g_registry.end())
            return;
        auto bp = g_byProp.find(it->second.propId);
        if (bp != g_byProp.end() && bp->second == raw)
            g_byProp.erase(bp);
        g_registry.erase(it);
    }

    FreeList& FreeListFor(uint32 mapId) // g_lock held
    {
        auto it = g_free.find(mapId);
        if (it == g_free.end())
            it = g_free.emplace(mapId, FreeList(uint64(g_cfg.reuseDelaySec) * 1000)).first;
        return it->second;
    }

    void LoadSettings()
    {
        Settings s;
        s.enable = sConfigMgr->GetOption<bool>("SandboxCore.Enable", true, false);
        s.moveMode = sConfigMgr->GetOption<uint32>("SandboxCore.MoveMode", 0, false) == 1 ? 1 : 0;
        s.destroyFirst = sConfigMgr->GetOption<uint32>("SandboxCore.Refresh", 1, false) != 0;
        s.reuseDelaySec = sConfigMgr->GetOption<uint32>("SandboxCore.ReuseDelaySec", 300, false);
        s.maxMove = sConfigMgr->GetOption<float>("SandboxCore.MaxMoveDistance", 200.f, false);
        s.minScale = sConfigMgr->GetOption<float>("SandboxCore.MinScale", 0.1f, false);
        s.maxScale = sConfigMgr->GetOption<float>("SandboxCore.MaxScale", 5.f, false);
        s.maxOps = sConfigMgr->GetOption<uint32>("SandboxCore.MaxOpsPerSecond", 400, false);
        s.maxObjects = sConfigMgr->GetOption<uint32>("SandboxCore.MaxObjects", 20000, false);
        if (!(s.maxMove > 0.f) || !Finite(s.maxMove))
            s.maxMove = 200.f;
        if (!(s.minScale > 0.f) || !(s.maxScale >= s.minScale) || !Finite(s.maxScale))
        {
            s.minScale = 0.1f;
            s.maxScale = 5.f;
        }

        std::lock_guard<std::mutex> guard(g_lock);
        g_cfg = s;
        g_rate.SetLimit(s.maxOps);
        for (auto& kv : g_free)
            kv.second.SetQuarantine(uint64(s.reuseDelaySec) * 1000);
    }

    // Every player who has the object on screen gets it again, at its new place, rotation and size.
    void Refresh(GameObject* go, bool destroyFirst)
    {
        Map* map = go->GetMap();
        if (!map)
            return;
        map->DoForAllPlayers([go, destroyFirst](Player* player)
        {
            if (!player->IsInWorld() || !player->HaveAtClient(go))
                return;
            if (destroyFirst)
                go->DestroyForPlayer(player);
            go->SendUpdateToPlayer(player);
        });
    }

    void SaveRow(uint32 propId, uint32 mapId, uint32 entry, GameObject const* go)
    {
        G3D::Quat const& r = go->GetWorldRotation();
        CharacterDatabase.Execute("REPLACE INTO sandbox_go_registry (prop_id, map, entry, guid_low, x, y, z, "
            "rotation0, rotation1, rotation2, rotation3, scale, updated_at) VALUES ({}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, UNIX_TIMESTAMP())",
            propId, mapId, entry, go->GetGUID().GetCounter(), go->GetPositionX(), go->GetPositionY(), go->GetPositionZ(),
            r.x, r.y, r.z, r.w, go->GetObjectScale());
    }

    // The registered, in-world builder object behind guid, or nullptr.
    SandboxGameObject* Lookup(ObjectGuid guid, Reg& reg)
    {
        {
            std::lock_guard<std::mutex> guard(g_lock);
            auto it = g_registry.find(guid.GetRawValue());
            if (it == g_registry.end())
                return nullptr;
            reg = it->second;
        }
        if (!guid.IsGameObject())
            return nullptr;
        Map* map = sMapMgr->FindBaseNonInstanceMap(reg.mapId);
        if (!map)
            return nullptr;
        SandboxGameObject* go = dynamic_cast<SandboxGameObject*>(map->GetGameObject(guid));
        if (!go || !go->IsInWorld())
            return nullptr;
        return go;
    }

    Status DoSpawn(uint32 propId, uint32 entry, uint32 mapId, float x, float y, float z, Quat q, float scale, ObjectGuid& out)
    {
        Settings cfg = CurrentSettings();
        if (!Finite(x) || !Finite(y) || !Finite(z) || !Finite(scale) || !NormalizeQuat(q))
            return ST_BAD_VALUE;
        // size 0: the template's own; below 0: the size kept for this prop (sandbox_go_scale), else the template's.
        if (scale < 0.f)
        {
            std::lock_guard<std::mutex> guard(g_lock);
            auto it = g_scale.find(propId);
            scale = it != g_scale.end() ? it->second : 0.f;
        }
        if (scale > 0.f && (scale < cfg.minScale || scale > cfg.maxScale))
            return ST_BAD_VALUE;

        GameObjectTemplate const* info = sObjectMgr->GetGameObjectTemplate(entry);
        if (!info)
            return ST_FAILED;
        if (info->type == GAMEOBJECT_TYPE_TRANSPORT || info->type == GAMEOBJECT_TYPE_MO_TRANSPORT
            || sObjectMgr->IsGameObjectStaticTransport(entry))
            return ST_BAD_VALUE;
        if (info->displayId && !sGameObjectDisplayInfoStore.LookupEntry(info->displayId))
            return ST_FAILED;
        if (!MapMgr::IsValidMapCoord(mapId, x, y, z))
            return ST_OUT_OF_BOUNDS;
        Map* map = sMapMgr->FindBaseNonInstanceMap(mapId);
        if (!map)
            return ST_FAILED;
        if (map->Instanceable())
            return ST_OUT_OF_BOUNDS;

        uint32 counter = 0;
        {
            std::lock_guard<std::mutex> guard(g_lock);
            if (g_registry.size() >= cfg.maxObjects)
                return ST_FULL;
            counter = FreeListFor(mapId).Take(NowMs(), [map, entry](uint32 c, uint32 releasedEntry)
            {
                return map->GetGameObject(ObjectGuid::Create<HighGuid::GameObject>(releasedEntry, c)) != nullptr
                    || map->GetGameObject(ObjectGuid::Create<HighGuid::GameObject>(entry, c)) != nullptr;
            });
        }
        if (!counter)
            counter = map->GenerateLowGuid<HighGuid::GameObject>();

        SandboxGameObject* go = new SandboxGameObject();
        if (!go->Create(counter, entry, map, PHASEMASK_NORMAL, x, y, z, YawOf(q), G3D::Quat(q.x, q.y, q.z, q.w), 100, GO_STATE_READY))
        {
            delete go;
            return ST_FAILED;
        }
        if (scale > 0.f)
            go->SetObjectScale(scale);
        // As a plain GameObject: Map::AddToMap<T> is only instantiated (Map.cpp) for the core's own types, and a
        // class in this file's anonymous namespace has no linkage, so AddToMap<SandboxGameObject> can't link
        // (wu-images 2026-10-30: "is used but not defined in this translation unit").
        if (!map->AddToMap(static_cast<GameObject*>(go)))
        {
            delete go;
            return ST_FAILED;
        }
        if (scale > 0.f)
            go->RebuildModel(); // the collision model at the new size

        out = go->GetGUID();
        {
            std::lock_guard<std::mutex> guard(g_lock);
            g_registry[out.GetRawValue()] = Reg{ propId, mapId, entry };
            g_byProp[propId] = out.GetRawValue();
        }
        SaveRow(propId, mapId, entry, go);
        return ST_OK;
    }

    Status DoDespawn(ObjectGuid guid, bool forget)
    {
        Reg reg{};
        SandboxGameObject* go = Lookup(guid, reg);
        if (!go)
            return ST_NOT_BUILDER;
        go->SetRespawnTime(0);
        go->Delete(); // leaves the world at the map's next update; OnGameObjectRemoveWorld frees the counter
        {
            std::lock_guard<std::mutex> guard(g_lock);
            Unregister(guid.GetRawValue());
            if (forget)
                g_scale.erase(reg.propId);
        }
        if (forget)
        {
            CharacterDatabase.Execute("DELETE FROM sandbox_go_registry WHERE prop_id = {}", reg.propId);
            CharacterDatabase.Execute("DELETE FROM sandbox_go_scale WHERE prop_id = {}", reg.propId);
        }
        return ST_OK;
    }

    Status DoMove(ObjectGuid guid, float x, float y, float z, Quat q, ObjectGuid& out)
    {
        Settings cfg = CurrentSettings();
        Reg reg{};
        SandboxGameObject* go = Lookup(guid, reg);
        if (!go)
            return ST_NOT_BUILDER;
        if (!Finite(x) || !Finite(y) || !Finite(z) || !NormalizeQuat(q))
            return ST_BAD_VALUE;
        if (!MapMgr::IsValidMapCoord(reg.mapId, x, y, z))
            return ST_OUT_OF_BOUNDS;
        if (Dist3(go->GetPositionX(), go->GetPositionY(), go->GetPositionZ(), x, y, z) > cfg.maxMove)
            return ST_OUT_OF_BOUNDS;

        if (cfg.moveMode == 1)
        {
            // A fresh GUID: what stock 3.3.5a clients need (they revive a re-created GUID at its old spot).
            float scale = go->GetObjectScale();
            if (scale == go->GetGOInfo()->size)
                scale = 0.f; // the template's own: no range check, nothing kept
            Status st = DoSpawn(reg.propId, reg.entry, reg.mapId, x, y, z, q, scale, out);
            if (st != ST_OK)
                return st;
            DoDespawn(guid, false);
            return ST_OK;
        }

        float o = YawOf(q);
        // Stationary position and rotation first: the relocation queues the visibility update, and every create
        // block from here on must carry the new pose.
        go->SetStationaryPosition(x, y, z, o);
        go->SetWorldRotation(G3D::Quat(q.x, q.y, q.z, q.w));
        go->GetMap()->GameObjectRelocation(go, x, y, z, o);
        Refresh(go, cfg.destroyFirst);
        SaveRow(reg.propId, reg.mapId, reg.entry, go);
        out = guid;
        return ST_OK;
    }

    Status DoScale(ObjectGuid guid, float scale)
    {
        Settings cfg = CurrentSettings();
        Reg reg{};
        SandboxGameObject* go = Lookup(guid, reg);
        if (!go)
            return ST_NOT_BUILDER;
        // size 0: back to the template's own size (and nothing kept)
        bool reset = Finite(scale) && scale == 0.f;
        if (reset)
            scale = go->GetGOInfo()->size;
        else if (!Finite(scale) || scale < cfg.minScale || scale > cfg.maxScale)
            return ST_BAD_VALUE;
        go->SetObjectScale(scale);
        go->RebuildModel();
        Refresh(go, cfg.destroyFirst);
        {
            std::lock_guard<std::mutex> guard(g_lock);
            if (reset)
                g_scale.erase(reg.propId);
            else
                g_scale[reg.propId] = scale;
        }
        if (reset)
            CharacterDatabase.Execute("DELETE FROM sandbox_go_scale WHERE prop_id = {}", reg.propId);
        else
            CharacterDatabase.Execute("REPLACE INTO sandbox_go_scale (prop_id, scale, updated_at) VALUES ({}, {}, UNIX_TIMESTAMP())",
                reg.propId, scale);
        SaveRow(reg.propId, reg.mapId, reg.entry, go);
        return ST_OK;
    }

    // The object a prop already has in the world (after a Lua reload, the script has forgotten it).
    Status DoFind(uint32 propId, ObjectGuid& out)
    {
        uint64 raw = 0;
        {
            std::lock_guard<std::mutex> guard(g_lock);
            auto it = g_byProp.find(propId);
            if (it == g_byProp.end())
                return ST_NOT_BUILDER;
            raw = it->second;
        }
        Reg reg{};
        if (!Lookup(ObjectGuid(raw), reg))
            return ST_NOT_BUILDER;
        out = ObjectGuid(raw);
        return ST_OK;
    }

    // Runs one bridge request in place: reads it from io, writes the reply over it.
    void HandleBridge(WorldPacket& io)
    {
        Status st = ST_BAD_REQUEST;
        uint8 op = 0;
        ObjectGuid outGuid;
        uint32 outVersion = 0;
        uint8 outMode = 0;
        try
        {
            io.rpos(0);
            uint32 magic = 0;
            uint8 version = 0;
            io >> magic;
            if (magic != REQUEST_MAGIC)
                return; // not ours: leave it alone (CanPacketSend still keeps it off the wire)
            io >> version >> op;
            Settings cfg = CurrentSettings();
            bool allowed = false;
            {
                std::lock_guard<std::mutex> guard(g_lock);
                allowed = op == OP_PING || op == OP_FIND || g_rate.Allow(NowMs()); // look-ups are free
            }
            if (version != PROTOCOL_VERSION)
                st = ST_BAD_REQUEST;
            else if (!cfg.enable && op != OP_PING)
                st = ST_DISABLED;
            else if (!allowed)
                st = ST_RATE;
            else
            {
                switch (op)
                {
                    case OP_PING:
                        outVersion = MODULE_VERSION;
                        outMode = uint8(cfg.moveMode);
                        st = cfg.enable ? ST_OK : ST_DISABLED;
                        break;
                    case OP_SPAWN:
                    {
                        uint32 propId, entry, mapId;
                        float x, y, z, scale;
                        Quat q;
                        io >> propId >> entry >> mapId >> x >> y >> z >> q.x >> q.y >> q.z >> q.w >> scale;
                        st = DoSpawn(propId, entry, mapId, x, y, z, q, scale, outGuid);
                        break;
                    }
                    case OP_MOVE:
                    {
                        uint64 raw;
                        float x, y, z;
                        Quat q;
                        io >> raw >> x >> y >> z >> q.x >> q.y >> q.z >> q.w;
                        st = DoMove(ObjectGuid(raw), x, y, z, q, outGuid);
                        break;
                    }
                    case OP_SCALE:
                    {
                        uint64 raw;
                        float scale;
                        io >> raw >> scale;
                        st = DoScale(ObjectGuid(raw), scale);
                        break;
                    }
                    case OP_DESPAWN:
                    {
                        uint64 raw;
                        uint8 forget;
                        io >> raw >> forget;
                        st = DoDespawn(ObjectGuid(raw), forget != 0);
                        break;
                    }
                    case OP_FIND:
                    {
                        uint32 propId;
                        io >> propId;
                        st = DoFind(propId, outGuid);
                        break;
                    }
                    default:
                        st = ST_BAD_REQUEST;
                        break;
                }
            }
        }
        catch (ByteBufferException const&)
        {
            st = ST_BAD_REQUEST;
        }

        io.clear();
        io << uint32(REPLY_MAGIC) << uint8(st);
        if (st == ST_OK)
        {
            if (op == OP_PING)
                io << uint32(outVersion) << uint8(outMode);
            else if (op == OP_SPAWN || op == OP_MOVE || op == OP_FIND)
                io << uint64(outGuid.GetRawValue());
        }
    }
}

class SandboxCoreServerScript : public ServerScript
{
public:
    SandboxCoreServerScript() : ServerScript("SandboxCoreServerScript", {
        SERVERHOOK_ON_PACKET_SENT,
        SERVERHOOK_CAN_PACKET_SEND
    }) { }

    // Before the socket check, for every packet: the bridge's requests are answered here.
    void OnPacketSent(WorldSession* /*session*/, WorldPacket const& packet) override
    {
        if (packet.GetOpcode() != BRIDGE_OPCODE)
            return;
        // The packet is mod-ale's own (CreatePacket allocates it non-const); the hook only passes it as const.
        HandleBridge(const_cast<WorldPacket&>(packet));
    }

    // The server never sends CMSG_DBLOOKUP to a client: keep every bridge packet off the wire.
    bool CanPacketSend(WorldSession* /*session*/, WorldPacket const& packet) override
    {
        return packet.GetOpcode() != BRIDGE_OPCODE;
    }
};

class SandboxCoreGameObjectScript : public AllGameObjectScript
{
public:
    SandboxCoreGameObjectScript() : AllGameObjectScript("SandboxCoreGameObjectScript") { }

    // A builder object leaving the world (Despawn, a grid unload, shutdown): its counter goes to the free list.
    void OnGameObjectRemoveWorld(GameObject* go) override
    {
        if (go->GetSpawnId() != 0)
            return;
        if (!dynamic_cast<SandboxGameObject*>(go))
            return;
        std::lock_guard<std::mutex> guard(g_lock);
        Unregister(go->GetGUID().GetRawValue());
        FreeListFor(go->GetMapId()).Release(go->GetGUID().GetCounter(), go->GetEntry(), NowMs());
    }
};

class SandboxCoreWorldScript : public WorldScript
{
public:
    SandboxCoreWorldScript() : WorldScript("SandboxCoreWorldScript", {
        WORLDHOOK_ON_AFTER_CONFIG_LOAD,
        WORLDHOOK_ON_STARTUP,
        WORLDHOOK_ON_SHUTDOWN
    }) { }

    void OnAfterConfigLoad(bool /*reload*/) override
    {
        LoadSettings();
    }

    void OnStartup() override
    {
        // The same tables as data/sql/db-characters/base/sandbox_core.sql, for a realm whose updater skipped it.
        CharacterDatabase.DirectExecute("CREATE TABLE IF NOT EXISTS sandbox_go_scale (prop_id INT UNSIGNED NOT NULL PRIMARY KEY, "
            "scale FLOAT NOT NULL DEFAULT 1, updated_at INT UNSIGNED NOT NULL DEFAULT 0)");
        CharacterDatabase.DirectExecute("CREATE TABLE IF NOT EXISTS sandbox_go_registry (prop_id INT UNSIGNED NOT NULL PRIMARY KEY, "
            "map SMALLINT UNSIGNED NOT NULL, entry INT UNSIGNED NOT NULL, guid_low INT UNSIGNED NOT NULL, "
            "x FLOAT NOT NULL, y FLOAT NOT NULL, z FLOAT NOT NULL, rotation0 FLOAT NOT NULL DEFAULT 0, "
            "rotation1 FLOAT NOT NULL DEFAULT 0, rotation2 FLOAT NOT NULL DEFAULT 0, rotation3 FLOAT NOT NULL DEFAULT 1, "
            "scale FLOAT NOT NULL DEFAULT 1, updated_at INT UNSIGNED NOT NULL DEFAULT 0)");
        CharacterDatabase.DirectExecute("CREATE TABLE IF NOT EXISTS sandbox_core_status (id TINYINT UNSIGNED NOT NULL PRIMARY KEY, "
            "version INT UNSIGNED NOT NULL, move_mode TINYINT UNSIGNED NOT NULL DEFAULT 0, started_at INT UNSIGNED NOT NULL DEFAULT 0)");

        uint32 n = 0;
        if (QueryResult result = CharacterDatabase.Query("SELECT prop_id, scale FROM sandbox_go_scale"))
        {
            std::lock_guard<std::mutex> guard(g_lock);
            do
            {
                Field* f = result->Fetch();
                g_scale[f[0].Get<uint32>()] = f[1].Get<float>();
                ++n;
            } while (result->NextRow());
        }

        Settings cfg = CurrentSettings();
        // ov_sandbox_core.lua reads this row before it ever sends a bridge packet: no row, no module.
        if (cfg.enable)
            CharacterDatabase.DirectExecute("REPLACE INTO sandbox_core_status (id, version, move_mode, started_at) VALUES (1, {}, {}, UNIX_TIMESTAMP())",
                MODULE_VERSION, cfg.moveMode);
        else
            CharacterDatabase.DirectExecute("DELETE FROM sandbox_core_status WHERE id = 1");
        LOG_INFO("module", "mod-sandbox-core: {} (move mode {}, {} sizes kept)", cfg.enable ? "on" : "off", cfg.moveMode, n);
    }

    void OnShutdown() override
    {
        CharacterDatabase.DirectExecute("DELETE FROM sandbox_core_status WHERE id = 1");
    }
};

void AddSandboxCoreScripts()
{
    new SandboxCoreServerScript();
    new SandboxCoreGameObjectScript();
    new SandboxCoreWorldScript();
}
