// g++ -std=c++17 -Wall -Wextra -Werror -I../src test_sandbox_math.cpp -o /tmp/t && /tmp/t
// The module's pure helpers: the quaternion G3D builds for SetWorldRotationAngles, the yaw it implies, the
// core's packed rotation, the free list's quarantine and the rate window. No AzerothCore headers needed.
#include "SandboxMath.h"

#include <cmath>
#include <cstdio>

using namespace SandboxCore;

static int g_pass = 0, g_fail = 0;
static void check(char const* name, bool ok)
{
    if (ok) { ++g_pass; std::printf("PASS %s\n", name); }
    else { ++g_fail; std::printf("FAIL %s\n", name); }
}
static bool near(double a, double b, double eps = 1e-5) { return std::fabs(a - b) <= eps; }

// R = Rz(z) * Ry(y) * Rx(x), as G3D::Matrix3::fromEulerAnglesZYX builds it.
static void eulerZYX(double z, double y, double x, double m[3][3])
{
    double cz = std::cos(z), sz = std::sin(z), cy = std::cos(y), sy = std::sin(y), cx = std::cos(x), sx = std::sin(x);
    double Rz[3][3] = { { cz, -sz, 0 }, { sz, cz, 0 }, { 0, 0, 1 } };
    double Ry[3][3] = { { cy, 0, sy }, { 0, 1, 0 }, { -sy, 0, cy } };
    double Rx[3][3] = { { 1, 0, 0 }, { 0, cx, -sx }, { 0, sx, cx } };
    double t[3][3] = {};
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) for (int k = 0; k < 3; ++k) t[i][j] += Rz[i][k] * Ry[k][j];
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) { m[i][j] = 0; for (int k = 0; k < 3; ++k) m[i][j] += t[i][k] * Rx[k][j]; }
}

static void quatToMatrix(Quat const& q, double m[3][3])
{
    double x = q.x, y = q.y, z = q.z, w = q.w;
    m[0][0] = 1 - 2 * (y * y + z * z); m[0][1] = 2 * (x * y - z * w);     m[0][2] = 2 * (x * z + y * w);
    m[1][0] = 2 * (x * y + z * w);     m[1][1] = 1 - 2 * (x * x + z * z); m[1][2] = 2 * (y * z - x * w);
    m[2][0] = 2 * (x * z - y * w);     m[2][1] = 2 * (y * z + x * w);     m[2][2] = 1 - 2 * (x * x + y * y);
}

static bool sameRotation(double yaw, double pitch, double roll)
{
    Quat q = QuatFromYawPitchRoll(float(yaw), float(pitch), float(roll));
    double a[3][3], b[3][3];
    eulerZYX(yaw, pitch, roll, a);
    quatToMatrix(q, b);
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) if (!near(a[i][j], b[i][j], 1e-5)) return false;
    return near(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w, 1.0, 1e-5);
}

