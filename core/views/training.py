"""
Training Programme views: CRUD and approval workflows.
"""
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import (
    ActivityLog, InvoiceRequest, Officer, Office,
    TrainerAllocation, TrainingChecklist, TrainingParticipant,
    TrainingProgramme,
)


def _is_head_or_admin(user):
    return user.is_staff or user.admin_role_id in (
        "ADMIN", "DG", "DDG-I", "DDG-II", "RD_HEAD", "GROUP_HEAD",
    )


def _generate_programme_number(office_id):
    today = date.today()
    prefix = f"TRN-{office_id}-{today.strftime('%Y%m')}"
    count = TrainingProgramme.objects.filter(programme_number__startswith=prefix).count()
    return f"{prefix}-{count + 1:03d}"


@login_required
def training_list(request):
    """List training programmes."""
    user = request.user
    if _is_head_or_admin(user):
        qs = TrainingProgramme.objects.all()
    else:
        qs = TrainingProgramme.objects.filter(
            Q(office=user.office)
            | Q(coordinator=user)
            | Q(trainers__officer=user)
        ).distinct()

    qs = qs.select_related("coordinator", "office").order_by("-created_at")

    stats = TrainingProgramme.objects.aggregate(
        total=Count("id"),
        announced=Count("id", filter=Q(stage="ANNOUNCED")),
        registration_open=Count("id", filter=Q(stage="REGISTRATION_OPEN")),
        conducted=Count("id", filter=Q(stage="CONDUCTED")),
        closed=Count("id", filter=Q(stage="CLOSED")),
        total_budgeted=Sum("budgeted_revenue"),
        total_actual=Sum("actual_revenue"),
    )

    return render(request, "training/list.html", {
        "programmes": qs,
        "stats": stats,
    })


@login_required
def training_create_form(request):
    """Display training programme creation form."""
    offices = Office.objects.order_by("office_name")
    officers = Officer.objects.filter(is_active=True).order_by("name")
    return render(request, "training/form.html", {
        "programme": None,
        "offices": offices,
        "officers": officers,
        "is_new": True,
    })


@login_required
def training_create(request):
    """Create a new training programme."""
    if request.method != "POST":
        return redirect("core:training_list")

    office_id = request.POST["office_id"]
    budgeted_participants = int(request.POST.get("budgeted_participants", 0))
    fee_per_participant = float(request.POST.get("fee_per_participant", 0))
    programme_number = _generate_programme_number(office_id)

    office = Office.objects.get(office_id=office_id)
    programme = TrainingProgramme.objects.create(
        programme_number=programme_number,
        title=request.POST.get("title", ""),
        topic_domain=request.POST.get("topic_domain", ""),
        description=request.POST.get("description", ""),
        office=office,
        mode=request.POST.get("mode", "IN_PERSON"),
        location=request.POST.get("location", ""),
        venue_details=request.POST.get("venue_details", ""),
        training_start_date=request.POST.get("training_start_date") or None,
        training_end_date=request.POST.get("training_end_date") or None,
        duration_days=int(request.POST.get("duration_days", 0)),
        budgeted_participants=budgeted_participants,
        fee_per_participant=fee_per_participant,
        budgeted_revenue=budgeted_participants * fee_per_participant,
        application_start_date=request.POST.get("application_start_date") or None,
        application_end_date=request.POST.get("application_end_date") or None,
        remarks=request.POST.get("remarks", ""),
        created_by=request.user,
        stage="ANNOUNCED",
        approval_status="DRAFT",
    )

    # Initialize default checklist
    _initialize_checklist(programme)

    ActivityLog.objects.create(
        actor=request.user, action="CREATE",
        entity_type="training_programme", entity_id=programme.pk,
        remarks="Training programme created",
    )
    return redirect("core:training_view", programme_id=programme.pk)


def _initialize_checklist(programme):
    """Create default preparation checklist."""
    steps = [
        "Venue Booking", "Brochure / Circular Preparation", "Brochure Approval",
        "Circular Distribution", "Trainer Confirmation", "Material Preparation",
        "Logistics Arrangement", "Registration Collection", "Pre-event Check",
    ]
    for i, step in enumerate(steps, 1):
        TrainingChecklist.objects.get_or_create(
            programme=programme, step_order=i,
            defaults={"step_name": step},
        )


