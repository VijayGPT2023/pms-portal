"""Core app URL configuration — all 177+ endpoints."""
from django.urls import path
from . import views
from .views import (
    assignments as asgn,
    approvals as appr,
    finance as fin,
    revenue as rev,
    mis,
    clients as cli,
    training as trn,
    utilization as util,
    reports as rpt,
    proposals as prop,
    admin_views as adm,
    data_management as data,
    non_revenue as nrev,
    profile as prof,
    edit_requests as ereq,
    pre_wo as prewo,
    mis_v2,
)

app_name = "core"

urlpatterns = [
    # ── Root & Auth ───────────────────────────────────────────────────
    path("", views.root_redirect, name="root"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("health/", views.health_check, name="health"),

    # Static legal / informational pages (public, no login required)
    path("privacy/", views.privacy_view, name="privacy"),
    path("terms/", views.terms_view, name="terms"),
    path("about/", views.about_view, name="about"),
    path("dpdp-notice/", views.dpdp_notice_view, name="dpdp_notice"),

    # ── Dashboard ─────────────────────────────────────────────────────
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/summary/", views.dashboard_summary_view, name="dashboard_summary"),
    path("dashboard/api/monthly-breakdown", views.monthly_breakdown_api, name="monthly_breakdown_api"),
    path("dashboard/api/business-mis", views.business_mis_api, name="business_mis_api"),

    # ── Assignments ───────────────────────────────────────────────────
    path("assignment/register/", asgn.register_activity, name="register_activity"),
    path("assignment/workorders/", asgn.workorders_list, name="workorders_list"),
    path("assignment/select-activity-type/", asgn.select_activity_type, name="select_activity_type"),
    path("assignment/new/", asgn.new_assignment, name="new_assignment"),
    path("assignment/select-type/<int:assignment_id>/", asgn.select_type, name="select_type"),
    path("assignment/edit/<int:assignment_id>/", asgn.edit_assignment, name="assignment_edit"),
    path("assignment/view/<int:assignment_id>/", asgn.view_assignment, name="assignment_view"),
    path("assignment/milestones/<int:assignment_id>/", asgn.manage_milestones, name="manage_milestones"),
    path("assignment/milestones/<int:assignment_id>/request-tentative-change/", asgn.request_tentative_date_change, name="request_tentative_change"),
    path("assignment/expenditure/<int:assignment_id>/", asgn.manage_expenditure, name="manage_expenditure"),
    path("assignment/expenditure-entry/<int:assignment_id>/", asgn.expenditure_entry, name="expenditure_entry"),
    path("mis/assignments/", asgn.assignments_list, name="assignments_list"),
    path("head/assignments/", asgn.head_assignment_hub, name="head_hub"),
    path("assignment/retrospective-fill/<int:assignment_id>/", asgn.retrospective_fill, name="retrospective_fill"),

    # ── Approvals ─────────────────────────────────────────────────────
    path("approvals/", appr.approvals_page, name="approvals"),
    path("approvals/registration/<int:assignment_id>/approve/", appr.approve_registration, name="approve_registration"),
    path("approvals/registration/<int:assignment_id>/reject/", appr.reject_registration, name="reject_registration"),
    path("approvals/assignment/<int:assignment_id>/approve/", appr.approve_assignment, name="approve_assignment"),
    path("approvals/assignment/<int:assignment_id>/reject/", appr.reject_assignment, name="reject_assignment"),
    path("approvals/allocate-tl/<int:assignment_id>/", appr.allocate_team_leader, name="allocate_team_leader"),
    path("approvals/request/<int:request_id>/approve/", appr.approve_request, name="approve_request"),
    path("approvals/request/<int:request_id>/reject/", appr.reject_request, name="reject_request"),
    path("approvals/request/<int:request_id>/escalate/", appr.escalate_request, name="escalate_request"),
    path("approvals/cost/<int:assignment_id>/submit/", appr.submit_cost_estimation, name="submit_cost_estimation"),
    path("approvals/cost/<int:assignment_id>/approve/", appr.approve_cost_estimation, name="approve_cost_estimation"),
    path("approvals/cost/<int:assignment_id>/reject/", appr.reject_cost_estimation, name="reject_cost_estimation"),
    path("approvals/team/<int:assignment_id>/submit/", appr.submit_team_constitution, name="submit_team_constitution"),
    path("approvals/team/<int:assignment_id>/approve/", appr.approve_team_constitution, name="approve_team_constitution"),
    path("approvals/team/<int:assignment_id>/reject/", appr.reject_team_constitution, name="reject_team_constitution"),
    path("approvals/milestone/<int:assignment_id>/submit/", appr.submit_milestone_planning, name="submit_milestone_planning"),
    path("approvals/milestone/<int:assignment_id>/approve/", appr.approve_milestone_planning, name="approve_milestone_planning"),
    path("approvals/milestone/<int:assignment_id>/reject/", appr.reject_milestone_planning, name="reject_milestone_planning"),
    path("approvals/revenue/<int:assignment_id>/submit/", appr.submit_revenue_shares, name="submit_revenue_shares"),
    path("approvals/revenue/<int:assignment_id>/approve/", appr.approve_revenue_shares, name="approve_revenue_shares"),
    path("approvals/revenue/<int:assignment_id>/reject/", appr.reject_revenue_shares, name="reject_revenue_shares"),
    path("approvals/tentative-date/<int:milestone_id>/approve/", appr.approve_tentative_date, name="approve_tentative_date"),
    path("approvals/tentative-date/<int:milestone_id>/reject/", appr.reject_tentative_date, name="reject_tentative_date"),

    # ── EditRequest ladder (SCOPE_V2 §3.5) ────────────────────────────
    path("edit-requests/", ereq.inbox, name="edit_request_inbox"),
    path("edit-requests/<int:request_id>/", ereq.detail, name="edit_request_detail"),
    path("edit-requests/<int:request_id>/approve/", ereq.approve, name="edit_request_approve"),
    path("edit-requests/<int:request_id>/reject/", ereq.reject, name="edit_request_reject"),
    path("edit-requests/<int:request_id>/withdraw/", ereq.withdraw, name="edit_request_withdraw"),
    path("edit-requests/propose/<int:assignment_id>/<str:section>/", ereq.propose_form, name="edit_request_propose"),

    # ── Finance ───────────────────────────────────────────────────────
    path("finance/", fin.finance_dashboard, name="finance_dashboard"),
    path("finance/officer-dashboard/", fin.finance_officer_dashboard, name="finance_officer_dashboard"),
    path("finance/invoice-request/<int:assignment_id>/", fin.invoice_request_form, name="invoice_request_form"),
    path("finance/invoice-request/<int:assignment_id>/submit/", fin.submit_invoice_request, name="submit_invoice_request"),
    path("finance/invoice-request-by-officer/<int:assignment_id>/", fin.officer_request_invoice, name="officer_request_invoice"),
    path("finance/invoice/<int:request_id>/approve/", fin.approve_invoice_request, name="approve_invoice"),
    path("finance/invoice/<int:request_id>/reject/", fin.reject_invoice_request, name="reject_invoice"),
    path("finance/invoice/<int:request_id>/tl-verify/", fin.tl_verify_invoice, name="tl_verify_invoice"),
    path("finance/payment/<int:invoice_id>/", fin.payment_form, name="payment_form"),
    path("finance/payment/<int:invoice_id>/record/", fin.record_payment, name="record_payment"),
    path("finance/invoice/<int:request_id>/hold-revenue/", fin.hold_revenue, name="hold_revenue"),
    path("finance/invoice/<int:request_id>/release-revenue/", fin.release_revenue, name="release_revenue"),

    # ── Revenue ───────────────────────────────────────────────────────
    path("revenue/edit/<int:assignment_id>/", rev.revenue_share_page, name="revenue_share_page"),
    path("revenue/edit/<int:assignment_id>/submit/", rev.revenue_share_submit, name="revenue_share_submit"),
    path("revenue/api/officers/", rev.api_get_officers, name="api_get_officers"),
    path("revenue/api/assignment/<int:assignment_id>/", rev.api_get_assignment, name="api_get_assignment"),
    # Revenue allocation flags (SCOPE_V2 §3.7)
    path("revenue/<int:assignment_id>/flag/", rev.raise_flag, name="revenue_raise_flag"),
    path("revenue/flag/<int:flag_id>/address/", rev.address_flag, name="revenue_address_flag"),
    path("revenue/flag/<int:flag_id>/withdraw/", rev.withdraw_flag, name="revenue_withdraw_flag"),

    # ── MIS V2 — three simpler dashboards (SCOPE_V2 §3.8) ──────────────
    path("mis/pre-wo/", mis_v2.pre_wo_mis, name="mis_pre_wo"),
    path("mis/revenue/", mis_v2.revenue_mis, name="mis_revenue"),
    path("mis/non-revenue/", mis_v2.non_revenue_mis, name="mis_non_revenue"),

    # ── MIS (legacy 6-tab — retired from nav, URLs kept for old links) ─
    path("mis/", mis.mis_dashboard, name="mis_dashboard"),
    path("mis/export/csv/", mis.mis_export_csv, name="mis_export_csv"),
    path("mis/office/<str:office_id>/", mis.office_detail, name="mis_office_detail"),

    # ── Clients ───────────────────────────────────────────────────────
    path("clients/", cli.client_list, name="client_list"),
    path("clients/new/", cli.new_client_form, name="new_client_form"),
    path("clients/new/submit/", cli.create_client, name="create_client"),
    path("clients/<int:client_id>/edit/", cli.edit_client_form, name="edit_client_form"),
    path("clients/<int:client_id>/edit/submit/", cli.update_client, name="update_client"),
    path("clients/<int:client_id>/view/", cli.view_client, name="view_client"),
    path("clients/assignment/<int:assignment_id>/manage/", cli.manage_assignment_clients, name="manage_assignment_clients"),
    path("clients/assignment/<int:assignment_id>/add/", cli.add_client_to_assignment, name="add_client_to_assignment"),
    path("clients/assignment/<int:assignment_id>/<int:link_id>/remove/", cli.remove_client_from_assignment, name="remove_client_from_assignment"),
    path("clients/mis/", cli.client_mis, name="client_mis"),
    path("clients/api/search/", cli.search_clients_api, name="search_clients_api"),

    # ── Training ──────────────────────────────────────────────────────
    path("training/", trn.training_list, name="training_list"),
    path("training/create/", trn.training_create_form, name="training_create_form"),
    path("training/create/submit/", trn.training_create, name="training_create"),
    path("training/view/<int:programme_id>/", trn.training_view, name="training_view"),
    path("training/checklist/<int:programme_id>/<int:step_order>/", trn.update_training_checklist, name="update_training_checklist"),
    path("training/edit/<int:programme_id>/", trn.training_edit_form, name="training_edit_form"),
    path("training/edit/<int:programme_id>/submit/", trn.training_edit, name="training_edit"),
    path("training/trainers/<int:programme_id>/", trn.trainer_allocation_form, name="trainer_allocation_form"),
    path("training/trainers/<int:programme_id>/submit/", trn.save_trainer_allocations, name="save_trainer_allocations"),
    path("training/approve/<int:programme_id>/", trn.approve_training_programme, name="approve_training"),
    path("training/reject/<int:programme_id>/", trn.reject_training_programme, name="reject_training"),
    path("training/allocate-coordinator/<int:programme_id>/", trn.allocate_coordinator, name="allocate_coordinator"),
    path("training/budget/<int:programme_id>/submit/", trn.submit_training_budget, name="submit_training_budget"),
    path("training/budget/<int:programme_id>/approve/", trn.approve_training_budget, name="approve_training_budget"),
    path("training/budget/<int:programme_id>/reject/", trn.reject_training_budget, name="reject_training_budget"),
    path("training/trainer/<int:programme_id>/submit/", trn.submit_trainer_allocation, name="submit_trainer_allocation"),
    path("training/trainer/<int:programme_id>/approve/", trn.approve_trainer_allocation, name="approve_trainer_allocation"),
    path("training/trainer/<int:programme_id>/reject/", trn.reject_trainer_allocation, name="reject_trainer_allocation"),
    path("training/revenue/<int:programme_id>/submit/", trn.submit_training_revenue, name="submit_training_revenue"),
    path("training/revenue/<int:programme_id>/approve/", trn.approve_training_revenue, name="approve_training_revenue"),
    path("training/revenue/<int:programme_id>/reject/", trn.reject_training_revenue, name="reject_training_revenue"),
    # Post-event 80-20 recognition (SCOPE_V2 §3.3)
    path("training/<int:programme_id>/register-completion/", trn.register_completion, name="training_register_completion"),
    path("training/<int:programme_id>/record-payment/", trn.record_training_payment, name="training_record_payment"),

    # ── Utilization ───────────────────────────────────────────────────
    path("utilization/", util.utilization_list, name="utilization_list"),
    path("utilization/new/", util.new_claim_form, name="new_claim_form"),
    path("utilization/new/submit/", util.create_claim, name="create_claim"),
    path("utilization/<int:claim_id>/edit/", util.edit_claim_form, name="edit_claim_form"),
    path("utilization/<int:claim_id>/edit/submit/", util.update_claim, name="update_claim"),
    path("utilization/<int:claim_id>/submit/", util.submit_claim, name="submit_claim"),
    path("utilization/pending-approval/", util.pending_approval, name="pending_approval"),
    path("utilization/<int:claim_id>/tl-approve/", util.tl_approve, name="tl_approve"),
    path("utilization/<int:claim_id>/tl-reject/", util.tl_reject, name="tl_reject"),
    path("utilization/pending-rectification/", util.pending_rectification, name="pending_rectification"),
    path("utilization/<int:claim_id>/head-rectify/", util.head_rectify, name="head_rectify"),
    path("utilization/<int:claim_id>/finalize/", util.finalize_claim, name="finalize_claim"),
    path("utilization/summary/", util.utilization_summary, name="utilization_summary"),

    # ── Reports ───────────────────────────────────────────────────────
    path("reports/delays/", rpt.delay_dashboard, name="delay_dashboard"),
    path("reports/delays/api/summary/", rpt.delay_summary_api, name="delay_summary_api"),
    path("reports/physical-progress/", rpt.physical_progress, name="physical_progress"),
    path("reports/financial-progress/", rpt.financial_progress, name="financial_progress"),
    path("reports/api/dashboard-summary/", rpt.dashboard_summary_api, name="dashboard_summary_api"),

    # ── Proposals ─────────────────────────────────────────────────────
    path("proposals/", prop.proposal_list, name="proposal_list"),
    path("proposals/upload/<int:assignment_id>/", prop.upload_form, name="proposal_upload_form"),
    path("proposals/upload/<int:assignment_id>/submit/", prop.upload_document, name="upload_document"),
    path("proposals/download/<int:document_id>/", prop.download_document, name="download_document"),
    path("proposals/delete/<int:document_id>/", prop.delete_document, name="delete_document"),
    path("proposals/link/<int:assignment_id>/", prop.proposal_link_form, name="proposal_link_form"),
    path("proposals/link/<int:assignment_id>/submit/", prop.link_proposal, name="link_proposal"),
    path("proposals/api/search-activities/", prop.search_activities_api, name="search_activities_api"),

    # ── Non-Revenue / Development Work (SCOPE_V2 §3.4) ─────────────────
    path("non-revenue/", nrev.list_suggestions, name="non_revenue_list"),
    path("non-revenue/create/", nrev.create_suggestion_form, name="non_revenue_create_form"),
    path("non-revenue/create/submit/", nrev.create_suggestion, name="non_revenue_create"),
    path("non-revenue/view/<int:suggestion_id>/", nrev.view_suggestion, name="non_revenue_view"),
    path("non-revenue/approve/<int:suggestion_id>/", nrev.approve_suggestion, name="non_revenue_approve"),
    path("non-revenue/reject/<int:suggestion_id>/", nrev.reject_suggestion, name="non_revenue_reject"),
    path("non-revenue/update/<int:suggestion_id>/", nrev.update_suggestion_progress, name="non_revenue_update"),
    path("non-revenue/complete/<int:suggestion_id>/", nrev.complete_suggestion, name="non_revenue_complete"),
    # Back-compat alias (base.html historically linked list_suggestions)
    path("non-revenue/list/", nrev.list_suggestions, name="list_suggestions"),

    # ── Pre-WO Pipeline (SCOPE_V2 §3.1) ───────────────────────────────
    path("pre-wo/", prewo.list_records, name="pre_wo_list"),
    path("pre-wo/create/", prewo.create_form, name="pre_wo_create_form"),
    path("pre-wo/create/submit/", prewo.create_record, name="pre_wo_create"),
    path("pre-wo/<int:record_id>/", prewo.view_record, name="pre_wo_view"),
    path("pre-wo/<int:record_id>/edit/", prewo.edit_form, name="pre_wo_edit_form"),
    path("pre-wo/<int:record_id>/edit/submit/", prewo.edit_record, name="pre_wo_edit"),
    path("pre-wo/<int:record_id>/approve/", prewo.approve_record, name="pre_wo_approve"),
    path("pre-wo/<int:record_id>/reject/", prewo.reject_record, name="pre_wo_reject"),
    path("pre-wo/<int:record_id>/close/", prewo.close_record, name="pre_wo_close"),

    # ── Profile ───────────────────────────────────────────────────────
    path("profile/", prof.view_profile, name="profile"),
    path("profile/change-password/", prof.change_password_form, name="change_password_form"),
    path("profile/change-password/submit/", prof.change_password_submit, name="change_password_submit"),

    # ── Admin ─────────────────────────────────────────────────────────
    path("admin-panel/users/", adm.user_management_page, name="user_management"),
    path("admin-panel/users/role/", adm.update_user_role, name="update_user_role"),
    path("admin-panel/users/reset-password/", adm.reset_user_password, name="reset_user_password"),
    path("admin-panel/roles/", adm.roles_management_page, name="roles_management"),
    path("admin-panel/roles/assign/", adm.assign_role, name="assign_role"),
    path("admin-panel/roles/remove/", adm.remove_role, name="remove_role"),
    path("admin-panel/officer/transfer/", adm.transfer_officer, name="transfer_officer"),

    # ── Data Management ───────────────────────────────────────────────
    path("data/export/", data.export_page, name="export_page"),
    path("data/export/assignments/", data.export_assignments, name="export_assignments"),
    path("data/import/", data.import_page, name="import_page"),
    path("data/import/submit/", data.import_data, name="import_data"),
    path("data/admin/config/", data.config_page, name="config_page"),
    path("data/admin/config/add/", data.add_config_option, name="add_config_option"),
    path("data/admin/config/update/", data.update_config_option, name="update_config_option"),
    path("data/admin/config/delete/", data.delete_config_option, name="delete_config_option"),
    path("data/api/subdomains/<str:domain>/", data.api_get_subdomains, name="api_get_subdomains"),
]
