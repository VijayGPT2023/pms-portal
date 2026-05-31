"""
Data migration: align expense heads with source documents.

1. Backfill macro_category on existing consultancy ExpenditureHead rows.
2. Add the consultancy heads missing vs NPC-ASS-6 (Form NPC-ASS-6, Rule 2.2.3 MAAP).
3. Seed the 17 training expense heads from Administrative Instruction 850/2025
   (Annexure I/II), each tagged with a shared macro_category.

Idempotent: uses get_or_create / update, safe to run on populated production DB.
"""
from django.db import migrations


# Consultancy heads: (sheet_section, head_code, head_name, macro_category)
# Covers NPC-ASS-6 sections A-F. Codes A1..A3,B1,B2,C1,C2,D1,D2,E1,E2,E3,F1
# already exist from the original seed; the rest are added here.
CONSULTANCY_HEADS = [
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
    ("E", "E8", "Research Material / Database / Software / IT Infrastructure / Internet", "MATERIAL"),
    ("E", "E9", "Residential Expenses of Participants", "LODGING"),
    ("E", "E10", "Factory / Other Visits", "TRAVEL"),
    ("E", "E11", "Documentation Fees", "ADMIN"),
    ("E", "E12", "Implementation Charges", "ADMIN"),
    ("E", "E13", "Miscellaneous", "MISC"),
    ("F", "F1", "Unforeseen Expenses (5%)", "MISC"),
]

# Training heads: (seq, head_code, head_name, macro_category) — AI-850/2025 i-xvii
TRAINING_HEADS = [
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

def seed(apps, schema_editor):
    ExpenditureHead = apps.get_model("core", "ExpenditureHead")
    TrainingExpenseHead = apps.get_model("core", "TrainingExpenseHead")

    for section, code, name, macro in CONSULTANCY_HEADS:
        obj, created = ExpenditureHead.objects.get_or_create(
            head_code=code,
            defaults={"category": section, "head_name": name,
                      "macro_category": macro, "is_active": True},
        )
        if not created:
            # update macro_category (and ensure section/name sane) without
            # clobbering any admin edits to is_active
            obj.macro_category = macro
            if not obj.category:
                obj.category = section
            obj.save(update_fields=["macro_category", "category"])

    for seq, code, name, macro in TRAINING_HEADS:
        TrainingExpenseHead.objects.get_or_create(
            head_code=code,
            defaults={"seq": seq, "head_name": name,
                      "macro_category": macro, "is_active": True},
        )


def unseed(apps, schema_editor):
    # Non-destructive reverse: only drop the training heads we added; leave
    # consultancy heads (they pre-existed / are referenced by items).
    TrainingExpenseHead = apps.get_model("core", "TrainingExpenseHead")
    codes = [code for _seq, code, _name, _macro in TRAINING_HEADS]
    TrainingExpenseHead.objects.filter(head_code__in=codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_trainingexpensehead_expenditurehead_macro_category_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
