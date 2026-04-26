# Runbook: Restore from Backup

**Purpose:** Restore the PMS Portal database (and optionally uploads) from a
backup produced by `backup_db` / `backup_files`.

**When to use:**
- DR drill (M0-REL-06) — quarterly rehearsal
- Real disaster: production DB corruption, accidental DROP, ransomware
- Cloning prod state to a sandbox for debugging

**Severity:** P1 if real outage. Always test in sandbox first.

---

## Pre-flight checklist

Before running ANY restore command, confirm:

- [ ] You have the **right backup file** — name pattern `db_YYYY-MM-DD_HHMMSS.sql.gz` (DB) or `files_YYYY-MM-DD_HHMMSS.tar.gz` (uploads).
- [ ] You know the **target environment** — production / staging / sandbox? Restoring an old prod backup ON TOP of current prod is destructive — see "If you must restore over production" below.
- [ ] Maintenance mode is **enabled** if restoring over production (see [enable-maintenance-mode.md](enable-maintenance-mode.md) — TBD).
- [ ] All users are logged out / no in-flight transactions.

---

## Steps

### 1. Pick the backup file

DirectAdmin → File Manager → `/home/npcindia/pms_data/backups/`

Choose the most recent good backup. Verify it's non-empty (>1 KB) and not the result of a failed cron run (check `/home/npcindia/logs/backup.log` if unsure).

### 2. Dry-run the restore command (SAFE — does not modify anything)

DirectAdmin → Setup Python App → Manage → "Execute python script". Paste:

```
/home/npcindia/pms_app/manage.py restore_db /home/npcindia/pms_data/backups/db_<DATE>_<TIME>.sql.gz
```

Expected output ends with:
```
DRY RUN. Re-run with --confirm to actually restore.
```

If you see an error here, do NOT proceed. Most common error: `mysql binary not found` — fix PATH in the cron / panel before continuing.

### 3. Restore into a sandbox database first (RECOMMENDED for DR drill)

In DirectAdmin → Databases, create a new DB called `npcindia_pms_sandbox` (separate user OK; same password is fine for the drill).

Then run with `--target-db`:

```
/home/npcindia/pms_app/manage.py restore_db /home/npcindia/pms_data/backups/db_<DATE>_<TIME>.sql.gz --confirm --target-db npcindia_pms_sandbox
```

Expected output:
```
Restored ... into npcindia_pms_sandbox
Restore complete. Run `manage.py verify_restore` next to validate.
```

Run validation:

```
/home/npcindia/pms_app/manage.py verify_restore
```

(Note: `verify_restore` runs against the **configured** DB — for sandbox testing, temporarily flip `MYSQL_DB=npcindia_pms_sandbox` in `local_settings.py`, run verify_restore, then flip back.)

Expected: 8 PASS, 0 FAIL.

### 4. If you must restore OVER production (DRP scenario only)

**This is destructive.** Existing production data after the backup time will be lost. Confirm with the project sponsor before proceeding.

```
/home/npcindia/pms_app/manage.py restore_db /home/npcindia/pms_data/backups/db_<DATE>_<TIME>.sql.gz --confirm
```

For SQLite (dev only): a side-copy of the current DB is automatically saved as `db.sqlite3.pre-restore-<timestamp>` next to the original. For MariaDB: there is **no automatic side-copy** — take a fresh `backup_db` first if anything is salvageable.

After restore:
- Run `manage.py verify_restore` — must show 8 PASS.
- Restart the app from the Python App panel.
- Disable maintenance mode.
- Email the team: "Restore complete; resumed at <time>; backup used was <date>."

### 5. Restore uploads (if needed)

```
cd /home/npcindia/pms_data
mv uploads uploads.pre-restore-$(date +%Y%m%d_%H%M%S)
tar -xzf backups/files_<DATE>_<TIME>.tar.gz
# This unpacks into ./uploads/
```

(For File Manager users: extract the .tar.gz via "Extract" right-click menu, then rename the existing uploads folder.)

---

## Verification (always)

After any restore:

1. `manage.py verify_restore` returns 8 PASS, 0 FAIL.
2. Open `https://pms.npcindia.info/` → log in as admin → see the dashboard with expected data.
3. Check 2-3 known assignments — workflow stages and financial totals look right.
4. Check `/health/` endpoint returns 200 with `database: connected`.

---

## DR drill schedule (M0-REL-06)

Quarterly (Mar / Jun / Sep / Dec — first week). Cycle:

1. Pick the most recent daily backup.
2. Restore into sandbox per Section 3.
3. Run verify_restore.
4. Record outcome in `docs/runbooks/dr-drill-log.md` with date, backup file used, restore time, validation result.

If a drill fails: open a P1 incident, root-cause, fix backup or restore code, re-run drill within 7 days.

---

## Rollback (if restore went wrong)

- **SQLite (dev):** copy back the side-copy file (`db.sqlite3.pre-restore-*`).
- **MariaDB (prod):** restore the most recent good backup (one before the bad one). There is no in-place undo.

---

## Escalation

Per [docs/m0/M0-Foundation-Baseline-Generic-v3.0](../../M0-Foundation-Baseline-Generic-v3.0.md) Part 11:
- Backup failed (one day) → P2, SA in 24h
- Backup failed (multiple days) → P1, SA in 4h
- Restore drill failed → P1, audit + compliance immediately
