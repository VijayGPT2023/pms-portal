#!/usr/bin/env python
"""
API-based seed script for Django PMS Portal.
Creates sample data using Django ORM (not raw SQL).
Follows Rule 13: Seed Data via proper code paths.

Usage:
    python scripts/seed_django.py
"""
import os
import sys
import django
from datetime import date, timedelta
from pathlib import Path

# Setup Django
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pms_portal.settings")
django.setup()

from core.models import (
    Office, Officer, OfficerRole, Group, ReportingHierarchy,
    Assignment, Milestone, ExpenditureHead, ExpenditureItem,
    RevenueShare, InvoiceRequest, PaymentReceipt, OfficerRevenueLedger,
    ConfigOption, FinancialYearTarget, Client, AssignmentClient,
    TrainingProgramme, TrainerAllocation, TrainingChecklist,
    TrainingExpenseHead,
    NonRevenueSuggestion,
)


def create_offices():
    """Create all NPC offices."""
    offices_data = [
        ("HQ", "NPC Headquarters, New Delhi"),
        ("RDDEL", "RD Delhi"),
        ("RDCHN", "RD Chennai"),
        ("RDHYD", "RD Hyderabad"),
        ("RDBNR", "RD Bengaluru"),
        ("RDKOL", "RD Kolkata"),
        ("RDMUM", "RD Mumbai"),
        ("RDLKO", "RD Lucknow"),
        ("RDPAT", "RD Patna"),
        ("RDJPR", "RD Jaipur"),
        ("RDGHY", "RD Guwahati"),
        ("RDCHD", "RD Chandigarh"),
        ("RDBPL", "RD Bhopal"),
    ]
    for oid, name in offices_data:
        Office.objects.get_or_create(
            office_id=oid,
            defaults={"office_name": name, "officer_count": 5, "annual_revenue_target": 300.0},
        )
    print(f"  Offices: {Office.objects.count()}")


def create_groups():
    """Create organizational groups."""
    groups = [
        ("IE", "Industrial Engineering"),
        ("ES", "Economic Services"),
        ("HRM", "Human Resource Management"),
        ("IT", "Information Technology"),
        ("Agri", "Agri-Business"),
        ("TM", "Training & Management"),
        ("Finance", "Finance & Accounts"),
        ("Admin", "Administration"),
    ]
    for code, name in groups:
        Group.objects.get_or_create(group_code=code, defaults={"group_name": name})
    print(f"  Groups: {Group.objects.count()}")


def create_officers():
    """Create sample officers across offices with various roles."""
    hq = Office.objects.get(office_id="HQ")

    # Admin
    admin, _ = Officer.objects.get_or_create(
        officer_id="ADMIN",
        defaults={
            "email": "admin@npcindia.gov.in",
            "name": "System Administrator",
            "office": hq,
            "admin_role_id": "ADMIN",
            "is_staff": True,
            "is_superuser": True,
            "designation": "Director-I",
        },
    )
    if not admin.has_usable_password():
        admin.set_password("admin123")
        admin.save()

    # DG
    dg, _ = Officer.objects.get_or_create(
        officer_id="DG001",
        defaults={
            "email": "dg@npcindia.gov.in",
            "name": "Dr. Anil Kumar",
            "office": hq,
            "admin_role_id": "DG",
            "designation": "Director General",
        },
    )
    if not dg.has_usable_password():
        dg.set_password("dg123")
        dg.save()
    OfficerRole.objects.get_or_create(
        officer=dg, role_type="DG",
        defaults={"scope_type": "GLOBAL", "is_primary": True},
    )

    # RD Heads for each regional office
    for i, oid in enumerate(["RDDEL", "RDCHN", "RDHYD", "RDBNR"], start=1):
        office = Office.objects.get(office_id=oid)
        rd, _ = Officer.objects.get_or_create(
            officer_id=f"RD{i:03d}",
            defaults={
                "email": f"rd{i}@npcindia.gov.in",
                "name": f"RD Head {office.office_name}",
                "office": office,
                "admin_role_id": "RD_HEAD",
                "designation": "Director-I",
            },
        )
        if not rd.has_usable_password():
            rd.set_password("rd123")
            rd.save()
        OfficerRole.objects.get_or_create(
            officer=rd, role_type="RD_HEAD",
            defaults={"scope_type": "OFFICE", "scope_value": oid, "is_primary": True},
        )

    # Regular officers (2 per office)
    for j, oid in enumerate(["HQ", "RDDEL", "RDCHN", "RDHYD"], start=1):
        office = Office.objects.get(office_id=oid)
        for k in range(1, 3):
            idx = (j - 1) * 2 + k
            off, _ = Officer.objects.get_or_create(
                officer_id=f"OFF{idx:03d}",
                defaults={
                    "email": f"officer{idx}@npcindia.gov.in",
                    "name": f"Officer {idx} ({oid})",
                    "office": office,
                    "designation": "Assistant Director",
                    "annual_target": 30.0,
                },
            )
            if not off.has_usable_password():
                off.set_password("officer123")
                off.save()

    # Finance officer
    fin, _ = Officer.objects.get_or_create(
        officer_id="FIN001",
        defaults={
            "email": "finance@npcindia.gov.in",
            "name": "Finance Officer",
            "office": hq,
            "admin_role_id": "FINANCE",
            "designation": "Accounts Officer",
        },
    )
    if not fin.has_usable_password():
        fin.set_password("finance123")
        fin.save()

    print(f"  Officers: {Officer.objects.count()}")


