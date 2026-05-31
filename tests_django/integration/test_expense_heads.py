"""
Tests for the consultancy (NPC-ASS-6) + training (AI-850) expense-head
alignment and the combined-by-macro-category Revenue MIS rollup.
"""
import pytest
from django.urls import reverse

from core.models import (
    ExpenditureHead, ExpenditureItem, MacroExpenseCategory,
    TrainingExpenseHead, TrainingExpenseItem, TrainingProgramme,
)

pytestmark = pytest.mark.django_db


# ------------------------------------------------------------------
# Seeded heads (data migration 0012)
# ------------------------------------------------------------------

def test_consultancy_heads_seeded_with_macro():
    # Migration runs on the test DB, so all NPC-ASS-6 heads must be present.
    assert ExpenditureHead.objects.count() >= 28
    # Spot-check a few previously-missing heads
    for code in ["A4", "B3", "B4", "C3", "D3", "E13"]:
        assert ExpenditureHead.objects.filter(head_code=code).exists(), code
    # Every head has a real macro_category
    valid = set(dict(MacroExpenseCategory.choices))
    assert all(h.macro_category in valid for h in ExpenditureHead.objects.all())


def test_training_heads_seeded():
    assert TrainingExpenseHead.objects.count() == 17
    assert TrainingExpenseHead.objects.filter(head_code="T08").exists()  # honorarium
    assert TrainingExpenseHead.objects.filter(head_code="T14").exists()  # training kit


# ------------------------------------------------------------------
# Training itemized expense form
# ------------------------------------------------------------------

@pytest.fixture
def programme(db, office, team_leader_user):
    return TrainingProgramme.objects.create(
        programme_number="TRN-HQ-EXP-001", title="Expense Test",
        office=office, coordinator=team_leader_user, created_by=team_leader_user,
        stage="ANNOUNCED",
    )


def test_training_expense_form_renders(tl_client, programme):
    resp = tl_client.get(reverse("core:training_expenses", kwargs={"programme_id": programme.pk}))
    assert resp.status_code == 200
    assert b"Itemized" in resp.content or b"Training Expenses" in resp.content
    assert b"coming soon" not in resp.content


def test_training_expense_save(tl_client, programme):
    head = TrainingExpenseHead.objects.get(head_code="T01")
    head2 = TrainingExpenseHead.objects.get(head_code="T08")
    url = reverse("core:training_expenses", kwargs={"programme_id": programme.pk})
    resp = tl_client.post(url, {
        f"estimated_{head.id}": "50000", f"actual_{head.id}": "48000", f"remarks_{head.id}": "hotel",
        f"estimated_{head2.id}": "20000", f"actual_{head2.id}": "20000", f"remarks_{head2.id}": "",
    })
    assert resp.status_code == 302
    items = {i.head.head_code: i for i in TrainingExpenseItem.objects.filter(programme=programme)}
    assert items["T01"].actual_amount == 48000
    assert items["T08"].estimated_amount == 20000
    programme.refresh_from_db()
    assert programme.actual_expenditure == 68000  # sum of actuals


# ------------------------------------------------------------------
# Combined Revenue MIS expense rollup by macro-category
# ------------------------------------------------------------------

def test_revenue_mis_combined_expense_rollup(auth_client, office, sample_assignment):
    # Consultancy expense under FEE (A1) + Training expense under FEE (T08)
    a1 = ExpenditureHead.objects.get(head_code="A1")
    ExpenditureItem.objects.create(assignment=sample_assignment, head=a1, actual_amount=100000)

    prog = TrainingProgramme.objects.create(
        programme_number="TRN-HQ-MIS-1", title="x", office=office, stage="ANNOUNCED",
    )
    t08 = TrainingExpenseHead.objects.get(head_code="T08")
    TrainingExpenseItem.objects.create(programme=prog, head=t08, actual_amount=40000)

    resp = auth_client.get(reverse("core:mis_revenue"))
    assert resp.status_code == 200
    assert resp.context["show_expenses"] is True
    rows = {r["label"]: r for r in resp.context["expense_rows"]}
    fee = rows["Fees & Honorarium"]
    assert fee["consultancy"] == 100000
    assert fee["training"] == 40000
    assert fee["total"] == 140000
    assert resp.context["exp_total"] == 140000
