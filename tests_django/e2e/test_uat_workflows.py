"""
End-to-end multi-role UAT: drive every lifecycle through the real HTTP views,
acting as the correct role at each step, and assert every state transition.

This is the automated equivalent of a human doing UAT — officer registers,
GH approves, TL fills + submits sections, GH approves each, system auto-activates,
finance invoices + records payment + recognizes 80-20 on surplus, etc.
"""
import pytest

from core import uat_workflows as wf
from core.models import Office, Officer, OfficerRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def uat(db):
    """Build one office + one user per role, all logged-in clients."""
    office = Office.objects.create(office_id="HQ", office_name="NPC HQ",
                                   officer_count=10, annual_revenue_target=600.0)

    def mk(oid, email, role):
        u = Officer.objects.create_user(email=email, officer_id=oid, name=oid.title(),
                                        office=office, password="uatpass123",
                                        admin_role_id=role)
        if role and role not in ("",):
            OfficerRole.objects.create(officer=u, role_type=role, scope_type="GLOBAL",
                                       is_primary=True)
        return u

    admin = mk("ADMIN", "admin@uat.gov.in", "ADMIN")
    gh = mk("GH01", "gh@uat.gov.in", "GROUP_HEAD")
    ddg = mk("DDG01", "ddg@uat.gov.in", "DDG-I")
    tl = mk("TL01", "tl@uat.gov.in", "TEAM_LEADER")
    off = mk("OFF01", "officer@uat.gov.in", "")
    off2 = mk("OFF02", "officer2@uat.gov.in", "")
    fin = mk("FIN01", "finance@uat.gov.in", "FINANCE")

    return {
        "office": office,
        "admin": admin, "gh": gh, "ddg": ddg, "tl": tl,
        "off": off, "off2": off2, "fin": fin,
        "c_admin": wf.login_as("admin@uat.gov.in"),
        "c_gh": wf.login_as("gh@uat.gov.in"),
        "c_tl": wf.login_as("tl@uat.gov.in"),
        "c_off": wf.login_as("officer@uat.gov.in"),
        "c_fin": wf.login_as("finance@uat.gov.in"),
    }


# ---------------------------------------------------------------------------
# 1. CONSULTANCY full lifecycle
# ---------------------------------------------------------------------------

def test_consultancy_full_lifecycle(uat):
    # Officer registers
    a = wf.register_assignment(uat["c_off"], "UAT Consultancy WO", uat["office"].office_id)
    assert a.registration_status == "PENDING_APPROVAL"

    # GH approves registration -> TL_ASSIGNMENT stage
    a = wf.approve_registration(uat["c_gh"], a)
    assert a.registration_status == "APPROVED"
    assert a.workflow_stage == "TL_ASSIGNMENT"

    # GH assigns TL -> DETAIL_ENTRY
    a = wf.assign_tl(uat["c_gh"], a, uat["tl"])
    assert a.team_leader_id == "TL01"
    assert a.workflow_stage == "DETAIL_ENTRY"

    # TL fills milestones + revenue, submits all 5 sections
    wf.add_milestone(uat["c_tl"], a, invoice_amount="50")
    wf.set_revenue_shares(uat["c_tl"], a, [(uat["tl"], 60), (uat["off"], 40)])
    for section in ("cost", "team", "milestone", "revenue"):
        wf.submit_section(uat["c_tl"], a, section)

    # GH approves all 5 sections (page-1 + the 4 progressive) -> auto-activate
    wf.approve_page1(uat["c_gh"], a)  # WO-Basic / approval_status
    for section in ("cost", "team", "milestone", "revenue"):
        wf.approve_section(uat["c_gh"], a, section)
    a.refresh_from_db()
    assert a.approval_status == "APPROVED"
    assert a.all_sections_approved(), "all 5 sections must be approved"
    assert a.workflow_stage == "ACTIVE", "WO should auto-activate after all sections approved"

    # Finance: raise invoice, approve (80%), record payment (20%)
    inv = wf.raise_invoice(uat["c_tl"], a, amount=50)
    assert inv is not None
    inv = wf.approve_invoice(uat["c_fin"], inv)
    assert inv.status == "APPROVED"
    assert inv.revenue_recognized_80 == pytest.approx(40.0)  # 80% of 50 (zero exp)
    inv = wf.record_payment(uat["c_fin"], inv, amount=50)
    from core.models import PaymentReceipt
    pmt = PaymentReceipt.objects.filter(invoice_request=inv).first()
    assert pmt is not None
    assert pmt.revenue_recognized_20 == pytest.approx(10.0)  # 20% of 50