def create_expenditure_heads():
    """Create consultancy (NPC-ASS-6) + training (AI-850/2025) expense heads.

    Kept in sync with data migration 0012_seed_expense_heads. Both sets carry a
    shared macro_category for the combined Revenue MIS rollup.
    """
    consultancy = [
        ("A", "A1", "NPC Consultant Fee", "FEE"),
        ("A", "A2", "Guest Consultant Fee", "FEE"),
        ("A", "A3", "Faculty Fee", "FEE"),
        ("A", "A4", "Project Associate", "FEE"),
        ("B", "B1", "NPC Consultant Travel", "TRAVEL"),
        ("B", "B2", "Supporting Staff Travel", "TRAVEL"),
        ("B", "B3", "Guest Consultant Travel", "TRAVEL"),
        ("B", "B4", "Local Conveyance (NPC & Outside Consultants)", "TRAVEL"),
        ("C", "C1", "Outstation Stay (NPC Consultants)", "LODGING"),
        ("C", "C2", "Local Consultant Expenses", "LODGING"),
        ("C", "C3", "Guest Faculty Lodging & Boarding", "LODGING"),
        ("D", "D1", "Publication Titles", "MATERIAL"),
        ("D", "D2", "Printing & Binding / Report Writing", "MATERIAL"),
        ("D", "D3", "Periodicals", "MATERIAL"),
        ("E", "E1", "Hiring of Hall", "ADMIN"),
        ("E", "E2", "Refreshment", "ADMIN"),
        ("E", "E3", "Stationery", "MATERIAL"),
        ("E", "E4", "Working Lunch", "ADMIN"),
        ("E", "E5", "Advertisement", "ADMIN"),
        ("E", "E6", "Brochure", "MATERIAL"),
        ("E", "E7", "Cyclostyled Material", "MATERIAL"),
        ("E", "E8", "Research Material / Database / Software / IT / Internet", "MATERIAL"),
        ("E", "E9", "Residential Expenses of Participants", "LODGING"),
        ("E", "E10", "Factory / Other Visits", "TRAVEL"),
        ("E", "E11", "Documentation Fees", "ADMIN"),
        ("E", "E12", "Implementation Charges", "ADMIN"),
        ("E", "E13", "Miscellaneous", "MISC"),
        ("F", "F1", "Unforeseen Expenses (5%)", "MISC"),
    ]
    for cat, code, name, macro in consultancy:
        ExpenditureHead.objects.get_or_create(
            head_code=code,
            defaults={"category": cat, "head_name": name, "macro_category": macro},
        )

    training = [
        (1, "T01", "Room Rent for Participants (APAI plan)", "LODGING"),
        (2, "T02", "Room Rent for NPC Officer (APAI plan)", "LODGING"),
        (3, "T03", "Room Rent for Faculty (APAI plan)", "LODGING"),
        (4, "T04", "Projector / Screen / Collar Mike etc.", "ADMIN"),
        (5, "T05", "Field Visit Charges", "TRAVEL"),
        (6, "T06", "Gala / Networking Dinner", "ADMIN"),
        (7, "T07", "Group Photography (no printing)", "ADMIN"),
        (8, "T08", "Honorarium to Faculty (per AI-830)", "FEE"),
        (9, "T09", "Faculty Travel — Air / Rail Tickets", "TRAVEL"),
        (10, "T10", "Faculty Travel — Local Conveyance (home location)", "TRAVEL"),
        (11, "T11", "Faculty Pick & Drop (programme location)", "TRAVEL"),
        (12, "T12", "NPC Officer Tour (Air/Rail + LC at home location)", "TRAVEL"),
        (13, "T13", "NPC Officer Pick & Drop (programme location)", "TRAVEL"),
        (14, "T14", "Training Kit (Bag, Pen, Pad, Pen drive, Certificate)", "MATERIAL"),
        (15, "T15", "Courier Charges", "MATERIAL"),
        (16, "T16", "Site Seeing Tickets (River Cruise, Light & Sound etc.)", "ADMIN"),
        (17, "T17", "Other Miscellaneous Expenses", "MISC"),
    ]
    for seq, code, name, macro in training:
        TrainingExpenseHead.objects.get_or_create(
            head_code=code,
            defaults={"seq": seq, "head_name": name, "macro_category": macro},
        )
    print(f"  Expenditure Heads: {ExpenditureHead.objects.count()} consultancy, "
          f"{TrainingExpenseHead.objects.count()} training")


