/*
 * mod-sandbox-core: pure helpers (no AzerothCore headers), so tests/test_sandbox_math.cpp builds with a plain g++.
 *
 *   QuatFromYawPitchRoll  the quaternion GameObject::SetWorldRotationAngles(yaw, pitch, roll) builds through
 *                         G3D::Matrix3::fromEulerAnglesZYX: R = Rz(yaw) * Ry(pitch) * Rx(roll), all radians.
 *   YawOf                 the orientation (rotation about z) a quaternion gives the object's position.
 *   PackRotation          GameObject::UpdatePackedRotation: the int64 the create block's UPDATEFLAG_ROTATION carries.
 *   NormalizeQuat         unit length, or false for a zero / non-finite quaternion.
 *   FreeList              released GUID counters, reusable after a quarantine.
 *   RateWindow            at most N operations per one-second window.
 *   protocol constants    the request / reply layout shared with realm/custom/lua_scripts/ov_sandbox_core.lua.
 */

#ifndef MOD_SANDBOX_CORE_MATH_H
#define MOD_SANDBOX_CORE_MATH_H

#include <cmath>
#include <cstdint>
#include <deque>

namespace SandboxCore
{
    // ---------------------------------------------------------------------------------------------- protocol
    // Lua builds a packet with opcode CMSG_DBLOOKUP (0x002, a client-to-server debug opcode the server never sends)
    // and sends it to a player's own session (player:SendPacket). The module's ServerScript::OnPacketSent sees it
    // first, runs the request and rewrites the packet in place with the reply; CanPacketSend then drops it, so it
    // never reaches a socket. Request:  uint32 REQUEST_MAGIC, uint8 PROTOCOL_VERSION, uint8 op, then the op's args.
    // Reply:                            uint32 REPLY_MAGIC, uint8 status, then the op's results.
    constexpr uint16_t BRIDGE_OPCODE    = 0x002;
    constexpr uint32_t REQUEST_MAGIC    = 0x53425831; // "SBX1"
    constexpr uint32_t REPLY_MAGIC      = 0x53425852; // "SBXR"
    constexpr uint8_t  PROTOCOL_VERSION = 1;

    enum Op : uint8_t
    {
        OP_PING    = 1, // -> uint32 module version, uint8 move mode
        OP_SPAWN   = 2, // uint32 propId, uint32 entry, uint32 mapId, float x y z, float qx qy qz qw, float scale (0 template, <0 kept) -> uint64 guid
        OP_MOVE    = 3, // uint64 guid, float x y z, float qx qy qz qw -> uint64 guid (the same one, unless MoveMode = 1)
        OP_SCALE   = 4, // uint64 guid, float scale (0 = back to the template's size)
        OP_DESPAWN = 5, // uint64 guid, uint8 forget (1 = drop its kept size)
        OP_FIND    = 6, // uint32 propId -> uint64 guid of its object in the world (ST_NOT_BUILDER: none)
    };

    enum Status : uint8_t
    {
        ST_OK          = 0,
        ST_BAD_REQUEST = 1, // short packet, wrong version, unknown op
        ST_DISABLED    = 2, // SandboxCore.Enable = 0
        ST_NOT_BUILDER = 3, // not a gameobject this module spawned (the registry)
        ST_BAD_VALUE   = 4, // non-finite numbers, zero quaternion, scale out of range
        ST_OUT_OF_BOUNDS = 5, // invalid map coordinates, too far in one move, instanced map
        ST_RATE        = 6, // over SandboxCore.MaxOpsPerSecond
        ST_FAILED      = 7, // the core refused (no template, Create or AddToMap failed, map not loaded)
        ST_FULL        = 8, // SandboxCore.MaxObjects reached
    };

    constexpr uint32_t MODULE_VERSION = 1;

    // ---------------------------------------------------------------------------------------------- math
    struct Quat
    {
        float x = 0.f, y = 0.f, z = 0.f, w = 1.f;
    };

    inline bool Finite(float v) { return std::isfinite(v); }

    inline Quat QuatFromYawPitchRoll(float yaw, float pitch, float roll)
    {
        double cy = std::cos(yaw * 0.5), sy = std::sin(yaw * 0.5);
        double cp = std::cos(pitch * 0.5), sp = std::sin(pitch * 0.5);
        double cr = std::cos(roll * 0.5), sr = std::sin(roll * 0.5);
        Quat q;
        q.w = float(cr * cp * cy + sr * sp * sy);
        q.x = float(sr * cp * cy - cr * sp * sy);
        q.y = float(cr * sp * cy + sr * cp * sy);
        q.z = float(cr * cp * sy - sr * sp * cy);
        return q;
    }

