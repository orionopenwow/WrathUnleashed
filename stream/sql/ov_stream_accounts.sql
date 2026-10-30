-- acore_auth: accounts playing in the browser (streamed "mini" slice), kept inside the slice by
-- lua/ov_slices.lua. Written only by that script, on the worldserver's own auth-database
-- connection, when the website's gate sends the console command "ovstream mark|clear" over
-- SOAP (no new database user, no new network for wu-portal). stream-up.sh applies this file;
-- ov_slices.lua also creates the table if it is missing.
CREATE TABLE IF NOT EXISTS ov_stream_accounts (
  account_id INT UNSIGNED NOT NULL PRIMARY KEY,   -- account.id
  slice      VARCHAR(32)  NOT NULL,               -- "mini"
  max_tier   TINYINT UNSIGNED NOT NULL DEFAULT 1, -- tiers 0..max_tier of slices/mini.json
  expires_at INT UNSIGNED NOT NULL,               -- unix time; the gate's play session ends then
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Housekeeping: rows past their time do nothing (the script ignores them); this drops them.
DELETE FROM ov_stream_accounts WHERE expires_at < UNIX_TIMESTAMP() - 86400;