def create_config_options():
    """Create dropdown config options."""
    options = [
        ("domain", "ES", "Economic Services"),
        ("domain", "IE", "Industrial Engineering"),
        ("domain", "HRM", "Human Resource Management"),
        ("domain", "IT", "Information Technology"),
        ("domain", "Agri", "Agri-Business"),
        ("domain", "TM", "Training & Management"),
        ("domain", "General", "General"),
        ("client_type", "CG", "Central Government"),
        ("client_type", "SG", "State Government"),
        ("client_type", "PSU", "PSU"),
        ("client_type", "PVT", "Private"),
        ("client_type", "INT", "International"),
    ]
    for cat, val, label in options:
        ConfigOption.objects.get_or_create(
            category=cat, option_value=val, defaults={"option_label": label}
        )
    print(f"  Config Options: {ConfigOption.objects.count()}")


def create_sample_assignments():
    """Create realistic sample assignments with milestones and revenue."""
    today = date.today()
    offices = list(Office.objects.all()[:4])
    officers = list(Officer.objects.filter(admin_role_id="")[:4])

    assignments_data = [
        ("Productivity Study for Steel Industry", "ASSIGNMENT", "ES", "Central Government", 50.0),
        ("IT Transformation for NIC", "ASSIGNMENT", "IT", "Central Government", 80.0),
        ("HRM Audit for SAIL", "ASSIGNMENT", "HRM", "PSU", 35.0),
        ("Training Programme - Lean Manufacturing", "TRAINING", "IE", "State Government", 20.0),
        ("Agri Supply Chain Analysis", "ASSIGNMENT", "Agri", "State Government", 45.0),
        ("Energy Audit for BHEL", "ASSIGNMENT", "IE", "PSU", 60.0),
    ]

    for i, (title, atype, domain, ctype, value) in enumerate(assignments_data):
        office = offices[i % len(offices)]
        officer = officers[i % len(officers)] if officers else None
        fy = "2025-26"

        a, created = Assignment.objects.get_or_create(
            assignment_no=f"NPC/{office.office_id}/ASG/SEED/{i+1:04d}/{fy}",
            defaults={
                "type": atype,
                "title": title,
                "domain": domain,
                "client_type": ctype,
                "office": office,
                "total_value": value,
                "gross_value": value,
                "start_date": today - timedelta(days=90),
                "target_date": today + timedelta(days=180),
                "status": "Ongoing",
                "workflow_stage": "ACTIVE",
                "registration_status": "APPROVED",
                "approval_status": "APPROVED",
                "cost_approval_status": "APPROVED",
                "team_approval_status": "APPROVED",
                "milestone_approval_status": "APPROVED",
                "revenue_approval_status": "APPROVED",
                "fy_period": fy,
                "team_leader": officer,
                "registered_by": officer,
            },
        )

        if created:
            # Create 3 milestones
            for m in range(1, 4):
                Milestone.objects.create(
                    assignment=a,
                    milestone_no=m,
                    title=f"Milestone {m}",
                    target_date=today + timedelta(days=60 * m),
                    invoice_percent=33.33,
                    invoice_amount=round(value * 0.3333, 2),
                    status="Pending" if m > 1 else "In Progress",
                )

            # Revenue shares
            if officer:
                RevenueShare.objects.create(
                    assignment=a, officer=officer,
                    share_percent=100, share_amount=value,
                )

    print(f"  Assignments: {Assignment.objects.count()}")
    print(f"  Milestones: {Milestone.objects.count()}")