@login_required
def training_view(request, programme_id):
    """View training programme details."""
    programme = get_object_or_404(
        TrainingProgramme.objects.select_related("coordinator", "office", "created_by"),
        pk=programme_id,
    )

    trainers = (
        TrainerAllocation.objects.filter(programme=programme)
        .select_related("officer")
        .order_by("trainer_role", "officer__name")
    )
    participants = TrainingParticipant.objects.filter(programme=programme).order_by("-registration_date")
    checklist = TrainingChecklist.objects.filter(programme=programme).order_by("step_order")

    if not checklist.exists():
        _initialize_checklist(programme)
        checklist = TrainingChecklist.objects.filter(programme=programme).order_by("step_order")

    can_edit = (
        _is_head_or_admin(request.user)
        or programme.coordinator == request.user
        or programme.created_by == request.user
    )

    return render(request, "training/view.html", {
        "programme": programme,
        "trainers": trainers,
        "participants": participants,
        "checklist": checklist,
        "can_edit": can_edit,
    })


@login_required
def update_training_checklist(request, programme_id, step_order):
    """Update a checklist step."""
    if request.method != "POST":
        return redirect("core:training_view", programme_id=programme_id)

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    can_edit = (
        _is_head_or_admin(request.user)
        or programme.coordinator == request.user
        or programme.created_by == request.user
    )
    if not can_edit:
        return redirect("core:training_view", programme_id=programme_id)

    is_completed = request.POST.get("is_completed") == "1"
    remarks = request.POST.get("remarks", "")

    try:
        step = TrainingChecklist.objects.get(programme=programme, step_order=step_order)
        step.is_completed = is_completed
        step.completed_by = request.user.officer_id if is_completed else ""
        step.completed_date = date.today() if is_completed else None
        step.remarks = remarks
        step.save()
    except TrainingChecklist.DoesNotExist:
        pass

    return redirect("core:training_view", programme_id=programme_id)


@login_required
def training_edit_form(request, programme_id):
    """Training programme edit form."""
    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    offices = Office.objects.order_by("office_name")
    officers = Officer.objects.filter(is_active=True).order_by("name")

    return render(request, "training/form.html", {
        "programme": programme,
        "offices": offices,
        "officers": officers,
        "is_new": False,
    })


@login_required
def training_edit(request, programme_id):
    """Update training programme."""
    if request.method != "POST":
        return redirect("core:training_view", programme_id=programme_id)

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    budgeted_participants = int(request.POST.get("budgeted_participants", 0))
    fee_per_participant = float(request.POST.get("fee_per_participant", 0))

    programme.title = request.POST.get("title", "")
    programme.topic_domain = request.POST.get("topic_domain", "")
    programme.description = request.POST.get("description", "")
    programme.office = Office.objects.get(office_id=request.POST["office_id"])
    programme.mode = request.POST.get("mode", "IN_PERSON")
    programme.location = request.POST.get("location", "")
    programme.venue_details = request.POST.get("venue_details", "")
    programme.training_start_date = request.POST.get("training_start_date") or None
    programme.training_end_date = request.POST.get("training_end_date") or None
    programme.duration_days = int(request.POST.get("duration_days", 0))
    programme.budgeted_participants = budgeted_participants
    programme.fee_per_participant = fee_per_participant
    programme.budgeted_revenue = budgeted_participants * fee_per_participant
    programme.application_start_date = request.POST.get("application_start_date") or None
    programme.application_end_date = request.POST.get("application_end_date") or None
    programme.stage = request.POST.get("stage", programme.stage)
    programme.remarks = request.POST.get("remarks", "")
    programme.save()

    ActivityLog.objects.create(
        actor=request.user, action="UPDATE",
        entity_type="training_programme", entity_id=programme.pk,
        remarks="Training programme updated",
    )
    return redirect("core:training_view", programme_id=programme.pk)


