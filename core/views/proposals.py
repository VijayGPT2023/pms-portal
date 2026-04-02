"""
Proposal and Document Upload views.
"""
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.models import Assignment, Office, Officer, OfficerRole, ProposalDocument


DOCUMENT_TYPES = ["PROPOSAL", "WORKLOAD", "TOR", "WORK_ORDER", "OTHER"]

UPLOAD_DIR = getattr(settings, "UPLOAD_DIR", Path(settings.BASE_DIR) / "uploads")
MAX_UPLOAD_SIZE_MB = getattr(settings, "MAX_UPLOAD_SIZE_MB", 10)
ALLOWED_UPLOAD_EXTENSIONS = getattr(settings, "ALLOWED_UPLOAD_EXTENSIONS", [
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".jpg", ".png", ".zip",
])


def _can_manage_documents(user, assignment):
    """Check if user can upload/delete documents for this assignment."""
    role = user.admin_role_id or ""
    if role in ("ADMIN", "DG", "DDG-I", "DDG-II"):
        return True
    if assignment.team_leader == user:
        return True
    if user.office == assignment.office and role in ("RD_HEAD", "GROUP_HEAD"):
        return True
    if assignment.registered_by == user:
        return True
    return False


@login_required
def upload_form(request, assignment_id):
    """Document upload form."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    documents = (
        ProposalDocument.objects.filter(assignment=assignment)
        .select_related("uploaded_by")
        .order_by("-created_at")
    )
    return render(request, "proposals/upload.html", {
        "assignment": assignment,
        "documents": documents,
        "document_types": DOCUMENT_TYPES,
        "can_manage": _can_manage_documents(request.user, assignment),
        "max_upload_size_mb": MAX_UPLOAD_SIZE_MB,
        "allowed_extensions": ALLOWED_UPLOAD_EXTENSIONS,
    })


@login_required
def upload_document(request, assignment_id):
    """Upload a document."""
    if request.method != "POST":
        return redirect("core:proposal_upload", assignment_id=assignment_id)

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    if not _can_manage_documents(request.user, assignment):
        raise Http404("Not authorized")

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        raise Http404("No file selected")

    document_type = request.POST.get("document_type", "PROPOSAL")
    if document_type not in DOCUMENT_TYPES:
        raise Http404("Invalid document type")

    ext = Path(uploaded_file.name).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise Http404(f"File type '{ext}' not allowed")

    if uploaded_file.size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise Http404(f"File too large (max {MAX_UPLOAD_SIZE_MB} MB)")

    if uploaded_file.size == 0:
        raise Http404("Uploaded file is empty")

    upload_path = UPLOAD_DIR / str(assignment_id)
    os.makedirs(upload_path, exist_ok=True)

    original_filename = uploaded_file.name
    file_stem = Path(original_filename).stem
    file_ext = Path(original_filename).suffix
    final_filename = original_filename
    file_path = upload_path / final_filename
    counter = 1
    while file_path.exists():
        final_filename = f"{file_stem}_{counter}{file_ext}"
        file_path = upload_path / final_filename
        counter += 1

    with open(file_path, "wb") as f:
        for chunk in uploaded_file.chunks():
            f.write(chunk)

    ProposalDocument.objects.create(
        assignment=assignment,
        document_type=document_type,
        file_name=final_filename,
        file_path=str(file_path),
        file_size=uploaded_file.size,
        mime_type=uploaded_file.content_type or "application/octet-stream",
        description=request.POST.get("description", "").strip(),
        uploaded_by=request.user,
    )
    return redirect("core:proposal_upload", assignment_id=assignment_id)


@login_required
def download_document(request, document_id):
    """Download a document."""
    doc = get_object_or_404(ProposalDocument, pk=document_id)
    file_path = Path(doc.file_path)
    if not file_path.exists():
        raise Http404("File not found on disk")
    return FileResponse(
        open(file_path, "rb"),
        filename=doc.file_name,
        content_type=doc.mime_type or "application/octet-stream",
    )


@login_required
def delete_document(request, document_id):
    """Delete a document."""
    if request.method != "POST":
        raise Http404

    doc = get_object_or_404(ProposalDocument, pk=document_id)
    assignment = doc.assignment
    if assignment and not _can_manage_documents(request.user, assignment):
        raise Http404("Not authorized")

    assignment_id = doc.assignment_id
    file_path = Path(doc.file_path)
    if file_path.exists():
        try:
            os.remove(file_path)
        except OSError:
            pass
    doc.delete()
    return redirect("core:proposal_upload", assignment_id=assignment_id)


@login_required
def proposal_link_form(request, assignment_id):
    """Proposal link form."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    documents = (
        ProposalDocument.objects.filter(assignment=assignment)
        .select_related("uploaded_by")
        .order_by("-created_at")
    )

    linked_proposal = None
    if assignment.linked_proposal_id:
        try:
            linked_proposal = Assignment.objects.get(pk=assignment.linked_proposal_id)
        except Assignment.DoesNotExist:
            pass

    # Get assignments that have PROPOSAL documents
    available_proposals = (
        Assignment.objects.filter(
            documents__document_type="PROPOSAL",
        )
        .exclude(pk=assignment_id)
        .distinct()
        .order_by("-assignment_no")[:50]
    )

    return render(request, "proposals/link.html", {
        "assignment": assignment,
        "documents": documents,
        "linked_proposal": linked_proposal,
        "available_proposals": available_proposals,
        "document_types": DOCUMENT_TYPES,
        "can_manage": _can_manage_documents(request.user, assignment),
    })


