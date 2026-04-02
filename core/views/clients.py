"""
Client Database Management and Multi-Client Assignment views.
"""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum, F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.models import Assignment, AssignmentClient, Client, Office


@login_required
def client_list(request):
    """List all clients with search/filter."""
    search = request.GET.get("search")
    client_type = request.GET.get("client_type")
    city = request.GET.get("city")

    qs = Client.objects.filter(is_active=True)
    if search:
        qs = qs.filter(
            Q(client_name__icontains=search)
            | Q(client_code__icontains=search)
            | Q(contact_person__icontains=search)
        )
    if client_type:
        qs = qs.filter(client_type=client_type)
    if city:
        qs = qs.filter(city__icontains=city)

    qs = qs.annotate(
        assignment_count=Count("assignment_links"),
        total_value=Sum("assignment_links__assignment__total_value"),
    ).order_by("client_name")

    return render(request, "clients/list.html", {
        "clients": qs,
        "filter_search": search,
        "filter_type": client_type,
        "filter_city": city,
        "client_types": settings.CLIENT_TYPE_OPTIONS,
    })


@login_required
def new_client_form(request):
    """Client creation form."""
    return render(request, "clients/form.html", {
        "client": None,
        "client_types": settings.CLIENT_TYPE_OPTIONS,
        "is_edit": False,
    })


@login_required
def create_client(request):
    """Create a new client."""
    if request.method != "POST":
        return redirect("core:client_list")

    name = request.POST.get("client_name", "").strip()
    ctype = request.POST.get("client_type", "Others")

    # Generate client code
    prefix = ctype[:3].upper() if ctype else "OTH"
    count = Client.objects.filter(client_code__startswith=prefix).count()
    client_code = f"{prefix}-{count + 1:04d}"

    Client.objects.create(
        client_code=client_code,
        client_name=name,
        client_type=ctype,
        address=request.POST.get("address", "").strip(),
        city=request.POST.get("city", "").strip(),
        state=request.POST.get("state", "").strip(),
        contact_person=request.POST.get("contact_person", "").strip(),
        contact_email=request.POST.get("contact_email", "").strip(),
        contact_phone=request.POST.get("contact_phone", "").strip(),
        gstin=request.POST.get("gstin", "").strip(),
        pan=request.POST.get("pan", "").strip(),
        created_by=request.user,
    )
    return redirect("core:client_list")


@login_required
def edit_client_form(request, client_id):
    """Edit client form."""
    client = get_object_or_404(Client, pk=client_id)
    return render(request, "clients/form.html", {
        "client": client,
        "client_types": settings.CLIENT_TYPE_OPTIONS,
        "is_edit": True,
    })


@login_required
def update_client(request, client_id):
    """Update client details."""
    if request.method != "POST":
        return redirect("core:view_client", client_id=client_id)

    client = get_object_or_404(Client, pk=client_id)
    client.client_name = request.POST.get("client_name", "").strip()
    client.client_type = request.POST.get("client_type", "Others")
    client.address = request.POST.get("address", "").strip()
    client.city = request.POST.get("city", "").strip()
    client.state = request.POST.get("state", "").strip()
    client.contact_person = request.POST.get("contact_person", "").strip()
    client.contact_email = request.POST.get("contact_email", "").strip()
    client.contact_phone = request.POST.get("contact_phone", "").strip()
    client.gstin = request.POST.get("gstin", "").strip()
    client.pan = request.POST.get("pan", "").strip()
    client.save()
    return redirect("core:view_client", client_id=client_id)


@login_required
def view_client(request, client_id):
    """View client details + all assignments."""
    client = get_object_or_404(Client, pk=client_id)

    assignments = (
        AssignmentClient.objects.filter(client=client)
        .select_related("assignment")
        .order_by("-assignment__created_at")
    )

    stats = AssignmentClient.objects.filter(client=client).aggregate(
        total_assignments=Count("id"),
        total_value=Sum(F("assignment__total_value") * F("billing_share_percent") / 100),
        total_invoiced=Sum(F("assignment__invoice_amount") * F("billing_share_percent") / 100),
        total_received=Sum(F("assignment__amount_received") * F("billing_share_percent") / 100),
    )

    return render(request, "clients/view.html", {
        "client": client,
        "assignments": assignments,
        "stats": stats,
    })


