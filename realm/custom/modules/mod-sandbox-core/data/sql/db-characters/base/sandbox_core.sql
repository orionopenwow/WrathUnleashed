-- mod-sandbox-core (characters database). SandboxCoreWorldScript::OnStartup creates the same tables if missing.

-- A prop's size, set through the module; re-applied when Lua spawns it without one.
CREATE TABLE IF NOT EXISTS `sandbox_go_scale` (
  `prop_id` INT UNSIGNED NOT NULL PRIMARY KEY,
  `scale` FLOAT NOT NULL DEFAULT 1,
  `updated_at` INT UNSIGNED NOT NULL DEFAULT 0
);

-- The builder objects the module spawned: the live GUID counter, position and rotation (the quaternion, as in
-- the world's gameobject.rotation0..3) and size. ov_build.lua's mod_builder_props stays the record of the prop
-- itself; this is the core-side mirror, for GMs and tools.
CREATE TABLE IF NOT EXISTS `sandbox_go_registry` (
  `prop_id` INT UNSIGNED NOT NULL PRIMARY KEY,
  `map` SMALLINT UNSIGNED NOT NULL,
  `entry` INT UNSIGNED NOT NULL,
  `guid_low` INT UNSIGNED NOT NULL,
  `x` FLOAT NOT NULL,
  `y` FLOAT NOT NULL,
  `z` FLOAT NOT NULL,
  `rotation0` FLOAT NOT NULL DEFAULT 0,
  `rotation1` FLOAT NOT NULL DEFAULT 0,
  `rotation2` FLOAT NOT NULL DEFAULT 0,
  `rotation3` FLOAT NOT NULL DEFAULT 1,
  `scale` FLOAT NOT NULL DEFAULT 1,
  `updated_at` INT UNSIGNED NOT NULL DEFAULT 0
);

-- One row while the module runs (written at startup, removed at shutdown). ov_sandbox_core.lua reads it before
-- it sends any bridge packet, so a realm without the module never sees one.
CREATE TABLE IF NOT EXISTS `sandbox_core_status` (
  `id` TINYINT UNSIGNED NOT NULL PRIMARY KEY,
  `version` INT UNSIGNED NOT NULL,
  `move_mode` TINYINT UNSIGNED NOT NULL DEFAULT 0,
  `started_at` INT UNSIGNED NOT NULL DEFAULT 0
);
