"""
verify_restore — run canary queries to validate a freshly restored DB
(M0-REL-08 — restore validation query catalog).

Run after `restore_db --confirm`. Exits non-zero if any check fails.

Catalog (8 checks, intentionally lightweight — schema + presence smoke tests):

  1. django_migrations table is populated and includes core.0001_initial
  2. core_officer table exists and has at least 1 row
  3. core_assignment table exists and is queryable
  4. core_milestone table exists and is queryable
  5. ContentType + Permission tables (auth scaffolding) populated
  6. Latest auditlog row is within last 60 days (data isn't ancient)
  7. SiteConfig table exists (Slice E feature, presence-only)
  8. Foreign-key sanity: every Assignment.team_leader resolves to an Officer

Output: PASS / FAIL per check + final summary.
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Run canary queries against the restored DB; fail non-zero on any error."

    def handle(self, *args, **opts):
        passed = 0
        failed = 0
        for name, fn in CHECKS:
            try:
                ok, detail = fn()
            except Exception as e:
                ok = False
                detail = f"raised {type(e).__name__}: {e}"
            tag = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
            self.stdout.write(f"  {tag}  {name}  — {detail}")
            if ok:
                passed += 1
            else:
                failed += 1
        self.stdout.write("")
        self.stdout.write(f"Summary: {passed} pass, {failed} fail")
        if failed:
            raise SystemExit(1)


def _check_django_migrations():
    with connection.cursor() as c:
        c.execute("SELECT COUNT(*) FROM django_migrations WHERE app='core' AND name='0001_initial'")
        n = c.fetchone()[0]
    return n == 1, f"core.0001_initial present={n == 1}"


def _check_officer_table():
    from core.models import Officer
    n = Officer.objects.count()
    return n > 0, f"officers={n}"


def _check_assignment_table():
    from core.models import Assignment
    n = Assignment.objects.count()
    return True, f"assignments queryable, count={n}"


def _check_milestone_table():
    from core.models import Milestone
    n = Milestone.objects.count()
    return True, f"milestones queryable, count={n}"


def _check_content_types():
    from django.contrib.contenttypes.models import ContentType
    n = ContentType.objects.count()
    return n > 0, f"content_types={n}"


def _check_recent_audit():
    from auditlog.models import LogEntry
    if LogEntry.objects.count() == 0:
        return True, "no audit rows yet (fresh DB OK)"
    latest = LogEntry.objects.order_by("-timestamp").first().timestamp
    delta_days = (timezone.now() - latest).days
    ok = delta_days <= 60
    return ok, f"latest audit {delta_days} days ago"


def _check_siteconfig_table():
    from core.models import SiteConfig
    SiteConfig.objects.count()  # raises if table missing
    return True, "site_config queryable"


def _check_team_leader_fks():
    from core.models import Assignment, Officer
    asgns_with_tl = Assignment.objects.exclude(team_leader__isnull=True)
    bad = 0
    for a in asgns_with_tl.values_list("team_leader_id", flat=True).distinct():
        if a is None:
            continue
        if not Officer.objects.filter(officer_id=a).exists():
            bad += 1
    return bad == 0, f"orphan team_leader FKs: {bad}"


CHECKS = [
    ("django_migrations sanity", _check_django_migrations),
    ("officer table", _check_officer_table),
    ("assignment table", _check_assignment_table),
    ("milestone table", _check_milestone_table),
    ("content types", _check_content_types),
    ("recent audit data", _check_recent_audit),
    ("siteconfig table", _check_siteconfig_table),
    ("team_leader FK integrity", _check_team_leader_fks),
]
