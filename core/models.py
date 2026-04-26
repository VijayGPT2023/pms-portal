"""
Django ORM models for PMS Portal.
Maps all 35+ tables from the existing database.py schema.
Uses django-fsm for workflow state machine and django-auditlog for audit trail.
"""
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django_fsm import FSMField, transition
from auditlog.registry import auditlog


# =============================================================================
# Custom User Manager
# =============================================================================

class OfficerManager(BaseUserManager):
    """Manager for custom Officer user model."""

    def create_user(self, email, officer_id, name, office, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        if not officer_id:
            raise ValueError("Officer ID is required")
        email = self.normalize_email(email)
        user = self.model(
            email=email,
            officer_id=officer_id,
            name=name,
            office=office,
            **extra,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, officer_id, name, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("admin_role_id", "ADMIN")
        # Superuser needs an office — use or create HQ
        office, _ = Office.objects.get_or_create(
            office_id="HQ",
            defaults={"office_name": "NPC Headquarters"},
        )
        return self.create_user(email, officer_id, name, office, password, **extra)


# =============================================================================
# Core Models
# =============================================================================

class Office(models.Model):
    """Regional offices with revenue targets."""
    office_id = models.CharField(max_length=50, unique=True)
    office_name = models.CharField(max_length=200)
    officer_count = models.IntegerField(default=0)
    annual_target_per_officer = models.FloatField(default=60.0)
    annual_revenue_target = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "offices"
        ordering = ["office_name"]

    def __str__(self):
        return f"{self.office_id} - {self.office_name}"


class Officer(AbstractBaseUser, PermissionsMixin):
    """Custom user model — maps to officers table."""
    officer_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    designation = models.CharField(max_length=200, blank=True, default="")
    discipline = models.CharField(max_length=200, blank=True, default="")
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name="officers",
        to_field="office_id", db_column="office_id",
    )
    admin_role_id = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    annual_target = models.FloatField(default=60.0)
    created_at = models.DateTimeField(auto_now_add=True)

    # Django auth fields
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["officer_id", "name"]

    objects = OfficerManager()

    class Meta:
        db_table = "officers"
        ordering = ["name"]

    def __str__(self):
        return f"{self.officer_id} - {self.name}"

    @property
    def office_id_value(self):
        """Return the office_id string for backward compat."""
        return self.office.office_id if self.office else ""


class Group(models.Model):
    """Organizational groups (IE, AB, ES, IT, etc.)."""
    group_code = models.CharField(max_length=50, unique=True)
    group_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "org_groups"  # Avoid conflict with Django's auth_group
        ordering = ["group_code"]

    def __str__(self):
        return f"{self.group_code} - {self.group_name}"


# =============================================================================
# Officer Roles & Hierarchy
# =============================================================================

class OfficerRole(models.Model):
    """Multi-role support — one officer can have multiple roles with scopes."""

    class RoleType(models.TextChoices):
        ADMIN = "ADMIN", "System Administrator"
        DG = "DG", "Director General"
        DDG_I = "DDG-I", "Deputy Director General - I"
        DDG_II = "DDG-II", "Deputy Director General - II"
        RD_HEAD = "RD_HEAD", "Regional Director / Head"
        GROUP_HEAD = "GROUP_HEAD", "Group Head"
        TEAM_LEADER = "TEAM_LEADER", "Team Leader"
        FINANCE = "FINANCE", "Finance Officer"
        OFFICER = "OFFICER", "Officer"

    class ScopeType(models.TextChoices):
        GLOBAL = "GLOBAL", "Global"
        OFFICE = "OFFICE", "Office"
        GROUP = "GROUP", "Group"
        ASSIGNMENT = "ASSIGNMENT", "Assignment"
        INDIVIDUAL = "INDIVIDUAL", "Individual"

    officer = models.ForeignKey(
        Officer, on_delete=models.CASCADE, related_name="roles",
        to_field="officer_id", db_column="officer_id",
    )
    role_type = models.CharField(max_length=50, choices=RoleType.choices)
    scope_type = models.CharField(
        max_length=50, choices=ScopeType.choices, blank=True, default=""
    )
    scope_value = models.CharField(max_length=200, blank=True, default="")
    is_primary = models.BooleanField(default=False)
    effective_from = models.DateField(auto_now_add=True)
    effective_to = models.DateField(null=True, blank=True)
    order_reference = models.CharField(max_length=200, blank=True, default="")
    assigned_by = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "officer_roles"

    def __str__(self):
        scope = f" ({self.scope_value})" if self.scope_value else ""
        return f"{self.officer.officer_id} - {self.role_type}{scope}"


class ReportingHierarchy(models.Model):
    """Which office/group reports to which DDG."""

    class EntityType(models.TextChoices):
        OFFICE = "OFFICE", "Office"
        GROUP = "GROUP", "Group"

    entity_type = models.CharField(max_length=50, choices=EntityType.choices)
    entity_value = models.CharField(max_length=200)
    reports_to_role = models.CharField(max_length=50)
    effective_from = models.DateField(auto_now_add=True)
    effective_to = models.DateField(null=True, blank=True)
    updated_by = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reporting_hierarchy"
        unique_together = [("entity_type", "entity_value")]

    def __str__(self):
        return f"{self.entity_type}:{self.entity_value} -> {self.reports_to_role}"


# =============================================================================
# Officer History (Promotions, Transfers, Role Changes)
# =============================================================================

class OfficerHistory(models.Model):
    """Generic change tracking for officers."""

    class ChangeType(models.TextChoices):
        DESIGNATION = "DESIGNATION", "Designation Change"
        OFFICE_TRANSFER = "OFFICE_TRANSFER", "Office Transfer"
        ROLE_ASSIGN = "ROLE_ASSIGN", "Role Assigned"
        ROLE_REMOVE = "ROLE_REMOVE", "Role Removed"

    officer = models.ForeignKey(
        Officer, on_delete=models.CASCADE, related_name="history",
        to_field="officer_id", db_column="officer_id",
    )
    change_type = models.CharField(max_length=50, choices=ChangeType.choices)
    field_name = models.CharField(max_length=100, blank=True, default="")
    old_value = models.TextField(blank=True, default="")
    new_value = models.TextField(blank=True, default="")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    order_reference = models.CharField(max_length=200, blank=True, default="")
    remarks = models.TextField(blank=True, default="")
    changed_by = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "officer_history"
        indexes = [
            models.Index(fields=["officer"], name="idx_oh_officer"),
            models.Index(fields=["change_type"], name="idx_oh_type"),
        ]

    def __str__(self):
        return f"{self.officer.officer_id} - {self.change_type}"


class DesignationHistory(models.Model):
    """Promotion and designation history."""
    officer = models.ForeignKey(
        Officer, on_delete=models.CASCADE, related_name="designation_history",
        to_field="officer_id", db_column="officer_id",
    )
    designation = models.CharField(max_length=200)
    pay_level = models.CharField(max_length=50, blank=True, default="")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    promotion_order_no = models.CharField(max_length=200, blank=True, default="")
    promotion_order_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True, default="")
    updated_by = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "designation_history"
        indexes = [
            models.Index(fields=["officer"], name="idx_dh_officer"),
        ]