@login_required
def trainer_allocation_form(request, programme_id):
    """Trainer allocation form."""
    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    trainers = (
        TrainerAllocation.objects.filter(programme=programme)
        .select_related("officer")
        .order_by("trainer_role", "officer__name")
    )
    officers = Officer.objects.filter(is_active=True).order_by("name")

    return render(request, "training/trainer_allocation.html", {
        "programme": programme,
        "trainers": trainers,
        "officers": officers,
    })


@login_required
def save_trainer_allocations(request, programme_id):
    """Save trainer allocations."""
    if request.method != "POST":
        return redirect("core:training_view", programme_id=programme_id)

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    TrainerAllocation.objects.filter(programme=programme).delete()

    i = 0
    while f"trainer_{i}_officer_id" in request.POST:
        officer_id = request.POST.get(f"trainer_{i}_officer_id")
        if officer_id:
            officer = Officer.objects.get(officer_id=officer_id)
            TrainerAllocation.objects.create(
                programme=programme,
                officer=officer,
                trainer_role=request.POST.get(f"trainer_{i}_role", "CO_TRAINER"),
                revenue_share_percent=float(request.POST.get(f"trainer_{i}_percent", 0) or 0),
                sessions_count=int(request.POST.get(f"trainer_{i}_days", 0) or 0),
            )
        i += 1

    ActivityLog.objects.create(
        actor=request.user, action="UPDATE",
        entity_type="trainer_allocations", entity_id=programme.pk,
        remarks="Trainer allocations updated",
    )
    return redirect(f"/training/view/{programme_id}?success=trainers_saved")


@login_required
def approve_training_programme(request, programme_id):
    """Head approves training programme."""
    if request.method != "POST" or not _is_head_or_admin(request.user):
        return redirect("core:training_list")

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    programme.approval_status = "APPROVED"
    programme.save(update_fields=["approval_status"])

    ActivityLog.objects.create(
        actor=request.user, action="APPROVE",
        entity_type="training_programme", entity_id=programme.pk,
        remarks="Training programme approved",
    )
    return redirect("core:approvals_list")


@login_required
def reject_training_programme(request, programme_id):
    """Head rejects training programme."""
    if request.method != "POST" or not _is_head_or_admin(request.user):
        return redirect("core:training_list")

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    programme.approval_status = "REJECTED"
    programme.remarks = request.POST.get("rejection_remarks", "")
    programme.save(update_fields=["approval_status", "remarks"])

    ActivityLog.objects.create(
        actor=request.user, action="REJECT",
        entity_type="training_programme", entity_id=programme.pk,
        remarks=programme.remarks,
    )
    return redirect("core:approvals_list")


@login_required
def allocate_coordinator(request, programme_id):
    """Head allocates coordinator."""
    if request.method != "POST" or not _is_head_or_admin(request.user):
        return redirect("core:training_list")

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    coordinator_id = request.POST.get("coordinator_id")
    coordinator = Officer.objects.get(officer_id=coordinator_id)

    programme.coordinator = coordinator
    programme.save(update_fields=["coordinator"])

    # Also add as PRIMARY trainer if not exists
    TrainerAllocation.objects.get_or_create(
        programme=programme, officer=coordinator,
        defaults={"trainer_role": "PRIMARY", "revenue_share_percent": 0},
    )

    ActivityLog.objects.create(
        actor=request.user, action="UPDATE",
        entity_type="training_programme", entity_id=programme.pk,
        new_data=f"coordinator={coordinator_id}",
        remarks="Coordinator allocated",
    )
    return redirect("core:approvals_list")


@login_required
def submit_training_budget(request, programme_id):
    """Coordinator submits budget for approval."""
    if request.method != "POST":
        return redirect("core:training_view", programme_id=programme_id)

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    programme.budget_approval_status = "SUBMITTED"
    programme.budget_submitted_by = request.user.officer_id
    programme.budget_submitted_at = timezone.now()
    programme.save(update_fields=["budget_approval_status", "budget_submitted_by", "budget_submitted_at"])

    ActivityLog.objects.create(
        actor=request.user, action="CREATE",
        entity_type="training_budget", entity_id=programme.pk,
        remarks="Budget submitted for approval",
    )
    return redirect(f"/training/view/{programme_id}?success=budget_submitted")


