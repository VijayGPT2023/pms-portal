"""
Django admin registration for all PMS Portal models.
Auto-generated admin panel — one of the key benefits of Django over FastAPI.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Office, Officer, Group, OfficerRole, ReportingHierarchy,
    OfficerHistory, DesignationHistory, OfficeTransferHistory,
    Assignment, Milestone, ExpenditureHead, ExpenditureItem, ExpenditureEntry,
    RevenueShare, InvoiceRequest, PaymentReceipt, OfficerRevenueLedger,
    InvoiceMilestoneLink, AssignmentTeam, Client, AssignmentClient,
    ApprovalRequest, EditRequest, ActivityLog, VersionHistory, ConfigOption,
    SiteConfig,
    FinancialYearTarget, NonRevenueSuggestion,
    GrievanceTicket, GrievanceResponse, GrievanceEscalation,
    UtilizationClaim, ProposalDocument, FinanceOfficer,
    TrainingProgramme, TrainerAllocation, TrainingParticipant, TrainingChecklist,
)


# =============================================================================
# Custom User Admin
# =============================================================================

@admin.register(Officer)
class OfficerAdmin(BaseUserAdmin):
    list_display = ("officer_id", "name", "email", "designation", "office", "admin_role_id", "is_active")
    list_filter = ("office", "admin_role_id", "is_active", "designation")
    search_fields = ("officer_id", "name", "email")
    ordering = ("name",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Officer Info", {"fields": ("officer_id", "name", "designation", "discipline", "office", "annual_target")}),
        ("Roles", {"fields": ("admin_role_id",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "officer_id", "name", "office", "password1", "password2"),
        }),
    )


# =============================================================================
# Core
# =============================================================================

@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display = ("office_id", "office_name", "officer_count", "annual_revenue_target")
    search_fields = ("office_id", "office_name")


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("group_code", "group_name", "is_active")


# =============================================================================
# Roles & Hierarchy
# =============================================================================

@admin.register(OfficerRole)
class OfficerRoleAdmin(admin.ModelAdmin):
    list_display = ("officer", "role_type", "scope_type", "scope_value", "is_primary", "effective_from")
    list_filter = ("role_type", "scope_type", "is_primary")
    search_fields = ("officer__officer_id", "officer__name")


@admin.register(ReportingHierarchy)
class ReportingHierarchyAdmin(admin.ModelAdmin):
    list_display = ("entity_type", "entity_value", "reports_to_role")


# =============================================================================
# Assignment & Related
# =============================================================================

class MilestoneInline(admin.TabularInline):
    model = Milestone
    extra = 0
    fields = ("milestone_no", "title", "target_date", "status", "invoice_percent")


class RevenueShareInline(admin.TabularInline):
    model = RevenueShare
    extra = 0
    fields = ("officer", "share_percent", "share_amount")


class AssignmentTeamInline(admin.TabularInline):
    model = AssignmentTeam
    extra = 0
    fields = ("officer", "role", "is_active")


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("assignment_no", "title", "type", "office", "status", "workflow_stage", "total_value")
    list_filter = ("type", "status", "workflow_stage", "office", "domain")
    search_fields = ("assignment_no", "title", "client")
    readonly_fields = ("created_at", "updated_at")
    inlines = [MilestoneInline, RevenueShareInline, AssignmentTeamInline]

    fieldsets = (
        ("Basic Info", {"fields": ("assignment_no", "type", "title", "office", "domain", "sub_domain")}),
        ("Client", {"fields": ("client", "client_type", "city")}),
        ("Dates", {"fields": ("work_order_date", "start_date", "target_date")}),
        ("Team", {"fields": ("team_leader", "registered_by")}),
        ("Financial", {"fields": ("total_value", "gross_value", "invoice_amount", "amount_received", "total_revenue", "total_expenditure", "surplus_deficit")}),
        ("Progress", {"fields": ("physical_progress_percent", "timeline_progress_percent")}),
        ("Workflow", {"fields": ("status", "workflow_stage", "registration_status")}),
        ("Section Approvals", {"fields": ("approval_status", "cost_approval_status", "team_approval_status", "milestone_approval_status", "revenue_approval_status")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ("assignment", "milestone_no", "title", "target_date", "status", "invoice_amount")
    list_filter = ("status",)
    search_fields = ("title", "assignment__assignment_no")


# =============================================================================
# Finance
# =============================================================================

@admin.register(InvoiceRequest)
class InvoiceRequestAdmin(admin.ModelAdmin):
    list_display = ("request_number", "assignment", "invoice_amount", "status", "fy_period", "requested_at")
    list_filter = ("status", "invoice_type", "fy_period")
    search_fields = ("request_number", "assignment__assignment_no")


@admin.register(PaymentReceipt)
class PaymentReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "invoice_request", "amount_received", "receipt_date", "payment_mode")
    list_filter = ("payment_mode", "fy_period")


@admin.register(OfficerRevenueLedger)
class OfficerRevenueLedgerAdmin(admin.ModelAdmin):
    list_display = ("officer", "assignment", "revenue_type", "amount", "fy_period", "is_held")
    list_filter = ("revenue_type", "is_held", "fy_period")


@admin.register(ExpenditureHead)
class ExpenditureHeadAdmin(admin.ModelAdmin):
    list_display = ("head_code", "head_name", "category", "is_active")
    list_filter = ("category", "is_active")


# =============================================================================
# Clients
# =============================================================================

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("client_code", "client_name", "client_type", "city", "is_active")
    list_filter = ("client_type", "is_active")
    search_fields = ("client_code", "client_name")


# =============================================================================
# Approvals & Audit
# =============================================================================

@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("request_type", "reference_type", "reference_id", "status", "requested_by", "created_at")
    list_filter = ("request_type", "status")


@admin.register(EditRequest)
class EditRequestAdmin(admin.ModelAdmin):
    list_display = ("assignment", "section", "edit_number", "status", "proposed_by", "reviewed_by", "proposed_at")
    list_filter = ("section", "status")
    search_fields = ("assignment__assignment_no", "proposed_by__officer_id")
    readonly_fields = ("edit_number", "proposed_at", "created_at", "updated_at")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("actor", "action", "entity_type", "entity_id", "created_at")
    list_filter = ("action", "entity_type")
    readonly_fields = ("actor", "action", "entity_type", "entity_id", "old_data", "new_data", "created_at")


# =============================================================================
# Grievance
# =============================================================================

@admin.register(GrievanceTicket)
class GrievanceTicketAdmin(admin.ModelAdmin):
    list_display = ("ticket_number", "officer", "complaint_type", "status", "priority", "current_level")
    list_filter = ("status", "priority", "complaint_type", "current_level")


# =============================================================================
# Utilization
# =============================================================================

@admin.register(UtilizationClaim)
class UtilizationClaimAdmin(admin.ModelAdmin):
    list_display = ("claim_number", "officer", "claim_type", "man_days_claimed", "status", "claim_month")
    list_filter = ("status", "claim_type", "claim_month")


# =============================================================================
# Training
# =============================================================================

@admin.register(TrainingProgramme)
class TrainingProgrammeAdmin(admin.ModelAdmin):
    list_display = ("programme_number", "title", "office", "stage", "training_start_date", "budgeted_revenue")
    list_filter = ("stage", "approval_status", "mode")
    search_fields = ("programme_number", "title")


# =============================================================================
# Configuration & Other
# =============================================================================

@admin.register(ConfigOption)
class ConfigOptionAdmin(admin.ModelAdmin):
    list_display = ("category", "option_value", "option_label", "sort_order", "is_active")
    list_filter = ("category", "is_active")


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "updated_by", "updated_at")
    search_fields = ("key", "value")
    readonly_fields = ("updated_at",)


@admin.register(FinancialYearTarget)
class FinancialYearTargetAdmin(admin.ModelAdmin):
    list_display = ("financial_year", "office", "annual_target")
    list_filter = ("financial_year",)


@admin.register(NonRevenueSuggestion)
class NonRevenueSuggestionAdmin(admin.ModelAdmin):
    list_display = ("suggestion_number", "title", "office", "status", "notional_value")
    list_filter = ("status", "activity_type")


# Simple registrations for remaining models
admin.site.register(ExpenditureItem)
admin.site.register(ExpenditureEntry)
admin.site.register(RevenueShare)
admin.site.register(InvoiceMilestoneLink)
admin.site.register(AssignmentTeam)
admin.site.register(AssignmentClient)
admin.site.register(OfficerHistory)
admin.site.register(DesignationHistory)
admin.site.register(OfficeTransferHistory)
admin.site.register(VersionHistory)
admin.site.register(GrievanceResponse)
admin.site.register(GrievanceEscalation)
admin.site.register(ProposalDocument)
admin.site.register(FinanceOfficer)
admin.site.register(TrainerAllocation)
admin.site.register(TrainingParticipant)
admin.site.register(TrainingChecklist)

# Admin site branding
admin.site.site_header = "PMS Portal Administration"
admin.site.site_title = "PMS Portal Admin"
admin.site.index_title = "Dashboard"