class OfficeTransferHistory(models.Model):
    """Office transfer records."""

    class TransferType(models.TextChoices):
        INITIAL = "INITIAL", "Initial Posting"
        TRANSFER = "TRANSFER", "Transfer"
        DEPUTATION = "DEPUTATION", "Deputation"
        REPATRIATION = "REPATRIATION", "Repatriation"

    officer = models.ForeignKey(
        Officer, on_delete=models.CASCADE, related_name="transfers",
        to_field="officer_id", db_column="officer_id",
    )
    from_office = models.ForeignKey(
        Office, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transfers_out", to_field="office_id", db_column="from_office_id",
    )
    to_office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name="transfers_in",
        to_field="office_id", db_column="to_office_id",
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    transfer_order_no = models.CharField(max_length=200, blank=True, default="")
    transfer_order_date = models.DateField(null=True, blank=True)
    transfer_type = models.CharField(
        max_length=50, choices=TransferType.choices, default=TransferType.TRANSFER
    )
    remarks = models.TextField(blank=True, default="")
    updated_by = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "office_transfer_history"
        indexes = [
            models.Index(fields=["officer"], name="idx_oth_officer"),
        ]


# =============================================================================
# Assignment — Main Business Entity with django-fsm State Machine
# =============================================================================

class Assignment(models.Model):
    """
    Core assignment model with django-fsm state machine.
    Supports 3 types: ASSIGNMENT, TRAINING, DEVELOPMENT.
    5-stage workflow + 5 independent section approvals.
    """

    class Type(models.TextChoices):
        ASSIGNMENT = "ASSIGNMENT", "Assignment"
        TRAINING = "TRAINING", "Training"
        DEVELOPMENT = "DEVELOPMENT", "Development Work"

    class Status(models.TextChoices):
        NOT_STARTED = "Not Started", "Not Started"
        ONGOING = "Ongoing", "Ongoing"
        COMPLETED = "Completed", "Completed"
        ON_HOLD = "On Hold", "On Hold"
        CANCELLED = "Cancelled", "Cancelled"

    # --- Workflow stages (django-fsm) ---
    # Labels renamed per SCOPE_V2 §3.2 — enum values unchanged (cosmetic only).
    class WorkflowStage(models.TextChoices):
        REGISTRATION = "REGISTRATION", "WO Registration"
        TL_ASSIGNMENT = "TL_ASSIGNMENT", "TL Assignment"
        DETAIL_ENTRY = "DETAIL_ENTRY", "Progressive Fill"
        ACTIVE = "ACTIVE", "Execution"
        COMPLETED = "COMPLETED", "Closure"

    class ApprovalStatus(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        PENDING = "PENDING", "Pending"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending Approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    # --- Identity ---
    assignment_no = models.CharField(max_length=100, unique=True)
    type = models.CharField(max_length=50, choices=Type.choices, blank=True, null=True)
    title = models.CharField(max_length=500)

    # --- Common fields ---
    client = models.CharField(max_length=500, blank=True, default="")
    client_type = models.CharField(max_length=100, blank=True, default="")
    city = models.CharField(max_length=200, blank=True, default="")
    domain = models.CharField(max_length=100, blank=True, default="")
    sub_domain = models.CharField(max_length=100, blank=True, default="")
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name="assignments",
        to_field="office_id", db_column="office_id",
    )
    status = models.CharField(
        max_length=50, choices=Status.choices, default=Status.NOT_STARTED
    )

    # --- Assignment-specific ---
    tor_scope = models.TextField(blank=True, default="")
    work_order_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    team_leader = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="led_assignments",
        to_field="officer_id", db_column="team_leader_officer_id",
    )

    # --- Training-specific ---
    venue = models.CharField(max_length=500, blank=True, default="")
    duration_start = models.DateField(null=True, blank=True)
    duration_end = models.DateField(null=True, blank=True)
    duration_days = models.IntegerField(default=0)
    type_of_participants = models.CharField(max_length=500, blank=True, default="")
    faculty1 = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="faculty1_assignments",
        to_field="officer_id", db_column="faculty1_officer_id",
    )
    faculty2 = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="faculty2_assignments",
        to_field="officer_id", db_column="faculty2_officer_id",
    )
    target_participants = models.IntegerField(default=0)
    tentative_participants = models.IntegerField(default=0)
    actual_participants = models.IntegerField(default=0)
    fee_per_participant = models.FloatField(default=0)

    # --- Development Work ---
    man_days = models.FloatField(default=0)
    daily_rate = models.FloatField(default=0.20)
    is_notional = models.BooleanField(default=False)
    dev_sub_type = models.CharField(max_length=100, blank=True, default="")
    proposal_value_lakhs = models.FloatField(default=0)
    num_committee_members = models.IntegerField(default=0)
    event_duration_days = models.FloatField(default=0)
    linked_proposal_id = models.IntegerField(null=True, blank=True)

    # --- Financial ---
    total_value = models.FloatField(default=0)
    gross_value = models.FloatField(default=0)
    invoice_amount = models.FloatField(default=0)
    amount_received = models.FloatField(default=0)
    total_revenue = models.FloatField(default=0)
    total_expenditure = models.FloatField(default=0)
    surplus_deficit = models.FloatField(default=0)

    # --- Progress ---
    physical_progress_percent = models.FloatField(default=0)
    timeline_progress_percent = models.FloatField(default=0)

    # --- Bulk Onboarding (SCOPE_V2 §3.6) ---
    # Set when an assignment is confirmed via the Head Hub during the
    # 3-month onboarding window. Signals that TL should fill retrospective
    # data (as-of date, physical %, historic invoices/payments) rather
    # than follow the fresh-registration path.
    is_bulk_onboarded = models.BooleanField(default=False)
    bulk_onboarding_as_of_date = models.DateField(null=True, blank=True)

    # --- Tracking ---
    details_filled = models.BooleanField(default=False)
    fy_period = models.CharField(max_length=20, blank=True, default="")
    version = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Workflow (django-fsm) ---
    registered_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registered_assignments",
        to_field="officer_id", db_column="registered_by",
    )
    registration_status = FSMField(
        default="DRAFT", max_length=50,
    )
    workflow_stage = FSMField(
        default="REGISTRATION", max_length=50,
    )

    # --- Section approval statuses (django-fsm) ---
    approval_status = FSMField(default="DRAFT", max_length=50)
    cost_approval_status = FSMField(default="DRAFT", max_length=50)
    cost_submitted_by = models.CharField(max_length=50, blank=True, default="")
    cost_submitted_at = models.DateTimeField(null=True, blank=True)
    cost_approved_by = models.CharField(max_length=50, blank=True, default="")
    cost_approved_at = models.DateTimeField(null=True, blank=True)

    team_approval_status = FSMField(default="DRAFT", max_length=50)
    team_submitted_by = models.CharField(max_length=50, blank=True, default="")
    team_submitted_at = models.DateTimeField(null=True, blank=True)
    team_approved_by = models.CharField(max_length=50, blank=True, default="")
    team_approved_at = models.DateTimeField(null=True, blank=True)

    milestone_approval_status = FSMField(default="DRAFT", max_length=50)
    milestone_submitted_by = models.CharField(max_length=50, blank=True, default="")
    milestone_submitted_at = models.DateTimeField(null=True, blank=True)
    milestone_approved_by = models.CharField(max_length=50, blank=True, default="")
    milestone_approved_at = models.DateTimeField(null=True, blank=True)

    revenue_approval_status = FSMField(default="DRAFT", max_length=50)
    revenue_submitted_by = models.CharField(max_length=50, blank=True, default="")
    revenue_submitted_at = models.DateTimeField(null=True, blank=True)
    revenue_approved_by = models.CharField(max_length=50, blank=True, default="")
    revenue_approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "assignments"
        indexes = [
            models.Index(fields=["office"], name="idx_asgn_office"),
            models.Index(fields=["type"], name="idx_asgn_type"),
            models.Index(fields=["status"], name="idx_asgn_status"),
            models.Index(fields=["physical_progress_percent"], name="idx_asgn_progress"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.assignment_no} - {self.title}"

    # ---- django-fsm workflow transitions ----

    # Registration workflow
    @transition(field=registration_status, source="DRAFT", target="PENDING_APPROVAL")
    def submit_registration(self):
        """Officer submits registration for approval."""
        pass

    @transition(field=registration_status, source="PENDING_APPROVAL", target="APPROVED")
    def approve_registration(self):
        """Head approves registration -> move to TL_ASSIGNMENT stage."""
        self.workflow_stage = "TL_ASSIGNMENT"

    @transition(field=registration_status, source="PENDING_APPROVAL", target="REJECTED")
    def reject_registration(self):
        """Head rejects registration."""
        pass

    # Workflow stage transitions
    @transition(field=workflow_stage, source="TL_ASSIGNMENT", target="DETAIL_ENTRY")
    def assign_team_leader(self):
        """Head assigns TL -> move to detail entry."""
        pass

    @transition(field=workflow_stage, source="DETAIL_ENTRY", target="ACTIVE")
    def activate(self):
        """All 5 sections approved -> auto-activate."""
        self.status = "Ongoing"

    @transition(field=workflow_stage, source="ACTIVE", target="COMPLETED")
    def complete(self):
        """Mark assignment as completed."""
        self.status = "Completed"

    # Section approval helpers
    def _submit_section(self, section_name, submitted_by):
        """Submit a section for approval."""
        setattr(self, f"{section_name}_approval_status", "SUBMITTED")
        setattr(self, f"{section_name}_submitted_by", submitted_by)
        from django.utils import timezone
        setattr(self, f"{section_name}_submitted_at", timezone.now())

    def _approve_section(self, section_name, approved_by):
        """Approve a section."""
        setattr(self, f"{section_name}_approval_status", "APPROVED")
        setattr(self, f"{section_name}_approved_by", approved_by)
        from django.utils import timezone
        setattr(self, f"{section_name}_approved_at", timezone.now())

    def _reject_section(self, section_name):
        """Reject a section back to DRAFT."""
        setattr(self, f"{section_name}_approval_status", "REJECTED")

    def all_sections_approved(self):
        """Check if all 5 sections are approved."""
        return all([
            self.approval_status == "APPROVED",
            self.cost_approval_status == "APPROVED",
            self.team_approval_status == "APPROVED",
            self.milestone_approval_status == "APPROVED",
            self.revenue_approval_status == "APPROVED",
        ])

    def try_auto_activate(self):
        """Auto-activate if all sections approved and in DETAIL_ENTRY stage."""
        if self.all_sections_approved() and self.workflow_stage == "DETAIL_ENTRY":
            self.activate()
            self.save()


# =============================================================================
# Milestone
# =============================================================================

class Milestone(models.Model):
    """Per-assignment milestones with invoice/payment tracking."""

    class Status(models.TextChoices):
        PENDING = "Pending", "Pending"
        IN_PROGRESS = "In Progress", "In Progress"
        COMPLETED = "Completed", "Completed"
        DELAYED = "Delayed", "Delayed"
        CANCELLED = "Cancelled", "Cancelled"

    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name="milestones"
    )
    milestone_no = models.IntegerField()
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, default="")
    target_date = models.DateField(null=True, blank=True)
    tentative_date = models.DateField(null=True, blank=True)
    actual_completion_date = models.DateField(null=True, blank=True)

    # Invoice tracking
    invoice_percent = models.FloatField(default=0)
    invoice_amount = models.FloatField(default=0)
    invoice_raised = models.BooleanField(default=False)
    invoice_raised_date = models.DateField(null=True, blank=True)

    # Payment tracking
    payment_received = models.BooleanField(default=False)
    payment_received_date = models.DateField(null=True, blank=True)

    revenue_percent = models.FloatField(default=0)
    status = models.CharField(
        max_length=50, choices=Status.choices, default=Status.PENDING
    )
    remarks = models.TextField(blank=True, default="")
    approval_status = models.CharField(max_length=50, default="PENDING")

    # Tentative date change tracking
    tentative_date_status = models.CharField(max_length=50, default="APPROVED")
    tentative_date_reason = models.TextField(blank=True, default="")
    tentative_date_requested_by = models.CharField(max_length=50, blank=True, default="")
    tentative_date_requested_at = models.DateTimeField(null=True, blank=True)
    tentative_date_approved_by = models.CharField(max_length=50, blank=True, default="")
    tentative_date_approved_at = models.DateTimeField(null=True, blank=True)

    version = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "milestones"
        unique_together = [("assignment", "milestone_no")]
        indexes = [
            models.Index(fields=["assignment"], name="idx_ms_assignment"),
        ]
        ordering = ["milestone_no"]

    def __str__(self):
        return f"M{self.milestone_no}: {self.title}"


