-- Schema v2: each login has a kind.
--   personal: a person's own login (bthanujan.mahendran)
--   service:  a service account, the only kind allowed as a sudo target (svc_*)
--   system:   a shared or system login (git, bench, ec2-user)
-- The migration classifies existing rows with the same rules as
-- convert.classify_login(): svc_* is service, git/bench/ec2-user is system,
-- everything else is personal.

ALTER TABLE login ADD COLUMN kind TEXT NOT NULL DEFAULT 'personal'
  CHECK (kind IN ('personal', 'service', 'system'));

UPDATE login SET kind = CASE
  WHEN user LIKE 'svc\_%' ESCAPE '\' THEN 'service'
  WHEN user IN ('git', 'bench', 'ec2-user') THEN 'system'
  ELSE 'personal'
END;

PRAGMA user_version = 2;