@login_required
def manage_assignment_clients(request, assignment_id):
    """Manage clients for an assignment."""
    assignment = get_object_or_404(Assignment, pk=assignment_id)

    linked_clients = (
        AssignmentClient.objects.filter(assignment=assignment)
        .select_related("client")
        .order_by("-is_primary", "client__client_name")
    )

    all_clients = Client.objects.filter(is_active=True).order_by("client_name")

    return render(request, "clients/assignment_clients.html", {
        "assignment": assignment,
        "linked_clients": linked_clients,
        "all_clients": all_clients,
    })


@login_required
def add_client_to_assignment(request, assignment_id):
    """Add client as sub-activity to assignment."""
    if request.method != "POST":
        return redirect("core:manage_assignment_clients", assignment_id=assignment_id)

    assignment = get_object_or_404(Assignment, pk=assignment_id)
    client_id = int(request.POST.get("client_id", 0))
    client = get_object_or_404(Client, pk=client_id)

    count = AssignmentClient.objects.filter(assignment=assignment).count()
    sub_num = f"{assignment.assignment_no}/SUB-{count + 1:02d}"

    billing_share = float(request.POST.get("billing_share_percent", 100))
    description = request.POST.get("description", "").strip()
    is_primary = bool(int(request.POST.get("is_primary", 0)))

    AssignmentClient.objects.get_or_create(
        assignment=assignment,
        client=client,
        defaults={
            "sub_activity_number": sub_num,
            "billing_share_percent": billing_share,
            "description": description,
            "is_primary": is_primary,
        },
    )
    return redirect("core:manage_assignment_clients", assignment_id=assignment_id)


@login_required
def remove_client_from_assignment(request, assignment_id, link_id):
    """Remove client-assignment link."""
    if request.method != "POST":
        return redirect("core:manage_assignment_clients", assignment_id=assignment_id)

    AssignmentClient.objects.filter(pk=link_id, assignment_id=assignment_id).delete()
    return redirect("core:manage_assignment_clients", assignment_id=assignment_id)


@login_required
def client_mis(request):
    """Client MIS dashboard."""
    client_type = request.GET.get("client_type")

    qs = Client.objects.filter(is_active=True)
    if client_type:
        qs = qs.filter(client_type=client_type)

    client_data = qs.annotate(
        assignment_count=Count("assignment_links__assignment", distinct=True),
        total_value=Sum(
            F("assignment_links__assignment__total_value")
            * F("assignment_links__billing_share_percent") / 100
        ),
        total_invoiced=Sum(
            F("assignment_links__assignment__invoice_amount")
            * F("assignment_links__billing_share_percent") / 100
        ),
        total_received=Sum(
            F("assignment_links__assignment__amount_received")
            * F("assignment_links__billing_share_percent") / 100
        ),
    ).order_by("-total_value")

    totals = client_data.aggregate(
        total_clients=Count("id"),
        grand_total_value=Sum("total_value"),
        grand_total_invoiced=Sum("total_invoiced"),
        grand_total_received=Sum("total_received"),
    )

    return render(request, "clients/mis.html", {
        "client_data": client_data,
        "totals": totals,
        "filter_type": client_type,
        "client_types": settings.CLIENT_TYPE_OPTIONS,
    })


@login_required
def search_clients_api(request):
    """JSON autocomplete search for client names."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse([], safe=False)

    results = Client.objects.filter(
        Q(client_name__icontains=q) | Q(client_code__icontains=q),
        is_active=True,
    ).values("id", "client_code", "client_name", "client_type")[:20]
    return JsonResponse(list(results), safe=False)