# =============================================================================
# Expenditure
# =============================================================================

class ExpenditureHead(models.Model):
    """Master list of expenditure categories (CMR format: A-F)."""
    category = models.CharField(max_length=10)
    head_code = models.CharField(max_length=20, unique=True)
    head_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "expenditure_heads"
        ordering = ["head_code"]

    def __str__(self):
        return f"{self.head_code} - {self.head_name}"


class ExpenditureItem(models.Model):
    """Estimated vs actual expenditure per assignment per head."""
    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name="expenditure_items"
    )
    head = models.ForeignKey(ExpenditureHead, on_delete=models.PROTECT)
    estimated_amount = models.FloatField(default=0)
    actual_amount = models.FloatField(default=0)
    remarks = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "expenditure_items"
        unique_together = [("assignment", "head")]
        indexes = [
            models.Index(fields=["assignment"], name="idx_ei_assignment"),
        ]


class ExpenditureEntry(models.Model):
    """Date-wise actual expense vouchers."""
    expenditure_item = models.ForeignKey(
        ExpenditureItem, on_delete=models.CASCADE, null=True, blank=True,
        related_name="entries",
    )
    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name="expenditure_entries"
    )
    head = models.ForeignKey(ExpenditureHead, on_delete=models.PROTECT)
    entry_date = models.DateField()
    amount = models.FloatField()
    fy_period = models.CharField(max_length=20)
    description = models.TextField(blank=True, default="")
    voucher_reference = models.CharField(max_length=200, blank=True, default="")
    entered_by = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="expenditure_entries",
        to_field="officer_id", db_column="entered_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "expenditure_entries"


