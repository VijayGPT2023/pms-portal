"""
Integration tests for Training two-step 80-20 revenue recognition (SCOPE_V2 §3.3).

Step 1: register completion -> 80% recognized + split to faculty.
Step 2: record payment -> 20% recognized + split to faculty.
Ordering guard, idempotency guard, and faculty split correctness.
"""
import pytest
from django.urls import reverse

from core.models import (
    Officer, TrainerAllocation, TrainingProgramme, TrainingRevenueLedger,
)


@pytest.fixture
def programme(db, office, team_leader_user):
    return TrainingProgramme.objects.create(
        programme_number="TRN-HQ-202605-001",
        title="Lean Manufacturing Workshop",
        office=office,
        coordinator=team_leader_user,
        created_by=team_leader_user,
        budgeted_participants=30,
        fee_per_participant=2000,
        budgeted_revenue=60000,
        stage="ANNOUNCED",
    )


@pytest.fixture
def two_faculty(db, programme, team_leader_user, officer_user):
    TrainerAllocation.objects.create(
        programme=programme, officer=team_leader_user,
        trainer_role="PRIMARY", revenue_share_percent=60,
    )
    TrainerAllocation.objects.create(
        programme=programme, officer=officer_user,
        trainer_role="CO_TRAINER", revenue_share_percent=40,
    )


def test_register_completion_recognizes_80_of_SURPLUS(tl_client, programme, two_faculty):
    """80% is recognized on SURPLUS (invoice − direct expenditure), not gross."""
    url = reverse("core:training_register_completion", kwargs={"programme_id": programme.pk})
    resp = tl_client.post(url, {
        "actual_participants": "28",
        "actual_expenditure": "15000",
        "invoice_number": "INV/TRN/001",
        "invoice_amount": "56000",
        "invoice_date": "2026-05-20",
    })
    assert resp.status_code == 302
    programme.refresh_from_db()
    assert programme.completion_registered is True
    # surplus = 56000 − 15000 = 41000 ; 80% = 32800
    surplus = 56000 - 15000
    assert programme.revenue_recognized_80 == pytest.approx(surplus * 0.80)
    assert programme.stage == "CONDUCTED"

    # Split 80% of surplus (32800): 60/40 => 19680 / 13120
    ledger = {l.officer_id: l.amount for l in TrainingRevenueLedger.objects.filter(
        programme=programme, revenue_type="COMPLETION_80")}
    assert ledger["TL001"] == pytest.approx(surplus * 0.80 * 0.60)
    assert ledger["OFF001"] == pytest.approx(surplus * 0.80 * 0.40)


def test_zero_expenditure_shares_full_gross(tl_client, programme, two_faculty):
    """With no expenditure, surplus = gross, so 80% of invoice (back-compat)."""
    url = reverse("core:training_register_completion", kwargs={"programme_id": programme.pk})
    tl_client.post(url, {"invoice_amount": "56000", "invoice_number": "INV/Z"})
    programme.refresh_from_db()
    assert programme.revenue_recognized_80 == pytest.approx(56000 * 0.80)


def test_expenditure_exceeds_invoice_floors_at_zero(tl_client, programme, two_faculty):
    """If direct expenditure > invoice, surplus floors at 0 — no negative share."""
    url = reverse("core:training_register_completion", kwargs={"programme_id": programme.pk})
    tl_client.post(url, {"invoice_amount": "10000", "actual_expenditure": "15000",
                         "invoice_number": "INV/NEG"})
    programme.refresh_from_db()
    assert programme.revenue_recognized_80 == 0.0


def test_payment_requires_completion_first(tl_client, programme, two_faculty):
    url = reverse("core:training_record_payment", kwargs={"programme_id": programme.pk})
    resp = tl_client.post(url, {"payment_amount": "56000"})
    assert resp.status_code == 302
    programme.refresh_from_db()
    assert programme.payment_recorded is False
    assert programme.revenue_recognized_20 == 0


