-- Email sign-in codes (same as migration a7d2c91e4b55). Normally just run `flask db upgrade`; use this only to create the table by hand.
CREATE TABLE IF NOT EXISTS email_otp (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL,
    otp_hash    VARCHAR(64)  NOT NULL,                       -- HMAC-SHA256 of the code, never the code
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ  NOT NULL,                       -- created_at + 5 minutes
    attempts    INTEGER      NOT NULL DEFAULT 0,             -- wrong guesses; 5 and the code is dead
    is_used     BOOLEAN      NOT NULL DEFAULT false,
    ip_address  VARCHAR(45)
);
CREATE INDEX IF NOT EXISTS ix_email_otp_email         ON email_otp (email);
CREATE INDEX IF NOT EXISTS ix_email_otp_expires_at    ON email_otp (expires_at);
CREATE INDEX IF NOT EXISTS ix_email_otp_ip_address    ON email_otp (ip_address);
CREATE INDEX IF NOT EXISTS ix_email_otp_email_created ON email_otp (email, created_at);
-- only if you created the table by hand, tell Alembic it exists:  UPDATE alembic_version SET version_num = 'a7d2c91e4b55';

-- Handy checks
SELECT id, email, created_at, expires_at, attempts, is_used, ip_address FROM email_otp ORDER BY id DESC LIMIT 20;
DELETE FROM email_otp WHERE expires_at < now() - interval '1 day';   -- manual clean-up (the app also does this on every send)