# =============================================================================
# Revenue
# =============================================================================

class RevenueShare(models.Model):
    """Officer-wise revenue allocation per assignment."""
    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name="revenue_shares"
    )
    officer = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="revenue_shares",
        to_field="officer_id", db_column="officer_id",
    )
    share_percent = models.FloatField(default=0)
    share_amount = models.FloatField(default=0)
    version = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "revenue_shares"
        unique_together = [("assignment", "officer")]
        indexes = [
            models.Index(fields=["assignment"], name="idx_rs_assignment"),
            models.Index(fields=["officer"], name="idx_rs_officer"),
        ]


# =============================================================================
# Invoice & Payment (80-20 Revenue Model)
# =============================================================================

class InvoiceRequest(models.Model):
    """Invoice lifecycle: PENDING -> APPROVED -> INVOICED."""

    class InvoiceType(models.TextChoices):
        ADVANCE = "ADVANCE", "Advance"
        SUBSEQUENT = "SUBSEQUENT", "Subsequent"
        FINAL = "FINAL", "Final"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        INVOICED = "INVOICED", "Invoiced"

    request_number = models.CharField(max_length=100, unique=True)
    assignment = models.ForeignKey(
        Assignment, on_delete=models.PROTECT, related_name="invoice_requests"
    )
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invoice_requests",
    )
    invoice_type = models.CharField(
        max_length=50, choices=InvoiceType.choices, default=InvoiceType.SUBSEQUENT
    )
    invoice_amount = models.FloatField()
    fy_period = models.CharField(max_length=20)
    description = models.TextField(blank=True, default="")
    status = FSMField(default="PENDING", max_length=50)

    # Requester
    requested_by = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="invoice_requests_made",
        to_field="officer_id", db_column="requested_by",
    )
    requested_at = models.DateTimeField(auto_now_add=True)

    # Verification
    verified_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invoices_verified",
        to_field="officer_id", db_column="verified_by",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_remarks = models.TextField(blank=True, default="")

    # Approval
    approved_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invoices_approved",
        to_field="officer_id", db_column="approved_by",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_remarks = models.TextField(blank=True, default="")

    # Tally integration
    tally_voucher_ref = models.CharField(max_length=200, blank=True, default="")
    tally_cost_centre = models.CharField(max_length=200, blank=True, default="")
    tally_invoice_date = models.DateField(null=True, blank=True)

    # 80% revenue recognition
    revenue_recognized_80 = models.FloatField(default=0)

    # Finance verification
    finance_verified_by = models.CharField(max_length=50, blank=True, default="")
    finance_verified_at = models.DateTimeField(null=True, blank=True)

    # Phase-2 additions
    client_id = models.IntegerField(null=True, blank=True)
    requested_by_officer_id = models.CharField(max_length=50, blank=True, default="")
    tl_revenue_hold = models.BooleanField(default=False)
    officer_request_status = models.CharField(max_length=50, default="DIRECT")
    finance_officer_id = models.CharField(max_length=50, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "invoice_requests"
        indexes = [
            models.Index(fields=["assignment"], name="idx_ir_assignment"),
            models.Index(fields=["status"], name="idx_ir_status"),
        ]

    def __str__(self):
        return f"{self.request_number} - {self.invoice_amount}"

    # django-fsm transitions
    @transition(field=status, source="PENDING", target="APPROVED")
    def approve(self):
        self.revenue_recognized_80 = self.invoice_amount * 0.80

    @transition(field=status, source="PENDING", target="REJECTED")
    def reject(self):
        pass

    @transition(field=status, source="APPROVED", target="INVOICED")
    def mark_invoiced(self):
        pass


class PaymentReceipt(models.Model):
    """Payment tracking with 20% revenue recognition."""

    class PaymentMode(models.TextChoices):
        NEFT = "NEFT", "NEFT"
        RTGS = "RTGS", "RTGS"
        CHEQUE = "CHEQUE", "Cheque"
        DD = "DD", "DD"
        CASH = "CASH", "Cash"
        UPI = "UPI", "UPI"

    receipt_number = models.CharField(max_length=100, unique=True)
    invoice_request = models.ForeignKey(
        InvoiceRequest, on_delete=models.PROTECT, related_name="payments"
    )
    amount_received = models.FloatField()
    receipt_date = models.DateField()
    payment_mode = models.CharField(
        max_length=50, choices=PaymentMode.choices, blank=True, default=""
    )
    reference_number = models.CharField(max_length=200, blank=True, default="")
    fy_period = models.CharField(max_length=20)
    remarks = models.TextField(blank=True, default="")
    revenue_recognized_20 = models.FloatField(default=0)
    updated_by = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="payment_receipts",
        to_field="officer_id", db_column="updated_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payment_receipts"
        indexes = [
            models.Index(fields=["invoice_request"], name="idx_pr_invoice"),
        ]

    def __str__(self):
        return f"{self.receipt_number} - {self.amount_received}"

    def save(self, **kwargs):
        # Auto-calculate 20% revenue recognition
        self.revenue_recognized_20 = self.amount_received * 0.20
        super().save(**kwargs)


class OfficerRevenueLedger(models.Model):
    """Individual revenue entries per officer (INVOICE_80 / PAYMENT_20)."""

    class RevenueType(models.TextChoices):
        INVOICE_80 = "INVOICE_80", "80% on Invoice"
        PAYMENT_20 = "PAYMENT_20", "20% on Payment"

    officer = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="revenue_ledger",
        to_field="officer_id", db_column="officer_id",
    )
    assignment = models.ForeignKey(
        Assignment, on_delete=models.PROTECT, related_name="revenue_ledger"
    )
    invoice_request = models.ForeignKey(
        InvoiceRequest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ledger_entries",
    )
    payment_receipt = models.ForeignKey(
        PaymentReceipt, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ledger_entries",
    )
    revenue_type = models.CharField(max_length=50, choices=RevenueType.choices)
    share_percent = models.FloatField()
    amount = models.FloatField()
    fy_period = models.CharField(max_length=20)
    transaction_date = models.DateField()
    remarks = models.TextField(blank=True, default="")
    is_held = models.BooleanField(default=False)
    released_by = models.CharField(max_length=50, blank=True, default="")
    released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "officer_revenue_ledger"
        indexes = [
            models.Index(fields=["officer"], name="idx_orl_officer"),
            models.Index(fields=["assignment"], name="idx_orl_assignment"),
        ]