int main()
{
    const double PI = 3.14159265358979323846;

    // the quaternion is the matrix G3D builds
    check("ypr matches Rz*Ry*Rx (yaw only)", sameRotation(1.0, 0, 0));
    check("ypr matches Rz*Ry*Rx (all three)", sameRotation(1.0, 0.3, -0.2));
    check("ypr matches Rz*Ry*Rx (big angles)", sameRotation(-2.5, 1.2, 3.0));
    check("ypr matches Rz*Ry*Rx (pitch 90)", sameRotation(0.4, PI / 2, 0.1));

    // yaw alone is the core's fromAxisAngleRotation(unitZ, o), the quaternion every plain spawn gets
    {
        Quat q = QuatFromYawPitchRoll(0.75f, 0, 0);
        check("yaw only = axis-angle about z", near(q.x, 0) && near(q.y, 0) && near(q.z, std::sin(0.375)) && near(q.w, std::cos(0.375)));
    }

    // the heading
    check("YawOf yaw only", near(YawOf(QuatFromYawPitchRoll(1.0f, 0, 0)), 1.0));
    check("YawOf with pitch and roll", near(YawOf(QuatFromYawPitchRoll(1.0f, 0.3f, -0.2f)), 1.0, 1e-4));
    check("YawOf wraps negative into [0, 2pi)", near(YawOf(QuatFromYawPitchRoll(-1.0f, 0, 0)), 2 * PI - 1.0, 1e-4));
    check("YawOf identity", near(YawOf(Quat{}), 0));

    // normalizing
    {
        Quat q{ 0, 0, 2, 2 };
        check("normalize scales to unit", NormalizeQuat(q) && near(q.z, std::sqrt(0.5)) && near(q.w, std::sqrt(0.5)));
        Quat zero{ 0, 0, 0, 0 };
        check("normalize refuses zero", !NormalizeQuat(zero));
        Quat bad{ NAN, 0, 0, 1 };
        check("normalize refuses NaN", !NormalizeQuat(bad));
        Quat inf{ 0, INFINITY, 0, 1 };
        check("normalize refuses infinity", !NormalizeQuat(inf));
    }

    // packing, exactly as GameObject::UpdatePackedRotation
    {
        check("pack identity is 0", PackRotation(Quat{}) == 0);
        Quat q = QuatFromYawPitchRoll(1.0f, 0.3f, -0.2f);
        Quat n{ -q.x, -q.y, -q.z, -q.w };
        check("pack: q and -q pack the same", PackRotation(q) == PackRotation(n));
        Quat yaw = QuatFromYawPitchRoll(float(PI / 2), 0, 0);
        int64_t z = int32_t(yaw.z * (1 << 20)) & ((1 << 21) - 1);
        check("pack yaw only: z in the low 21 bits", PackRotation(yaw) == z);
        // the vectors ov_sandbox_core.lua / test_ov_build.lua compare against
        std::printf("VECTOR ypr(1.0,0.3,-0.2) = %.6f %.6f %.6f %.6f\n", q.x, q.y, q.z, q.w);
    }

    // the free list
    {
        FreeList fl(1000);
        auto none = [](uint32_t, uint32_t) { return false; };
        check("free list empty gives 0", fl.Take(5000, none) == 0);
        fl.Release(0, 1, 0);
        check("counter 0 is never kept", fl.Size() == 0);
        fl.Release(10, 100, 1000);
        fl.Release(11, 100, 1500);
        check("still in quarantine", fl.Take(1999, none) == 0 && fl.Size() == 2);
        check("oldest first after quarantine", fl.Take(2000, none) == 10);
        check("next one waits for its own time", fl.Take(2000, none) == 0 && fl.Take(2500, none) == 11);
        fl.Release(12, 100, 0);
        fl.Release(13, 100, 0);
        auto busy12 = [](uint32_t c, uint32_t) { return c == 12; };
        check("a counter still in the world is dropped, the next one given", fl.Take(5000, busy12) == 13 && fl.Size() == 0);
        FreeList capped(0, 2);
        capped.Release(1, 1, 0); capped.Release(2, 1, 0); capped.Release(3, 1, 0);
        check("cap drops the oldest", capped.Size() == 2 && capped.Take(0, none) == 2);
        FreeList clock(1000);
        clock.Release(7, 1, 5000);
        check("a clock that went back keeps the counter", clock.Take(4000, none) == 0 && clock.Size() == 1);
    }

    // the rate window
    {
        RateWindow r(3);
        bool a = r.Allow(1000), b = r.Allow(1100), c = r.Allow(1999), d = r.Allow(1999);
        check("three in a second, not four", a && b && c && !d);
        check("next second starts over", r.Allow(2000));
        RateWindow off(0);
        check("limit 0 allows nothing", !off.Allow(0));
    }

    // protocol constants Lua mirrors (ov_sandbox_core.lua)
    check("bridge opcode is CMSG_DBLOOKUP", BRIDGE_OPCODE == 0x002);
    check("magics", REQUEST_MAGIC == 0x53425831u && REPLY_MAGIC == 0x53425852u && PROTOCOL_VERSION == 1);
    check("ops", OP_PING == 1 && OP_SPAWN == 2 && OP_MOVE == 3 && OP_SCALE == 4 && OP_DESPAWN == 5 && OP_FIND == 6);

    std::printf("%d passed, %d failed\n", g_pass, g_fail);
    return g_fail == 0 ? 0 : 1;
}