def test_record_payment_recognizes_20(tl_client, programme, two_faculty):
    # Step 1
    tl_client.post(reverse("core:training_register_completion", kwargs={"programme_id": programme.pk}), {
        "invoice_amount": "56000", "invoice_number": "INV/TRN/001",
    })
    # Step 2
    resp = tl_client.post(reverse("core:training_record_payment", kwargs={"programme_id": programme.pk}), {
        "payment_amount": "56000", "payment_date": "2026-06-10",
    })
    assert resp.status_code == 302
    programme.refresh_from_db()
    assert programme.payment_recorded is True
    assert programme.revenue_recognized_20 == pytest.approx(56000 * 0.20)
    assert programme.stage == "CLOSED"

    # 20% of 56000 = 11200; 60/40 => 6720 / 4480
    ledger = {l.officer_id: l.amount for l in TrainingRevenueLedger.objects.filter(
        programme=programme, revenue_type="PAYMENT_20")}
    assert ledger["TL001"] == pytest.approx(11200 * 0.60)
    assert ledger["OFF001"] == pytest.approx(11200 * 0.40)


def test_completion_is_idempotent(tl_client, programme, two_faculty):
    url = reverse("core:training_register_completion", kwargs={"programme_id": programme.pk})
    tl_client.post(url, {"invoice_amount": "56000"})
    tl_client.post(url, {"invoice_amount": "99999"})  # second attempt blocked
    programme.refresh_from_db()
    assert programme.revenue_recognized_80 == pytest.approx(56000 * 0.80)
    assert TrainingRevenueLedger.objects.filter(
        programme=programme, revenue_type="COMPLETION_80").count() == 2  # 2 faculty, one round


def test_completion_requires_invoice_amount(tl_client, programme, two_faculty):
    url = reverse("core:training_register_completion", kwargs={"programme_id": programme.pk})
    resp = tl_client.post(url, {"invoice_amount": "0"})
    assert resp.status_code == 302
    programme.refresh_from_db()
    assert programme.completion_registered is False


def test_even_split_when_shares_not_100(tl_client, programme, team_leader_user, officer_user):
    # Two faculty but shares sum to 50, not 100 -> even split
    TrainerAllocation.objects.create(programme=programme, officer=team_leader_user, revenue_share_percent=30)
    TrainerAllocation.objects.create(programme=programme, officer=officer_user, revenue_share_percent=20)
    url = reverse("core:training_register_completion", kwargs={"programme_id": programme.pk})
    tl_client.post(url, {"invoice_amount": "10000"})  # 80% = 8000, even => 4000 each
    amounts = sorted(l.amount for l in TrainingRevenueLedger.objects.filter(programme=programme))
    assert amounts == pytest.approx([4000.0, 4000.0])


def test_expense_added_after_completion_recomputes_recognition(tl_client, programme, two_faculty):
    """The real UAT scenario: register completion FIRST (no expenditure yet),
    THEN add itemized expenses -> recognition must re-derive on surplus."""
    from core.models import TrainingExpenseHead, TrainingRevenueLedger
    # 1. Complete with zero expenditure -> 80% of gross 56000 = 44800
    tl_client.post(reverse("core:training_register_completion", kwargs={"programme_id": programme.pk}),
                   {"invoice_amount": "56000", "invoice_number": "INV/REC"})
    programme.refresh_from_db()
    assert programme.revenue_recognized_80 == pytest.approx(56000 * 0.80)

    # 2. Now add itemized expenditure of 16000 via the expense form
    h1 = TrainingExpenseHead.objects.get(head_code="T01")
    h2 = TrainingExpenseHead.objects.get(head_code="T08")
    resp = tl_client.post(reverse("core:training_expenses", kwargs={"programme_id": programme.pk}), {
        f"estimated_{h1.id}": "0", f"actual_{h1.id}": "10000", f"remarks_{h1.id}": "",
        f"estimated_{h2.id}": "0", f"actual_{h2.id}": "6000", f"remarks_{h2.id}": "",
    })
    assert resp.status_code == 302
    programme.refresh_from_db()
    # surplus = 56000 − 16000 = 40000 ; 80% = 32000 (recomputed!)
    assert programme.revenue_recognized_80 == pytest.approx(40000 * 0.80)
    # ledger rebuilt to the new amount (2 faculty, 60/40 of 32000)
    led = {l.officer_id: l.amount for l in TrainingRevenueLedger.objects.filter(
        programme=programme, revenue_type="COMPLETION_80")}
    assert sum(led.values()) == pytest.approx(32000.0)