class InvoiceMilestoneLink(models.Model):
    """M:N link between invoices and milestones."""
    invoice_request = models.ForeignKey(
        InvoiceRequest, on_delete=models.CASCADE, related_name="milestone_links"
    )
    milestone = models.ForeignKey(
        Milestone, on_delete=models.PROTECT, related_name="invoice_links"
    )
    milestone_share_amount = models.FloatField(default=0)
    revenue_share_percent = models.FloatField(default=0)
    milestone_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "invoice_milestone_links"
        unique_together = [("invoice_request", "milestone")]


# =============================================================================
# Assignment Team & Clients
# =============================================================================

class AssignmentTeam(models.Model):
    """Team members per assignment."""

    class Role(models.TextChoices):
        TEAM_LEADER = "TEAM_LEADER", "Team Leader"
        MEMBER = "MEMBER", "Member"
        CONSULTANT = "CONSULTANT", "Consultant"

    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name="team_members"
    )
    officer = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="team_memberships",
        to_field="officer_id", db_column="officer_id",
    )
    role = models.CharField(
        max_length=50, choices=Role.choices, default=Role.MEMBER
    )
    assigned_by = models.CharField(max_length=50, blank=True, default="")
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "assignment_team"
        unique_together = [("assignment", "officer")]


class Client(models.Model):
    """Client master database."""
    client_code = models.CharField(max_length=50, unique=True)
    client_name = models.CharField(max_length=500)
    client_type = models.CharField(max_length=100, blank=True, default="")
    address = models.TextField(blank=True, default="")
    city = models.CharField(max_length=200, blank=True, default="")
    state = models.CharField(max_length=200, blank=True, default="")
    contact_person = models.CharField(max_length=200, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=50, blank=True, default="")
    gstin = models.CharField(max_length=15, blank=True, default="")
    pan = models.CharField(max_length=10, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_clients",
        to_field="officer_id", db_column="created_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clients"
        indexes = [
            models.Index(fields=["client_code"], name="idx_cl_code"),
        ]
        ordering = ["client_name"]

    def __str__(self):
        return f"{self.client_code} - {self.client_name}"


class AssignmentClient(models.Model):
    """M:N linking assignments to clients with billing share."""
    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name="assignment_clients"
    )
    client = models.ForeignKey(
        Client, on_delete=models.PROTECT, related_name="assignment_links"
    )
    sub_activity_number = models.CharField(max_length=100, blank=True, default="")
    billing_share_percent = models.FloatField(default=100)
    description = models.TextField(blank=True, default="")
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assignment_clients"
        unique_together = [("assignment", "client")]
        indexes = [
            models.Index(fields=["assignment"], name="idx_ac_assignment"),
            models.Index(fields=["client"], name="idx_ac_client"),
        ]


# =============================================================================
# Approval Workflow
# =============================================================================

class ApprovalRequest(models.Model):
    """Generic approval queue supporting multiple request types."""

    class RequestType(models.TextChoices):
        ASSIGNMENT_APPROVAL = "ASSIGNMENT_APPROVAL", "Assignment Approval"
        MILESTONE_APPROVAL = "MILESTONE_APPROVAL", "Milestone Approval"
        REVENUE_SHARE_CHANGE = "REVENUE_SHARE_CHANGE", "Revenue Share Change"
        TEAM_LEADER_ALLOCATION = "TEAM_LEADER_ALLOCATION", "TL Allocation"
        ESCALATION = "ESCALATION", "Escalation"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        ESCALATED = "ESCALATED", "Escalated"

    request_type = models.CharField(max_length=100, choices=RequestType.choices)
    reference_type = models.CharField(max_length=100)
    reference_id = models.IntegerField()
    requested_by = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="approval_requests_made",
        to_field="officer_id", db_column="requested_by",
    )
    requested_to = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approval_requests_received",
        to_field="officer_id", db_column="requested_to",
    )
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name="approval_requests",
        to_field="office_id", db_column="office_id",
    )
    status = FSMField(default="PENDING", max_length=50)
    request_data = models.TextField(blank=True, default="")  # JSON
    remarks = models.TextField(blank=True, default="")
    approval_remarks = models.TextField(blank=True, default="")
    approved_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approvals_given",
        to_field="officer_id", db_column="approved_by",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    escalated_to = models.CharField(max_length=50, blank=True, default="")
    escalated_at = models.DateTimeField(null=True, blank=True)

    # Change request review columns
    reviewed_by = models.CharField(max_length=50, blank=True, default="")
    review_status = models.CharField(max_length=50, blank=True, default="")
    review_notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "approval_requests"
        ordering = ["-created_at"]


# =============================================================================
# Post-approval Edit Workflow (SCOPE_V2 §3.5)
# =============================================================================

class EditRequest(models.Model):
    """
    Post-approval edit workflow for Assignment sections.
    After a section's first GH approval, any change requires an EditRequest.
    Edits 1-3 per section route to GH/RD; edits 4+ route to DDG.
    """

    class Section(models.TextChoices):
        COST = "COST", "Cost Estimation"
        MILESTONE = "MILESTONE", "Milestones"
        TEAM = "TEAM", "Team"
        REVENUE = "REVENUE", "Revenue Allocation"

    GH_EDIT_LIMIT = 3

    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name="edit_requests"
    )
    section = models.CharField(max_length=20, choices=Section.choices)
    edit_number = models.IntegerField()
    proposed_by = models.ForeignKey(
        Officer, on_delete=models.PROTECT,
        related_name="edit_requests_proposed",
        to_field="officer_id", db_column="proposed_by_officer_id",
    )
    proposed_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()
    change_data = models.TextField(blank=True, default="")  # JSON: old vs new

    status = FSMField(default="PENDING", max_length=50)

    reviewed_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="edit_requests_reviewed",
        to_field="officer_id", db_column="reviewed_by_officer_id",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "edit_requests"
        indexes = [
            models.Index(fields=["assignment", "section"], name="idx_er_asgn_section"),
            models.Index(fields=["status"], name="idx_er_status"),
        ]
        ordering = ["-proposed_at"]

    def __str__(self):
        return f"EditRequest #{self.edit_number} ({self.section}) on {self.assignment.assignment_no}"

    @property
    def required_approver_role(self):
        return "GH" if self.edit_number <= self.GH_EDIT_LIMIT else "DDG"

    @classmethod
    def next_edit_number(cls, assignment, section):
        last = cls.objects.filter(
            assignment=assignment, section=section,
        ).order_by("-edit_number").first()
        return (last.edit_number + 1) if last else 1

    def save(self, *args, **kwargs):
        if not self.pk and not self.edit_number:
            self.edit_number = self.next_edit_number(self.assignment, self.section)
        super().save(*args, **kwargs)

    @transition(field=status, source="PENDING", target="APPROVED")
    def approve(self, reviewer, notes=""):
        """Approver accepts the edit. Caller applies change_data to the Assignment."""
        from django.utils import timezone
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.review_notes = notes

    @transition(field=status, source="PENDING", target="REJECTED")
    def reject(self, reviewer, notes):
        if not notes:
            raise ValueError("review_notes is required on rejection")
        from django.utils import timezone
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.review_notes = notes

    @transition(field=status, source="PENDING", target="WITHDRAWN")
    def withdraw(self):
        pass


