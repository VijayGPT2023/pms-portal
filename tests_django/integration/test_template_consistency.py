"""
Holistic consistency guard against organic drift between models / views /
templates.

Renders the major GET pages with a sentinel `string_if_invalid` so any
undefined template variable (typo'd field, renamed model attr, wrong context
shape) SURFACES instead of silently rendering blank — which is Django's
default and the reason plain HTTP-200 tests miss this class of bug.

- LIST_PAGES: list / detail / dashboard pages rendered with real objects.
  STRICT: zero invalid variables allowed.
- FORM_PAGES: blank create/edit forms where the bound object is None, so
  `{{ object.field }}` legitimately resolves empty. Only checked for HTTP 200.

This test caught (and now guards against the return of):
- InvoiceRequest.get_status_display on an FSMField with no choices.
- assignments_list 'offices' being a flat string list iterated as objects.
"""
import re

import pytest
from django.test import Client as TestClient

pytestmark = pytest.mark.django_db

SENTINEL = "XXINVALIDVARXX"

LIST_PAGES = [
    "/dashboard/", "/dashboard/summary/",
    "/training/",
    "/finance/", "/finance/officer-dashboard/",
    "/clients/", "/clients/mis/",
    "/admin-panel/users/", "/admin-panel/roles/",
    "/utilization/", "/utilization/pending-approval/",
    "/utilization/pending-rectification/", "/utilization/summary/",
    "/proposals/",
    "/mis/assignments/",
    "/reports/delays/",
    "/profile/",
    "/data/export/", "/data/import/", "/data/admin/config/",
    "/mis/pre-wo/", "/mis/revenue/", "/mis/non-revenue/",
    "/pre-wo/", "/non-revenue/",
    "/approvals/", "/edit-requests/",
]

FORM_PAGES = [
    "/training/create/", "/clients/new/", "/utilization/new/",
    "/pre-wo/create/", "/non-revenue/create/", "/profile/change-password/",
]


def _client(admin_user):
    c = TestClient()
    c.login(email="admin@test.gov.in", password="testpass123")
    return c


def test_list_pages_have_no_invalid_vars(admin_user, settings, sample_assignment,
                                         sample_client, expenditure_heads):
    settings.TEMPLATES[0].setdefault("OPTIONS", {})["string_if_invalid"] = SENTINEL + "(%s)"
    from django.template import engines
    engines._engines = {}
    client = _client(admin_user)

    offenders = []
    for url in LIST_PAGES:
        resp = client.get(url)
        if resp.status_code != 200:
            offenders.append(f"{url} -> HTTP {resp.status_code}")
            continue
        body = resp.content.decode("utf-8", "replace")
        if SENTINEL in body:
            bad = sorted({b for b in re.findall(rf"{SENTINEL}\(([^)]*)\)", body) if b.strip()})
            if bad:
                offenders.append(f"{url} -> invalid vars: {bad}")

    assert not offenders, "Template variable / context issues:\n" + "\n".join(offenders)


def test_form_pages_render(admin_user, sample_assignment):
    client = _client(admin_user)
    failures = [u for u in FORM_PAGES if client.get(u).status_code != 200]
    assert not failures, f"Form pages not rendering: {failures}"


def test_assignment_view_all_tabs_render(admin_user, sample_assignment,
                                         sample_milestones, expenditure_heads):
    """Every assignment-view tab must render. Guards against stale {% url %}
    names like the core:revenue_edit -> revenue_share_page drift that 500'd
    the team tab."""
    client = _client(admin_user)
    failures = []
    for tab in ("basic", "milestones", "cost", "team"):
        resp = client.get(f"/assignment/view/{sample_assignment.pk}/?tab={tab}")
        if resp.status_code != 200:
            failures.append(f"tab={tab} -> HTTP {resp.status_code}")
    assert not failures, f"Assignment-view tabs failing: {failures}"