# ---------------------------------------------------------------------------
# 2. TRAINING full lifecycle (with expenditure -> surplus split)
# ---------------------------------------------------------------------------

def test_training_full_lifecycle(uat):
    p = wf.create_training(uat["c_tl"], "UAT Training Prog", uat["office"].office_id)
    assert p is not None
    # faculty 60/40
    wf.set_faculty(uat["c_tl"], p, [(uat["tl"], "PRIMARY", 60, 2),
                                    (uat["off"], "CO_TRAINER", 40, 1)])
    # completion: invoice 56000, expenditure 16000 -> surplus 40000, 80% = 32000
    p = wf.register_completion(uat["c_tl"], p, invoice_amount=56000, expenditure=16000)
    assert p.completion_registered
    assert p.revenue_recognized_80 == pytest.approx(40000 * 0.80)
    # payment 56000 -> surplus 40000, 20% = 8000
    p = wf.record_training_payment(uat["c_tl"], p, amount=56000)
    assert p.payment_recorded
    assert p.revenue_recognized_20 == pytest.approx(40000 * 0.20)

    from core.models import TrainingRevenueLedger
    led = TrainingRevenueLedger.objects.filter(programme=p)
    # 2 faculty x 2 tranches = 4 ledger rows
    assert led.count() == 4
    # total to faculty = full surplus
    assert sum(l.amount for l in led) == pytest.approx(40000.0)


# ---------------------------------------------------------------------------
# 3. PRE-WO + NON-REVENUE
# ---------------------------------------------------------------------------

def test_pre_wo_lifecycle(uat):
    r = wf.create_pre_wo(uat["c_off"], "UAT Enquiry", uat["office"].office_id)
    assert r.approval_status == "PENDING"
    r = wf.approve_pre_wo(uat["c_gh"], r)
    assert r.approval_status == "APPROVED"
    r = wf.close_pre_wo(uat["c_gh"], r, outcome="DROPPED")
    assert r.outcome == "DROPPED"


def test_non_revenue_lifecycle(uat):
    nr = wf.create_non_revenue(uat["c_off"], "UAT Dev Work", uat["office"].office_id, man_days="4")
    assert nr.approval_status == "PENDING"
    assert nr.man_days == 4
    nr = wf.approve_non_revenue(uat["c_gh"], nr, officer=uat["off"])
    assert nr.approval_status == "APPROVED"
    assert nr.status == "IN_PROGRESS"
    nr = wf.complete_non_revenue(uat["c_gh"], nr)
    assert nr.status == "COMPLETED"


# ---------------------------------------------------------------------------
# 4. UTILIZATION chain (officer submits, TL approves, head rectifies, finalize)
# ---------------------------------------------------------------------------

def test_utilization_lifecycle(uat):
    # Need an active assignment for the claim to attach to
    a = wf.register_assignment(uat["c_off"], "UAT Util WO", uat["office"].office_id)
    wf.approve_registration(uat["c_gh"], a)
    wf.assign_tl(uat["c_gh"], a, uat["tl"])

    claim = wf.create_claim(uat["c_off"], a, man_days="5")
    assert claim.status == "DRAFT"
    claim = wf.submit_claim(uat["c_off"], claim)
    assert claim.status == "SUBMITTED"
    claim = wf.tl_approve_claim(uat["c_tl"], claim)
    assert claim.status == "TL_APPROVED"
    claim = wf.head_rectify_claim(uat["c_gh"], claim, days=4)
    assert claim.status == "HEAD_RECTIFIED"
    assert claim.rectified_days == 4
    claim = wf.finalize_claim(uat["c_gh"], claim)
    assert claim.status == "FINAL"