# =============================================================================
# Audit & Activity Logging
# =============================================================================

class ActivityLog(models.Model):
    """Audit trail for all user actions."""

    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"
        ESCALATE = "ESCALATE", "Escalate"
        COMMENT = "COMMENT", "Comment"
        LOGIN = "LOGIN", "Login"
        LOGOUT = "LOGOUT", "Logout"

    actor = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="activity_logs",
        to_field="officer_id", db_column="actor_id",
    )
    action = models.CharField(max_length=50, choices=Action.choices)
    entity_type = models.CharField(max_length=100)
    entity_id = models.IntegerField(null=True, blank=True)
    old_data = models.TextField(blank=True, default="")
    new_data = models.TextField(blank=True, default="")
    remarks = models.TextField(blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "activity_log"
        ordering = ["-created_at"]


class VersionHistory(models.Model):
    """Field-level change tracking."""
    table_name = models.CharField(max_length=100)
    record_id = models.IntegerField()
    field_name = models.CharField(max_length=100)
    old_value = models.TextField(blank=True, default="")
    new_value = models.TextField(blank=True, default="")
    changed_by = models.CharField(max_length=50, blank=True, default="")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "version_history"
        indexes = [
            models.Index(fields=["table_name", "record_id"], name="idx_vh_table_record"),
        ]


# =============================================================================
# Configuration
# =============================================================================

class ConfigOption(models.Model):
    """Configurable dropdowns (domains, sub-domains, client types, etc.)."""
    category = models.CharField(max_length=100)
    option_value = models.CharField(max_length=200)
    option_label = models.CharField(max_length=500, blank=True, default="")
    parent_value = models.CharField(max_length=200, blank=True, default="")
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "config_options"
        unique_together = [("category", "option_value")]
        ordering = ["category", "sort_order"]


class FinancialYearTarget(models.Model):
    """Annual/quarterly targets per office."""
    financial_year = models.CharField(max_length=20)
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name="fy_targets",
        to_field="office_id", db_column="office_id",
    )
    annual_target = models.FloatField(default=0)
    q1_target = models.FloatField(default=0)
    q2_target = models.FloatField(default=0)
    q3_target = models.FloatField(default=0)
    q4_target = models.FloatField(default=0)
    training_target = models.IntegerField(default=0)
    lecture_target = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "financial_year_targets"
        unique_together = [("financial_year", "office")]


# =============================================================================
# Non-Revenue / Development Work
# =============================================================================

class NonRevenueSuggestion(models.Model):
    """Development/capacity-building work with approval workflow."""

    class ActivityType(models.TextChoices):
        CAPACITY_BUILDING = "CAPACITY_BUILDING", "Capacity Building"
        KNOWLEDGE_SHARING = "KNOWLEDGE_SHARING", "Knowledge Sharing"
        INTERNAL_PROJECT = "INTERNAL_PROJECT", "Internal Project"
        RESEARCH = "RESEARCH", "Research"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending Approval"
        APPROVED = "APPROVED", "Approved"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        ON_HOLD = "ON_HOLD", "On Hold"
        CONVERTED = "CONVERTED_TO_PR", "Converted to PR"
        COMPLETED = "COMPLETED", "Completed"
        DROPPED = "DROPPED", "Dropped"
        REJECTED = "REJECTED", "Rejected"

    suggestion_number = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, default="")
    activity_type = models.CharField(
        max_length=50, choices=ActivityType.choices, blank=True, default=""
    )
    beneficiary = models.CharField(max_length=500, blank=True, default="")
    domain = models.CharField(max_length=100, blank=True, default="")
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name="non_revenue_suggestions",
        to_field="office_id", db_column="office_id",
    )
    officer = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="allocated_suggestions",
        to_field="officer_id", db_column="officer_id",
    )
    justification = models.TextField(blank=True, default="")
    expected_outcome = models.TextField(blank=True, default="")
    notional_value = models.FloatField(default=0)
    target_start_date = models.DateField(null=True, blank=True)
    target_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=50, choices=Status.choices, default=Status.PENDING_APPROVAL
    )
    approval_status = models.CharField(max_length=50, default="PENDING")
    approved_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_suggestions",
        to_field="officer_id", db_column="approved_by",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="")
    current_update = models.TextField(blank=True, default="")
    drop_reason = models.TextField(blank=True, default="")
    remarks = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_suggestions",
        to_field="officer_id", db_column="created_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "non_revenue_suggestions"
        ordering = ["-created_at"]


# =============================================================================
# Grievance System
# =============================================================================

class GrievanceTicket(models.Model):
    """Grievance redressal with escalation levels."""

    class ComplaintType(models.TextChoices):
        ALLOCATION_PERCENT = "ALLOCATION_PERCENT", "Allocation Percentage"
        COST_ESTIMATE = "COST_ESTIMATE", "Cost Estimate"
        REVENUE_SHARE = "REVENUE_SHARE", "Revenue Share"
        MILESTONE_DATE = "MILESTONE_DATE", "Milestone Date"
        DATA_INCONSISTENCY = "DATA_INCONSISTENCY", "Data Inconsistency"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        ESCALATED = "ESCALATED", "Escalated"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    class EscalationLevel(models.TextChoices):
        TL = "TL", "Team Leader"
        HEAD = "HEAD", "Office Head"
        DDG = "DDG", "Deputy DG"
        DG = "DG", "Director General"

    ticket_number = models.CharField(max_length=100, unique=True)
    officer = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="grievances",
        to_field="officer_id", db_column="officer_id",
    )
    assignment = models.ForeignKey(
        Assignment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="grievances",
    )
    complaint_type = models.CharField(max_length=50, choices=ComplaintType.choices)
    subject = models.CharField(max_length=500)
    description = models.TextField()
    status = FSMField(default="OPEN", max_length=50)
    priority = models.CharField(
        max_length=50, choices=Priority.choices, default=Priority.NORMAL
    )
    current_level = models.CharField(
        max_length=50, choices=EscalationLevel.choices, default=EscalationLevel.TL
    )
    assigned_to = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_grievances",
        to_field="officer_id", db_column="assigned_to",
    )
    resolution = models.TextField(blank=True, default="")
    resolution_date = models.DateField(null=True, blank=True)
    escalation_due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "grievance_tickets"
        indexes = [
            models.Index(fields=["officer"], name="idx_gt_officer"),
            models.Index(fields=["status"], name="idx_gt_status"),
        ]
        ordering = ["-created_at"]