    inline bool NormalizeQuat(Quat& q)
    {
        if (!Finite(q.x) || !Finite(q.y) || !Finite(q.z) || !Finite(q.w))
            return false;
        double m = std::sqrt(double(q.x) * q.x + double(q.y) * q.y + double(q.z) * q.z + double(q.w) * q.w);
        if (m < 1e-6)
            return false;
        q.x = float(q.x / m); q.y = float(q.y / m); q.z = float(q.z / m); q.w = float(q.w / m);
        return true;
    }

    // The heading in [0, 2pi): where the object's x axis points on the ground after the rotation.
    inline float YawOf(Quat const& q)
    {
        double siny = 2.0 * (double(q.w) * q.z + double(q.x) * q.y);
        double cosy = 1.0 - 2.0 * (double(q.y) * q.y + double(q.z) * q.z);
        double a = std::atan2(siny, cosy);
        double tau = 2.0 * 3.14159265358979323846;
        if (a < 0) a += tau;
        if (a >= tau) a -= tau;
        return float(a);
    }

    // Exactly GameObject::UpdatePackedRotation (src/server/game/Entities/GameObject/GameObject.cpp).
    inline int64_t PackRotation(Quat const& q)
    {
        static const int32_t PACK_YZ = 1 << 20;
        static const int32_t PACK_X = PACK_YZ << 1;
        static const int32_t PACK_YZ_MASK = (PACK_YZ << 1) - 1;
        static const int32_t PACK_X_MASK = (PACK_X << 1) - 1;
        int8_t w_sign = (q.w >= 0.f ? 1 : -1);
        int64_t x = int32_t(q.x * PACK_X) * w_sign & PACK_X_MASK;
        int64_t y = int32_t(q.y * PACK_YZ) * w_sign & PACK_YZ_MASK;
        int64_t z = int32_t(q.z * PACK_YZ) * w_sign & PACK_YZ_MASK;
        return z | (y << 21) | (x << 42);
    }

    inline float Dist3(float ax, float ay, float az, float bx, float by, float bz)
    {
        double dx = ax - bx, dy = ay - by, dz = az - bz;
        return float(std::sqrt(dx * dx + dy * dy + dz * dz));
    }

    // ---------------------------------------------------------------------------------------------- free list
    // GUID counters of builder objects that left the world, oldest first. A counter comes back out only after
    // `quarantineMs`: by then the object is surely out of the map's object store, and clients have dropped it.
    // (A stock 3.3.5a client keeps recently destroyed objects and would revive a reused GUID with its old
    // position; the full GUID also carries the entry, so only a reuse with the same entry can hit that cache.)
    class FreeList
    {
    public:
        struct Entry
        {
            uint32_t counter;
            uint32_t entry;
            uint64_t releasedMs;
        };

        explicit FreeList(uint64_t quarantineMs = 300000, size_t cap = 65536) : _quarantineMs(quarantineMs), _cap(cap) { }

        void SetQuarantine(uint64_t ms) { _quarantineMs = ms; }

        void Release(uint32_t counter, uint32_t entry, uint64_t nowMs)
        {
            if (counter == 0)
                return;
            if (_list.size() >= _cap)
                _list.pop_front();
            _list.push_back({ counter, entry, nowMs });
        }

        // The oldest counter out of quarantine, or 0. `inUse(counter, releasedEntry)` lets the caller veto one
        // that is somehow still in the world (it is dropped, not returned to the list).
        template<typename InUse>
        uint32_t Take(uint64_t nowMs, InUse inUse)
        {
            while (!_list.empty())
            {
                Entry e = _list.front();
                if (nowMs < e.releasedMs || nowMs - e.releasedMs < _quarantineMs)
                    return 0;
                _list.pop_front();
                if (!inUse(e.counter, e.entry))
                    return e.counter;
            }
            return 0;
        }

        size_t Size() const { return _list.size(); }

    private:
        std::deque<Entry> _list;
        uint64_t _quarantineMs;
        size_t _cap;
    };

    // ---------------------------------------------------------------------------------------------- rate
    class RateWindow
    {
    public:
        explicit RateWindow(uint32_t perSecond = 400) : _limit(perSecond) { }
        void SetLimit(uint32_t perSecond) { _limit = perSecond; }

        bool Allow(uint64_t nowMs)
        {
            uint64_t sec = nowMs / 1000;
            if (sec != _sec)
            {
                _sec = sec;
                _n = 0;
            }
            if (_limit == 0 || _n >= _limit)
                return false;
            ++_n;
            return true;
        }

    private:
        uint32_t _limit;
        uint64_t _sec = ~uint64_t(0);
        uint32_t _n = 0;
    };
}

#endif