@login_required
def approve_training_budget(request, programme_id):
    """Head approves training budget."""
    if request.method != "POST" or not _is_head_or_admin(request.user):
        return redirect("core:training_list")

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    programme.budget_approval_status = "APPROVED"
    programme.save(update_fields=["budget_approval_status"])

    ActivityLog.objects.create(
        actor=request.user, action="APPROVE",
        entity_type="training_budget", entity_id=programme.pk,
        remarks="Budget approved",
    )
    return redirect("core:approvals_list")


@login_required
def reject_training_budget(request, programme_id):
    """Head rejects training budget."""
    if request.method != "POST" or not _is_head_or_admin(request.user):
        return redirect("core:training_list")

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    programme.budget_approval_status = "REJECTED"
    programme.remarks = request.POST.get("rejection_remarks", "")
    programme.save(update_fields=["budget_approval_status", "remarks"])

    ActivityLog.objects.create(
        actor=request.user, action="REJECT",
        entity_type="training_budget", entity_id=programme.pk,
        remarks=programme.remarks,
    )
    return redirect("core:approvals_list")


@login_required
def submit_trainer_allocation(request, programme_id):
    """Coordinator submits trainer allocation."""
    if request.method != "POST":
        return redirect("core:training_view", programme_id=programme_id)

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    if not TrainerAllocation.objects.filter(programme=programme).exists():
        return redirect(f"/training/trainers/{programme_id}?error=no_trainers")

    programme.trainer_approval_status = "SUBMITTED"
    programme.trainer_submitted_by = request.user.officer_id
    programme.trainer_submitted_at = timezone.now()
    programme.save(update_fields=["trainer_approval_status", "trainer_submitted_by", "trainer_submitted_at"])

    return redirect(f"/training/view/{programme_id}?success=trainer_submitted")


@login_required
def approve_trainer_allocation(request, programme_id):
    """Head approves trainer allocation."""
    if request.method != "POST" or not _is_head_or_admin(request.user):
        return redirect("core:training_list")

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    programme.trainer_approval_status = "APPROVED"
    programme.save(update_fields=["trainer_approval_status"])
    return redirect("core:approvals_list")


@login_required
def reject_trainer_allocation(request, programme_id):
    """Head rejects trainer allocation."""
    if request.method != "POST" or not _is_head_or_admin(request.user):
        return redirect("core:training_list")

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    programme.trainer_approval_status = "REJECTED"
    programme.remarks = request.POST.get("rejection_remarks", "")
    programme.save(update_fields=["trainer_approval_status", "remarks"])
    return redirect("core:approvals_list")


@login_required
def submit_training_revenue(request, programme_id):
    """Coordinator submits revenue shares."""
    if request.method != "POST":
        return redirect("core:training_view", programme_id=programme_id)

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)

    total = TrainerAllocation.objects.filter(programme=programme).aggregate(
        t=Sum("revenue_share_percent"),
    )["t"] or 0
    if abs(total - 100) > 0.01:
        return redirect(f"/training/trainers/{programme_id}?error=total_not_100")

    programme.revenue_approval_status = "SUBMITTED"
    programme.revenue_submitted_by = request.user.officer_id
    programme.revenue_submitted_at = timezone.now()
    programme.save(update_fields=["revenue_approval_status", "revenue_submitted_by", "revenue_submitted_at"])
    return redirect(f"/training/view/{programme_id}?success=revenue_submitted")


@login_required
def approve_training_revenue(request, programme_id):
    """Head approves training revenue shares."""
    if request.method != "POST" or not _is_head_or_admin(request.user):
        return redirect("core:training_list")

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    programme.revenue_approval_status = "APPROVED"
    programme.save(update_fields=["revenue_approval_status"])
    return redirect("core:approvals_list")


@login_required
def reject_training_revenue(request, programme_id):
    """Head rejects training revenue shares."""
    if request.method != "POST" or not _is_head_or_admin(request.user):
        return redirect("core:training_list")

    programme = get_object_or_404(TrainingProgramme, pk=programme_id)
    programme.revenue_approval_status = "REJECTED"
    programme.remarks = request.POST.get("rejection_remarks", "")
    programme.save(update_fields=["revenue_approval_status", "remarks"])
    return redirect("core:approvals_list")