class GrievanceResponse(models.Model):
    """Responses/comments on grievance tickets."""

    class ResponseType(models.TextChoices):
        COMMENT = "COMMENT", "Comment"
        ACTION_TAKEN = "ACTION_TAKEN", "Action Taken"
        ESCALATION = "ESCALATION", "Escalation"
        RESOLUTION = "RESOLUTION", "Resolution"

    ticket = models.ForeignKey(
        GrievanceTicket, on_delete=models.CASCADE, related_name="responses"
    )
    responder = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="grievance_responses",
        to_field="officer_id", db_column="responder_id",
    )
    response_type = models.CharField(
        max_length=50, choices=ResponseType.choices, default=ResponseType.COMMENT
    )
    response_text = models.TextField()
    attachments = models.TextField(blank=True, default="")  # JSON array
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "grievance_responses"


class GrievanceEscalation(models.Model):
    """Escalation history for grievances."""
    ticket = models.ForeignKey(
        GrievanceTicket, on_delete=models.CASCADE, related_name="escalations"
    )
    from_level = models.CharField(max_length=50)
    to_level = models.CharField(max_length=50)
    from_handler = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="grievances_escalated_from",
        to_field="officer_id", db_column="from_handler",
    )
    to_handler = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="grievances_escalated_to",
        to_field="officer_id", db_column="to_handler",
    )
    escalation_reason = models.TextField(blank=True, default="")
    auto_escalated = models.BooleanField(default=False)
    escalated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "grievance_escalations"


# =============================================================================
# Utilization Claims
# =============================================================================

class UtilizationClaim(models.Model):
    """Officer effort/utilization tracking with TL -> Head workflow."""

    class ClaimType(models.TextChoices):
        ASSIGNMENT_WORK = "ASSIGNMENT_WORK", "Assignment Work"
        PROPOSAL_PREP = "PROPOSAL_PREP", "Proposal Preparation"
        EVENT_MGMT = "EVENT_MGMT", "Event Management"
        COMMITTEE = "COMMITTEE", "Committee Work"
        MEETING = "MEETING", "Meetings/Events"
        TRAVEL = "TRAVEL", "Official Travel"
        LEAVE = "LEAVE", "Leave"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        TL_APPROVED = "TL_APPROVED", "TL Approved"
        HEAD_RECTIFIED = "HEAD_RECTIFIED", "Head Rectified"
        FINAL = "FINAL", "Final"

    claim_number = models.CharField(max_length=100, unique=True)
    officer = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="utilization_claims",
        to_field="officer_id", db_column="officer_id",
    )
    assignment = models.ForeignKey(
        Assignment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="utilization_claims",
    )
    claim_month = models.CharField(max_length=20)
    activity_date = models.DateField()
    man_days_claimed = models.FloatField()
    activity_description = models.TextField(blank=True, default="")
    claim_type = models.CharField(
        max_length=50, choices=ClaimType.choices, default=ClaimType.ASSIGNMENT_WORK
    )
    status = FSMField(default="DRAFT", max_length=50)
    submitted_at = models.DateTimeField(null=True, blank=True)
    tl_approved_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tl_approved_claims",
        to_field="officer_id", db_column="tl_approved_by",
    )
    tl_approved_at = models.DateTimeField(null=True, blank=True)
    tl_remarks = models.TextField(blank=True, default="")
    head_rectified_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="head_rectified_claims",
        to_field="officer_id", db_column="head_rectified_by",
    )
    head_rectified_at = models.DateTimeField(null=True, blank=True)
    head_remarks = models.TextField(blank=True, default="")
    rectified_days = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "utilization_claims"
        indexes = [
            models.Index(fields=["officer"], name="idx_uc_officer"),
            models.Index(fields=["claim_month"], name="idx_uc_month"),
            models.Index(fields=["status"], name="idx_uc_status"),
        ]
        ordering = ["-activity_date"]


# =============================================================================
# Proposals & Documents
# =============================================================================

class ProposalDocument(models.Model):
    """File uploads for proposals, TOR, work orders, etc."""

    class DocumentType(models.TextChoices):
        PROPOSAL = "PROPOSAL", "Proposal"
        WORKLOAD = "WORKLOAD", "Workload"
        TOR = "TOR", "Terms of Reference"
        WORK_ORDER = "WORK_ORDER", "Work Order"
        OTHER = "OTHER", "Other"

    assignment = models.ForeignKey(
        Assignment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="documents",
    )
    document_type = models.CharField(
        max_length=50, choices=DocumentType.choices, default=DocumentType.PROPOSAL
    )
    file_name = models.CharField(max_length=500)
    file_path = models.CharField(max_length=1000)
    file_size = models.IntegerField(default=0)
    mime_type = models.CharField(max_length=200, blank=True, default="")
    description = models.TextField(blank=True, default="")
    uploaded_by = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="uploaded_documents",
        to_field="officer_id", db_column="uploaded_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "proposal_documents"
        indexes = [
            models.Index(fields=["assignment"], name="idx_pd_assignment"),
        ]


# =============================================================================
# Finance Officers
# =============================================================================

class FinanceOfficer(models.Model):
    """Finance officer assignments per office."""
    officer = models.ForeignKey(
        Officer, on_delete=models.CASCADE, related_name="finance_offices",
        to_field="officer_id", db_column="officer_id",
    )
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name="finance_officers",
        to_field="office_id", db_column="office_id",
    )
    is_active = models.BooleanField(default=True)
    assigned_by = models.CharField(max_length=50, blank=True, default="")
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_officers"
        indexes = [
            models.Index(fields=["officer"], name="idx_fo_officer"),
            models.Index(fields=["office"], name="idx_fo_office"),
        ]


# =============================================================================
# Training Module
# =============================================================================