@login_required
def link_proposal(request, assignment_id):
    """Link proposal to assignment."""
    if request.method != "POST":
        return redirect("core:proposal_link", assignment_id=assignment_id)

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    if not _can_manage_documents(request.user, assignment):
        raise Http404("Not authorized")

    link_mode = request.POST.get("link_mode", "")

    if link_mode == "upload":
        uploaded_file = request.FILES.get("file")
        if not uploaded_file or not uploaded_file.name:
            raise Http404("No file selected")

        ext = Path(uploaded_file.name).suffix.lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise Http404(f"File type not allowed")

        if uploaded_file.size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise Http404("File too large")

        upload_path = UPLOAD_DIR / str(assignment_id)
        os.makedirs(upload_path, exist_ok=True)

        final_filename = uploaded_file.name
        file_path = upload_path / final_filename
        counter = 1
        while file_path.exists():
            stem = Path(uploaded_file.name).stem
            suffix = Path(uploaded_file.name).suffix
            final_filename = f"{stem}_{counter}{suffix}"
            file_path = upload_path / final_filename
            counter += 1

        with open(file_path, "wb") as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        ProposalDocument.objects.create(
            assignment=assignment,
            document_type="PROPOSAL",
            file_name=final_filename,
            file_path=str(file_path),
            file_size=uploaded_file.size,
            mime_type=uploaded_file.content_type or "application/octet-stream",
            description=request.POST.get("description", "").strip(),
            uploaded_by=request.user,
        )

    elif link_mode == "link":
        linked_id = request.POST.get("linked_assignment_id")
        if not linked_id:
            raise Http404("No assignment selected")
        linked_id = int(linked_id)
        if linked_id == assignment_id:
            raise Http404("Cannot link to itself")

        get_object_or_404(Assignment, pk=linked_id)
        assignment.linked_proposal_id = linked_id
        assignment.save(update_fields=["linked_proposal_id"])

    return redirect("core:proposal_link", assignment_id=assignment_id)


@login_required
def proposal_list(request):
    """Proposal list view."""
    office = request.GET.get("office")
    atype = request.GET.get("type")
    has_proposal = request.GET.get("has_proposal")

    role = request.user.admin_role_id or ""
    qs = Assignment.objects.select_related("office").annotate(
        doc_count=Count("documents"),
    )

    if office:
        qs = qs.filter(office__office_id=office)
    if atype:
        qs = qs.filter(type=atype)
    if role not in ("ADMIN", "DG", "DDG-I", "DDG-II"):
        qs = qs.filter(office=request.user.office)

    if has_proposal == "yes":
        qs = qs.filter(
            models_Q_proposal_exists(True)
        )
    elif has_proposal == "no":
        qs = qs.filter(
            doc_count=0,
            linked_proposal_id__isnull=True,
        )

    qs = qs.order_by("-assignment_no")
    offices = Office.objects.order_by("office_name")

    return render(request, "proposals/list.html", {
        "assignments": qs,
        "offices": offices,
        "filter_office": office,
        "filter_type": atype,
        "filter_has_proposal": has_proposal,
    })


def models_Q_proposal_exists(val):
    """Helper Q object for proposal existence filter."""
    from django.db.models import Q
    if val:
        return Q(doc_count__gt=0) | Q(linked_proposal_id__isnull=False)
    return Q(doc_count=0, linked_proposal_id__isnull=True)


@login_required
def search_activities_api(request):
    """JSON autocomplete search for activities for linking."""
    from django.db.models import Q
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse([], safe=False)

    results = Assignment.objects.filter(
        Q(assignment_no__icontains=q) | Q(title__icontains=q)
    ).values("id", "assignment_no", "title", "type")[:20]
    return JsonResponse(list(results), safe=False)