def create_sample_clients():
    """Create sample clients."""
    clients_data = [
        ("MOC001", "Ministry of Commerce", "Central Government", "New Delhi"),
        ("SAIL01", "Steel Authority of India", "PSU", "New Delhi"),
        ("BHEL01", "Bharat Heavy Electricals", "PSU", "New Delhi"),
        ("GOMP01", "Govt. of Madhya Pradesh", "State Government", "Bhopal"),
        ("GOKL01", "Govt. of Kerala", "State Government", "Thiruvananthapuram"),
    ]
    admin = Officer.objects.filter(officer_id="ADMIN").first()
    for code, name, ctype, city in clients_data:
        Client.objects.get_or_create(
            client_code=code,
            defaults={
                "client_name": name,
                "client_type": ctype,
                "city": city,
                "created_by": admin,
            },
        )
    print(f"  Clients: {Client.objects.count()}")


def create_financial_year_targets():
    """Create FY targets for offices."""
    for office in Office.objects.all():
        FinancialYearTarget.objects.get_or_create(
            financial_year="2025-26",
            office=office,
            defaults={
                "annual_target": office.annual_revenue_target or 300.0,
                "q1_target": 75.0,
                "q2_target": 75.0,
                "q3_target": 75.0,
                "q4_target": 75.0,
            },
        )
    print(f"  FY Targets: {FinancialYearTarget.objects.count()}")


def main():
    print("=" * 60)
    print("PMS Portal — Django Seed Data")
    print("=" * 60)

    print("\n1. Creating offices...")
    create_offices()

    print("2. Creating groups...")
    create_groups()

    print("3. Creating officers...")
    create_officers()

    print("4. Creating expenditure heads...")
    create_expenditure_heads()

    print("5. Creating config options...")
    create_config_options()

    print("6. Creating sample assignments...")
    create_sample_assignments()

    print("7. Creating sample clients...")
    create_sample_clients()

    print("8. Creating FY targets...")
    create_financial_year_targets()

    print("\n" + "=" * 60)
    print("Seed data created successfully!")
    print(f"  Total Officers: {Officer.objects.count()}")
    print(f"  Total Assignments: {Assignment.objects.count()}")
    print(f"  Total Milestones: {Milestone.objects.count()}")
    print(f"  Total Clients: {Client.objects.count()}")
    print("=" * 60)
    print("\nLogin credentials:")
    print("  Admin:   admin@npcindia.gov.in / admin123")
    print("  DG:      dg@npcindia.gov.in / dg123")
    print("  RD Head: rd1@npcindia.gov.in / rd123")
    print("  Officer: officer1@npcindia.gov.in / officer123")
    print("  Finance: finance@npcindia.gov.in / finance123")


if __name__ == "__main__":
    main()