class TrainingProgramme(models.Model):
    """Full training lifecycle with budget/trainer/revenue approvals."""
    programme_number = models.CharField(max_length=100, unique=True, blank=True, null=True)
    title = models.CharField(max_length=500, blank=True, default="")
    topic_domain = models.CharField(max_length=200, blank=True, default="")
    description = models.TextField(blank=True, default="")
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, null=True, blank=True,
        related_name="training_programmes",
        to_field="office_id", db_column="office_id",
    )
    mode = models.CharField(max_length=50, blank=True, default="")
    location = models.CharField(max_length=500, blank=True, default="")
    venue_details = models.TextField(blank=True, default="")
    training_start_date = models.DateField(null=True, blank=True)
    training_end_date = models.DateField(null=True, blank=True)
    duration_days = models.FloatField(default=0)
    budgeted_participants = models.IntegerField(default=0)
    fee_per_participant = models.FloatField(default=0)
    budgeted_revenue = models.FloatField(default=0)
    actual_revenue = models.FloatField(default=0)
    application_start_date = models.DateField(null=True, blank=True)
    application_end_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True, default="")
    coordinator = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="coordinated_programmes",
        to_field="officer_id", db_column="coordinator_id",
    )
    stage = models.CharField(max_length=50, default="DRAFT")
    approval_status = models.CharField(max_length=50, default="PENDING")
    budget_approval_status = models.CharField(max_length=50, default="PENDING")
    budget_submitted_by = models.CharField(max_length=50, blank=True, default="")
    budget_submitted_at = models.DateTimeField(null=True, blank=True)
    trainer_approval_status = models.CharField(max_length=50, default="PENDING")
    trainer_submitted_by = models.CharField(max_length=50, blank=True, default="")
    trainer_submitted_at = models.DateTimeField(null=True, blank=True)
    revenue_approval_status = models.CharField(max_length=50, default="PENDING")
    revenue_submitted_by = models.CharField(max_length=50, blank=True, default="")
    revenue_submitted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        Officer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_programmes",
        to_field="officer_id", db_column="created_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "training_programmes"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.programme_number} - {self.title}"


class TrainerAllocation(models.Model):
    """Trainer assignment to programmes."""
    programme = models.ForeignKey(
        TrainingProgramme, on_delete=models.CASCADE, related_name="trainers"
    )
    officer = models.ForeignKey(
        Officer, on_delete=models.PROTECT, related_name="trainer_allocations",
        to_field="officer_id", db_column="officer_id",
    )
    trainer_role = models.CharField(max_length=50, default="TRAINER")
    sessions_count = models.IntegerField(default=0)
    revenue_share_percent = models.FloatField(default=0)

    class Meta:
        db_table = "trainer_allocations"
        unique_together = [("programme", "officer")]


class TrainingParticipant(models.Model):
    """Participant registry for training programmes."""
    programme = models.ForeignKey(
        TrainingProgramme, on_delete=models.CASCADE, related_name="participants"
    )
    participant_name = models.CharField(max_length=200, blank=True, default="")
    organization = models.CharField(max_length=500, blank=True, default="")
    designation = models.CharField(max_length=200, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    registration_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "training_participants"


class TrainingChecklist(models.Model):
    """Step-by-step completion tracking for training programmes."""
    programme = models.ForeignKey(
        TrainingProgramme, on_delete=models.CASCADE, related_name="checklist"
    )
    step_order = models.IntegerField()
    step_name = models.CharField(max_length=500)
    is_completed = models.BooleanField(default=False)
    completed_by = models.CharField(max_length=50, blank=True, default="")
    completed_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True, default="")

    class Meta:
        db_table = "training_checklist"
        unique_together = [("programme", "step_order")]
        ordering = ["step_order"]


# =============================================================================
# Site Configuration (SCOPE_V2 §3.6 — admin-editable knobs)
# =============================================================================

class SiteConfig(models.Model):
    """Key-value settings editable from the admin panel.

    Used for runtime-tunable knobs that aren't secrets (secrets go in env/
    local_settings.py). Typed access via the helpers below; admins see and
    edit raw string values.
    """

    # Well-known keys. Keep in sync with helper methods.
    KEY_BULK_WINDOW_CLOSE = "bulk_onboarding_window_close"
    KEY_MAINTENANCE_MODE = "maintenance_mode_enabled"

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "Officer", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="site_config_updates",
        to_field="officer_id", db_column="updated_by",
    )

    class Meta:
        db_table = "site_config"
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value[:40]}"

    @classmethod
    def get(cls, key, default=None):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key, value, user=None, description=""):
        obj, _ = cls.objects.update_or_create(
            key=key,
            defaults={
                "value": str(value),
                "updated_by": user,
                **({"description": description} if description else {}),
            },
        )
        return obj

    @classmethod
    def bulk_window_close_date(cls):
        """Return the configured close date (datetime.date) or None if unset."""
        from datetime import date as _date
        raw = cls.get(cls.KEY_BULK_WINDOW_CLOSE, "")
        if not raw:
            return None
        try:
            return _date.fromisoformat(raw.strip())
        except ValueError:
            return None

    @classmethod
    def bulk_window_is_open(cls):
        """Window is open if no close date is set, or today <= close date.

        Default (unset) is OPEN — never accidentally lock out a fresh
        deployment. Admin configures a close date when ready to close.
        """
        from datetime import date as _date
        close = cls.bulk_window_close_date()
        return close is None or _date.today() <= close


# =============================================================================
# Cron heartbeat (M0-OPS-08, M0-REL-13)
# =============================================================================

class CronHeartbeat(models.Model):
    """
    One row per scheduled job. Updated on every run via core.cron.heartbeat().
    Admin dashboard reads this to show red/amber/green status per job.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"
        RUNNING = "running", "Running"

    job_name = models.CharField(max_length=100, unique=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCESS)
    last_error = models.TextField(blank=True, default="")
    last_duration_ms = models.IntegerField(default=0)
    # Used by `check_heartbeats` to decide if a job is overdue.
    expected_interval_seconds = models.IntegerField(default=86400)  # daily by default
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cron_heartbeat"
        ordering = ["job_name"]

    def __str__(self):
        return f"{self.job_name} [{self.last_status} @ {self.last_run_at}]"

    def is_overdue(self):
        """True if last_run_at is older than 1.5x expected interval."""
        from django.utils import timezone
        if self.last_run_at is None:
            return True  # never run
        threshold = timezone.now() - timezone.timedelta(seconds=int(self.expected_interval_seconds * 1.5))
        return self.last_run_at < threshold


# =============================================================================
# Register models with django-auditlog
# =============================================================================

auditlog.register(Assignment)
auditlog.register(Milestone)
auditlog.register(InvoiceRequest)
auditlog.register(PaymentReceipt)
auditlog.register(RevenueShare)
auditlog.register(ApprovalRequest)
auditlog.register(EditRequest)
auditlog.register(SiteConfig)
auditlog.register(Officer, exclude_fields=["password", "last_login"])
auditlog.register(GrievanceTicket)
auditlog.register(UtilizationClaim)
auditlog.register(TrainingProgramme)
