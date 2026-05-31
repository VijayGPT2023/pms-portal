"""
seed_uat — populate the LOCAL dev database with realistic, browsable data by
driving the real workflows as each role (the same drivers the E2E test uses).

Leaves a DB you can log into and click through as any role:
    admin@uat.gov.in / gh@uat.gov.in / tl@uat.gov.in / officer@uat.gov.in /
    finance@uat.gov.in   (all password: uatpass123)

Creates, end-to-end:
    * 1 consultancy WO taken to ACTIVE + invoiced + paid (80-20 recognized)
    * 1 training programme completed + paid (surplus split to faculty)
    * 1 Pre-WO enquiry (approved) + 1 non-revenue task (completed)
    * 1 utilization claim taken through to FINAL

Idempotent-ish: re-running creates fresh activities (new titles each run via a
counter) but reuses the role users. SAFE FOR DEV/LOCAL ONLY — refuses to run
when DEBUG is False unless --force is given.

Usage:
    python manage.py seed_uat
    python manage.py seed_uat --force      # allow on non-DEBUG (careful!)
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import uat_workflows as wf
from core.models import Office, Officer, OfficerRole


# UAT-prefixed officer_ids so they never collide with imported/real officers.
ROLE_USERS = [
    ("UAT-ADM", "admin@uat.gov.in", "ADMIN", "UAT Admin"),
    ("UAT-GH", "gh@uat.gov.in", "GROUP_HEAD", "UAT Group Head"),
    ("UAT-DDG", "ddg@uat.gov.in", "DDG-I", "UAT DDG"),
    ("UAT-TL", "tl@uat.gov.in", "TEAM_LEADER", "UAT Team Leader"),
    ("UAT-OFF", "officer@uat.gov.in", "", "UAT Officer"),
    ("UAT-OFF2", "officer2@uat.gov.in", "", "UAT Officer 2"),
    ("UAT-FIN", "finance@uat.gov.in", "FINANCE", "UAT Finance"),
]


class Command(BaseCommand):
    help = "Seed local DB with browsable UAT data via real multi-role workflows."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Allow running when DEBUG is False (dangerous).")
        parser.add_argument("--office", default="HQ",
                            help="Office id to attach UAT users/activities to.")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError(
                "Refusing to run with DEBUG=False (this writes test data). "
                "Use --force only if you really mean to seed this environment."
            )

        # django-axes refuses Client.login() (no request object). The drivers
        # use the test Client, so disable axes for this command's session.
        settings.AXES_ENABLED = False
        # The test Client sends Host: testserver; allow it for this run.
        if "testserver" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

        office_id = opts["office"]
        office, _ = Office.objects.get_or_create(
            office_id=office_id,
            defaults={"office_name": f"{office_id} Office", "officer_count": 10,
                      "annual_revenue_target": 600.0},
        )

        users = {}
        for oid, email, role, name in ROLE_USERS:
            u = Officer.objects.filter(email=email).first()
            if not u:
                u = Officer.objects.create_user(email=email, officer_id=oid, name=name,
                                                office=office, password="uatpass123",
                                                admin_role_id=role)
            if role and not OfficerRole.objects.filter(officer=u, role_type=role).exists():
                OfficerRole.objects.create(officer=u, role_type=role,
                                           scope_type="GLOBAL", is_primary=True)
            users[email] = u

        c_admin = wf.login_as("admin@uat.gov.in")
        c_gh = wf.login_as("gh@uat.gov.in")
        c_tl = wf.login_as("tl@uat.gov.in")
        c_off = wf.login_as("officer@uat.gov.in")
        c_fin = wf.login_as("finance@uat.gov.in")
        tl, off, off2 = users["tl@uat.gov.in"], users["officer@uat.gov.in"], users["officer2@uat.gov.in"]

        # unique suffix so repeat runs don't clash on titles
        tag = timezone.now().strftime("%m%d-%H%M%S")
        out = self.stdout.write

        # --- Consultancy WO -> ACTIVE -> invoiced -> paid ---
        a = wf.register_assignment(c_off, f"UAT Consultancy {tag}", office_id)
        wf.approve_registration(c_gh, a)
        wf.assign_tl(c_gh, a, tl)
        wf.add_milestone(c_tl, a, invoice_amount="50")
        wf.set_revenue_shares(c_tl, a, [(tl, 60), (off, 40)])
        for s in ("cost", "team", "milestone", "revenue"):
            wf.submit_section(c_tl, a, s)
        wf.approve_page1(c_gh, a)
        for s in ("cost", "team", "milestone", "revenue"):
            wf.approve_section(c_gh, a, s)
        a.refresh_from_db()
        inv = wf.raise_invoice(c_tl, a, amount=50)
        if inv:
            wf.approve_invoice(c_fin, inv)
            wf.record_payment(c_fin, inv, amount=50)
        out(f"  Consultancy: {a.assignment_no} stage={a.workflow_stage}")

        # --- Training -> completed -> paid (surplus split) ---
        p = wf.create_training(c_tl, f"UAT Training {tag}", office_id)
        if p:
            wf.set_faculty(c_tl, p, [(tl, "PRIMARY", 60, 2), (off, "CO_TRAINER", 40, 1)])
            wf.register_completion(c_tl, p, invoice_amount=56000, expenditure=16000)
            wf.record_training_payment(c_tl, p, amount=56000)
            p.refresh_from_db()
            out(f"  Training: {p.programme_number} stage={p.stage} "
                f"recognized80={p.revenue_recognized_80:.0f}")

        # --- Pre-WO + Non-Revenue ---
        r = wf.create_pre_wo(c_off, f"UAT Enquiry {tag}", office_id)
        if r:
            wf.approve_pre_wo(c_gh, r)
            out(f"  Pre-WO: {r.record_number} {r.approval_status}")
        nr = wf.create_non_revenue(c_off, f"UAT Dev Work {tag}", office_id, man_days="4")
        if nr:
            wf.approve_non_revenue(c_gh, nr, officer=off)
            wf.complete_non_revenue(c_gh, nr)
            out(f"  Non-Revenue: {nr.suggestion_number} {nr.status}")

        # --- Utilization chain ---
        claim = wf.create_claim(c_off, a, man_days="5")
        if claim:
            wf.submit_claim(c_off, claim)
            wf.tl_approve_claim(c_tl, claim)
            wf.head_rectify_claim(c_gh, claim, days=4)
            wf.finalize_claim(c_gh, claim)
            out(f"  Utilization: {claim.claim_number} {claim.status}")

        out(self.style.SUCCESS(
            "\nUAT seed complete. Log in (password uatpass123) as:\n"
            "  admin@uat.gov.in (Admin) · gh@uat.gov.in (Group Head) · "
            "tl@uat.gov.in (TL) · officer@uat.gov.in (Officer) · "
            "finance@uat.gov.in (Finance)"))
