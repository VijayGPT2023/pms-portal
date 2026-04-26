"""
Root conftest for Django tests.
Shared fixtures: test users, offices, assignments, clients.
"""
import pytest
from django.test import Client as TestClient

from core.models import (
    Assignment, Client, ExpenditureHead, Milestone, Office, Officer,
    OfficerRole, RevenueShare, TrainingProgramme,
)


@pytest.fixture(autouse=True)
def _disable_axes_in_tests(settings):
    """
    django-axes refuses to authenticate without a request object, which the
    Django test client's .login() does not provide. Tests opt OUT of axes by
    default; the dedicated lockout tests re-enable it explicitly.
    """
    settings.AXES_ENABLED = False


@pytest.fixture
def office(db):
    """Create the HQ office."""
    return Office.objects.create(
        office_id="HQ",
        office_name="NPC Headquarters",
        officer_count=10,
        annual_revenue_target=600.0,
    )


@pytest.fixture
def regional_office(db):
    """Create a regional office."""
    return Office.objects.create(
        office_id="RDDEL",
        office_name="RD Delhi",
        officer_count=5,
        annual_revenue_target=300.0,
    )


@pytest.fixture
def admin_user(db, office):
    """Create admin user."""
    user = Officer.objects.create_user(
        email="admin@test.gov.in",
        officer_id="ADMIN",
        name="Test Admin",
        office=office,
        password="testpass123",
        is_staff=True,
        is_superuser=True,
        admin_role_id="ADMIN",
    )
    return user


@pytest.fixture
def rd_head_user(db, regional_office):
    """Create RD Head user."""
    user = Officer.objects.create_user(
        email="rdhead@test.gov.in",
        officer_id="RDHEAD01",
        name="RD Head Test",
        office=regional_office,
        password="testpass123",
        admin_role_id="RD_HEAD",
    )
    OfficerRole.objects.create(
        officer=user,
        role_type="RD_HEAD",
        scope_type="OFFICE",
        scope_value="RDDEL",
        is_primary=True,
    )
    return user


@pytest.fixture
def team_leader_user(db, office):
    """Create Team Leader user."""
    user = Officer.objects.create_user(
        email="tl@test.gov.in",
        officer_id="TL001",
        name="Team Leader Test",
        office=office,
        password="testpass123",
        admin_role_id="TEAM_LEADER",
    )
    return user


@pytest.fixture
def officer_user(db, office):
    """Create regular officer."""
    return Officer.objects.create_user(
        email="officer@test.gov.in",
        officer_id="OFF001",
        name="Regular Officer",
        office=office,
        password="testpass123",
        admin_role_id="",
        designation="Assistant Director",
    )


@pytest.fixture
def finance_user(db, office):
    """Create finance officer."""
    return Officer.objects.create_user(
        email="finance@test.gov.in",
        officer_id="FIN001",
        name="Finance Officer",
        office=office,
        password="testpass123",
        admin_role_id="FINANCE",
    )


@pytest.fixture
def auth_client(admin_user):
    """Return a TestClient logged in as admin."""
    client = TestClient()
    client.login(email="admin@test.gov.in", password="testpass123")
    return client


@pytest.fixture
def officer_client(officer_user):
    """Return a TestClient logged in as regular officer."""
    client = TestClient()
    client.login(email="officer@test.gov.in", password="testpass123")
    return client


@pytest.fixture
def tl_client(team_leader_user):
    """Return a TestClient logged in as TL."""
    client = TestClient()
    client.login(email="tl@test.gov.in", password="testpass123")
    return client


@pytest.fixture
def head_client(rd_head_user):
    """Return a TestClient logged in as RD Head."""
    client = TestClient()
    client.login(email="rdhead@test.gov.in", password="testpass123")
    return client


@pytest.fixture
def sample_assignment(db, office, team_leader_user):
    """Create a sample assignment in ACTIVE stage."""
    return Assignment.objects.create(
        assignment_no="NPC/HQ/ASG/TEST/0001/2025-26",
        type="ASSIGNMENT",
        title="Test Productivity Study",
        client="Ministry of Commerce",
        client_type="Central Government",
        domain="ES",
        office=office,
        status="Ongoing",
        total_value=50.0,
        gross_value=50.0,
        workflow_stage="ACTIVE",
        registration_status="APPROVED",
        approval_status="APPROVED",
        cost_approval_status="APPROVED",
        team_approval_status="APPROVED",
        milestone_approval_status="APPROVED",
        revenue_approval_status="APPROVED",
        team_leader=team_leader_user,
    )


@pytest.fixture
def draft_assignment(db, office, officer_user):
    """Create a draft assignment in REGISTRATION stage."""
    return Assignment.objects.create(
        assignment_no="NPC/HQ/ASG/TEST/0002/2025-26",
        type="ASSIGNMENT",
        title="Draft Assignment",
        office=office,
        status="Not Started",
        workflow_stage="REGISTRATION",
        registration_status="DRAFT",
        registered_by=officer_user,
    )


@pytest.fixture
def sample_milestones(db, sample_assignment):
    """Create 3 milestones for the sample assignment."""
    milestones = []
    for i in range(1, 4):
        m = Milestone.objects.create(
            assignment=sample_assignment,
            milestone_no=i,
            title=f"Milestone {i}",
            invoice_percent=33.33,
            invoice_amount=sample_assignment.total_value * 0.3333,
            status="Pending",
        )
        milestones.append(m)
    return milestones


@pytest.fixture
def sample_client(db, officer_user):
    """Create a sample client."""
    return Client.objects.create(
        client_code="CLI001",
        client_name="Test Ministry",
        client_type="Central Government",
        city="New Delhi",
        state="Delhi",
        contact_person="Test Contact",
        contact_email="contact@test.gov.in",
        created_by=officer_user,
    )


@pytest.fixture
def expenditure_heads(db):
    """Create default expenditure heads."""
    heads = []
    for cat, code, name in [
        ("A", "A1", "NPC Consultant Fee"),
        ("A", "A2", "Guest Consultant Fee"),
        ("B", "B1", "NPC Consultant Travel"),
        ("C", "C1", "Outstation Stay"),
        ("E", "E1", "Hall Hiring"),
    ]:
        h = ExpenditureHead.objects.create(
            category=cat, head_code=code, head_name=name
        )
        heads.append(h)
    return heads
