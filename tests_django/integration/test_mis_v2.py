"""
Smoke + scoping tests for MIS V2 dashboards (SCOPE_V2 §3.8, §10 access matrix).

Each dashboard renders for org/office/self roles, and scoping filters records.
"""
import pytest
from django.urls import reverse

from core.models import (
    NonRevenueSuggestion, OfficerRevenueLedger, PreWORecord, RevenueShare,
)


# ------------------------------------------------------------------
# Render smoke tests
# ------------------------------------------------------------------

def test_pre_wo_mis_renders(auth_client):
    resp = auth_client.get(reverse("core:mis_pre_wo"))
    assert resp.status_code == 200
    assert b"Pre-WO MIS" in resp.content


def test_revenue_mis_renders(auth_client):
    resp = auth_client.get(reverse("core:mis_revenue"))
    assert resp.status_code == 200
    assert b"Revenue MIS" in resp.content


def test_non_revenue_mis_renders(auth_client):
    resp = auth_client.get(reverse("core:mis_non_revenue"))
    assert resp.status_code == 200
    assert b"Non-Revenue MIS" in resp.content


def test_officer_dashboards_render(officer_client):
    for name in ("core:mis_pre_wo", "core:mis_revenue", "core:mis_non_revenue"):
        resp = officer_client.get(reverse(name))
        assert resp.status_code == 200, name


# ------------------------------------------------------------------
# Pre-WO funnel KPIs
# ------------------------------------------------------------------

def test_pre_wo_funnel_counts(auth_client, office):
    PreWORecord.objects.create(record_number="E1", stage="ENQUIRY", title="a", office=office)
    PreWORecord.objects.create(record_number="P1", stage="PROPOSAL", title="b", office=office,
                               outcome="CONVERTED_TO_WO")
    resp = auth_client.get(reverse("core:mis_pre_wo"))
    ctx = resp.context["kpis"]
    assert ctx["total"] == 2
    assert ctx["converted"] == 1
    assert ctx["conversion_rate"] == 50.0


# ------------------------------------------------------------------
# Non-Revenue man-day rollup
# ------------------------------------------------------------------

def test_non_revenue_mandays_sum(auth_client, office, officer_user):
    NonRevenueSuggestion.objects.create(
        suggestion_number="NR1", title="x", office=office, officer=officer_user,
        man_days=4, status="COMPLETED", approval_status="APPROVED",
    )
    NonRevenueSuggestion.objects.create(
        suggestion_number="NR2", title="y", office=office, officer=officer_user,
        man_days=6, status="IN_PROGRESS", approval_status="APPROVED",
    )
    resp = auth_client.get(reverse("core:mis_non_revenue"))
    kpis = resp.context["kpis"]
    assert kpis["total_man_days"] == 10
    assert kpis["completed"] == 1
    assert kpis["in_progress"] == 1


# ------------------------------------------------------------------
# Office scoping: a head sees only their office
# ------------------------------------------------------------------

def test_revenue_mis_scoped_to_office_for_head(head_client, office, regional_office,
                                               sample_assignment, team_leader_user):
    # Ledger entry on HQ assignment (sample_assignment is HQ) — RD head should NOT see it.
    OfficerRevenueLedger.objects.create(
        officer=team_leader_user, assignment=sample_assignment,
        revenue_type="INVOICE_80", share_percent=100, amount=1000,
        fy_period="2025-26", transaction_date="2026-05-01",
    )
    resp = head_client.get(reverse("core:mis_revenue"))
    # RD head's office is RDDEL; the ledger is on HQ -> total should be 0 for them.
    assert resp.context["kpis"]["total"] == 0
