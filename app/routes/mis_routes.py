"""
MIS Analytics routes: office-wise, domain-wise, and officer-wise revenue analytics.
Includes target vs achievement comparison and physical progress tracking.
"""
from typing import Optional
from datetime import datetime, date
from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse

from app.database import get_db
from app.dependencies import get_current_user
from app.templates_config import templates

router = APIRouter()


def get_financial_years():
    """Generate list of financial years for filter dropdown."""
    current_year = datetime.now().year
    years = []
    for y in range(current_year - 5, current_year + 2):
        years.append(f"{y}-{str(y+1)[-2:]}")
    return years


def parse_financial_year(fy_str: str):
    """Parse financial year string to start and end dates."""
    if not fy_str or '-' not in fy_str:
        return None, None
    try:
        start_year = int(fy_str.split('-')[0])
        return date(start_year, 4, 1), date(start_year + 1, 3, 31)
    except:
        return None, None


def calculate_fy_progress():
    """Calculate how much of the financial year has elapsed."""
    today = date.today()
    if today.month >= 4:
        fy_start = date(today.year, 4, 1)
    else:
        fy_start = date(today.year - 1, 4, 1)
    fy_end = date(fy_start.year + 1, 3, 31)

    total_days = (fy_end - fy_start).days
    elapsed_days = (today - fy_start).days
    return min(elapsed_days / total_days, 1.0)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def mis_dashboard(
    request: Request,
    financial_year: Optional[str] = Query(None),
    filter_office: Optional[str] = Query(None),
    filter_domain: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_order: Optional[str] = Query("desc")
):
    """Display MIS Analytics dashboard with target vs achievement comparison."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Default to current FY if not specified
    if not financial_year:
        today = date.today()
        if today.month >= 4:
            financial_year = f"{today.year}-{str(today.year + 1)[-2:]}"
        else:
            financial_year = f"{today.year - 1}-{str(today.year)[-2:]}"

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()

        # Build base filter conditions
        base_conditions = "WHERE 1=1"
        params = []

        fy_start, fy_end = parse_financial_year(financial_year)
        if fy_start and fy_end:
            base_conditions += " AND (a.start_date BETWEEN ? AND ? OR a.work_order_date BETWEEN ? AND ?)"
            params.extend([fy_start.isoformat(), fy_end.isoformat(), fy_start.isoformat(), fy_end.isoformat()])

        if date_from:
            base_conditions += " AND (a.start_date >= ? OR a.work_order_date >= ?)"
            params.extend([date_from, date_from])

        if date_to:
            base_conditions += " AND (a.start_date <= ? OR a.work_order_date <= ?)"
            params.extend([date_to, date_to])

        if filter_office:
            base_conditions += " AND a.office_id = ?"
            params.append(filter_office)

        if filter_domain:
            base_conditions += " AND a.domain = ?"
            params.append(filter_domain)

        # 1. Office-wise Target vs Achievement
        office_query = f"""
            SELECT
                a.office_id,
                o.office_name,
                o.officer_count,
                o.annual_revenue_target,
                COALESCE(fyt.annual_target, o.annual_revenue_target) as target,
                COALESCE(fyt.training_target, 0) as training_target,
                COALESCE(fyt.lecture_target, 0) as lecture_target,
                COUNT(*) as assignment_count,
                SUM(COALESCE(a.total_revenue, 0)) as total_revenue,
                SUM(COALESCE(a.amount_received, 0)) as deposits,
                SUM(COALESCE(a.total_expenditure, 0)) as total_expenditure,
                SUM(COALESCE(a.surplus_deficit, 0)) as surplus_deficit,
                SUM(CASE WHEN a.type = 'ASSIGNMENT' THEN 1 ELSE 0 END) as project_count,
                SUM(CASE WHEN a.type = 'TRAINING' THEN 1 ELSE 0 END) as training_count,
                AVG(COALESCE(a.physical_progress_percent, 0)) as avg_physical_progress
            FROM assignments a
            LEFT JOIN offices o ON a.office_id = o.office_id
            LEFT JOIN financial_year_targets fyt ON a.office_id = fyt.office_id
                AND fyt.financial_year = ?
            {base_conditions}
            GROUP BY a.office_id, o.office_name, o.officer_count, o.annual_revenue_target,
                     fyt.annual_target, fyt.training_target, fyt.lecture_target
            ORDER BY total_revenue DESC
        """
        cursor.execute(office_query, [financial_year] + params)
        office_data = [dict(row) for row in cursor.fetchall()]

        # Calculate achievement percentages and pro-rata targets
        for o in office_data:
            target = o['target'] or 0
            o['prorata_target'] = round(target * fy_progress, 2)
            o['achievement_pct'] = round((o['total_revenue'] / target * 100), 1) if target > 0 else 0
            o['prorata_achievement_pct'] = round((o['total_revenue'] / o['prorata_target'] * 100), 1) if o['prorata_target'] > 0 else 0
            o['surplus_deficit_pct'] = round((o['surplus_deficit'] / o['total_revenue'] * 100), 1) if o['total_revenue'] > 0 else 0

        # Mark top 3 and bottom 3 offices by achievement %
        sorted_by_achievement = sorted([o for o in office_data if o['achievement_pct'] > 0],
                                       key=lambda x: x['achievement_pct'], reverse=True)
        top_3_offices = set(o['office_id'] for o in sorted_by_achievement[:3])
        bottom_3_offices = set(o['office_id'] for o in sorted_by_achievement[-3:] if len(sorted_by_achievement) > 3)

        for o in office_data:
            o['is_top'] = o['office_id'] in top_3_offices
            o['is_bottom'] = o['office_id'] in bottom_3_offices and o['office_id'] not in top_3_offices

        # 2. Domain-wise revenue aggregation
        domain_query = f"""
            SELECT
                COALESCE(a.domain, 'Unspecified') as domain,
                COUNT(*) as assignment_count,
                SUM(COALESCE(a.total_revenue, 0)) as total_revenue,
                SUM(COALESCE(a.total_expenditure, 0)) as total_expenditure,
                SUM(COALESCE(a.surplus_deficit, 0)) as surplus_deficit,
                AVG(COALESCE(a.physical_progress_percent, 0)) as avg_physical_progress
            FROM assignments a
            {base_conditions}
            GROUP BY COALESCE(a.domain, 'Unspecified')
            ORDER BY total_revenue DESC
        """
        cursor.execute(domain_query, params)
        domain_data = [dict(row) for row in cursor.fetchall()]

        # 3. Officer-wise Target vs Achievement
        officer_conditions = "WHERE 1=1"
        officer_params = []

        if fy_start and fy_end:
            officer_conditions += " AND (a.start_date BETWEEN ? AND ? OR a.work_order_date BETWEEN ? AND ?)"
            officer_params.extend([fy_start.isoformat(), fy_end.isoformat(), fy_start.isoformat(), fy_end.isoformat()])

        if date_from:
            officer_conditions += " AND (a.start_date >= ? OR a.work_order_date >= ?)"
            officer_params.extend([date_from, date_from])

        if date_to:
            officer_conditions += " AND (a.start_date <= ? OR a.work_order_date <= ?)"
            officer_params.extend([date_to, date_to])

        if filter_office:
            officer_conditions += " AND off.office_id = ?"
            officer_params.append(filter_office)

        # Show ALL active officers, not just those with revenue shares
        officer_query = f"""
            SELECT
                off.officer_id,
                off.name,
                off.office_id,
                off.designation,
                off.annual_target,
                COALESCE(revenue_data.assignment_count, 0) as assignment_count,
                COALESCE(revenue_data.total_share_amount, 0) as total_share_amount,
                COALESCE(revenue_data.avg_share_percent, 0) as avg_share_percent
            FROM officers off
            LEFT JOIN (
                SELECT
                    rs.officer_id,
                    COUNT(DISTINCT rs.assignment_id) as assignment_count,
                    SUM(rs.share_amount) as total_share_amount,
                    AVG(rs.share_percent) as avg_share_percent
                FROM revenue_shares rs
                JOIN assignments a ON rs.assignment_id = a.id
                {officer_conditions}
                GROUP BY rs.officer_id
            ) revenue_data ON off.officer_id = revenue_data.officer_id
            WHERE off.is_active = 1
            {"AND off.office_id = ?" if filter_office else ""}
            ORDER BY total_share_amount DESC
        """
        # Add filter_office to params if specified
        query_params = officer_params + ([filter_office] if filter_office else [])
        cursor.execute(officer_query, query_params)
        officer_data = [dict(row) for row in cursor.fetchall()]

        # Calculate officer achievement percentages
        for o in officer_data:
            target = o['annual_target'] or 60.0
            o['prorata_target'] = round(target * fy_progress, 2)
            o['achievement_pct'] = round((o['total_share_amount'] / target * 100), 1) if target > 0 else 0
            o['prorata_achievement_pct'] = round((o['total_share_amount'] / o['prorata_target'] * 100), 1) if o['prorata_target'] > 0 else 0

        # Mark top 10 and bottom 10 officers
        top_10_officers = set(o['officer_id'] for o in officer_data[:10])
        bottom_10_officers = set(o['officer_id'] for o in officer_data[-10:] if len(officer_data) > 10)

        for o in officer_data:
            o['is_top'] = o['officer_id'] in top_10_officers
            o['is_bottom'] = o['officer_id'] in bottom_10_officers and o['officer_id'] not in top_10_officers

        # 4. Physical Progress Summary
        progress_query = f"""
            SELECT
                a.status,
                COUNT(*) as count,
                AVG(COALESCE(a.physical_progress_percent, 0)) as avg_progress,
                SUM(COALESCE(a.total_revenue, 0)) as total_revenue
            FROM assignments a
            {base_conditions}
            GROUP BY a.status
            ORDER BY count DESC
        """
        cursor.execute(progress_query, params)
        progress_by_status = [dict(row) for row in cursor.fetchall()]

        # Get filter options
        cursor.execute("SELECT office_id, office_name FROM offices ORDER BY office_id")
        offices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT domain FROM assignments WHERE domain IS NOT NULL ORDER BY domain")
        domains = [row['domain'] for row in cursor.fetchall()]

        # Calculate totals
        total_target = sum(o['target'] or 0 for o in office_data)
        total_revenue = sum(o['total_revenue'] or 0 for o in office_data)
        total_expenditure = sum(o['total_expenditure'] or 0 for o in office_data)
        total_officers = sum(o['officer_count'] or 0 for o in office_data)
        prorata_target = round(total_target * fy_progress, 2)
        avg_physical_progress = sum(o['avg_physical_progress'] or 0 for o in office_data) / len(office_data) if office_data else 0

        totals = {
            'total_assignments': sum(o['assignment_count'] for o in office_data),
            'total_target': total_target,
            'prorata_target': prorata_target,
            'total_revenue': total_revenue,
            'total_expenditure': total_expenditure,
            'surplus_deficit': total_revenue - total_expenditure,
            'achievement_pct': round((total_revenue / prorata_target * 100), 1) if prorata_target > 0 else 0,
            'overall_achievement_pct': round((total_revenue / total_target * 100), 1) if total_target > 0 else 0,
            'total_offices': len(office_data),
            'total_officers': total_officers,
            'total_domains': len(domain_data),
            'total_officers_with_share': len(officer_data),
            'avg_physical_progress': round(avg_physical_progress, 1),
            'fy_progress_pct': round(fy_progress * 100, 1)
        }

        # Apply sorting to office data
        if sort_by == 'revenue':
            office_data = sorted(office_data, key=lambda x: x['total_revenue'] or 0,
                               reverse=(sort_order == 'desc'))
        elif sort_by == 'timeline':
            office_data = sorted(office_data, key=lambda x: x['avg_physical_progress'] or 0,
                               reverse=(sort_order == 'desc'))
        elif sort_by == 'achievement':
            office_data = sorted(office_data, key=lambda x: x['achievement_pct'] or 0,
                               reverse=(sort_order == 'desc'))

    return templates.TemplateResponse(
        "mis_dashboard.html",
        {
            "request": request,
            "user": user,
            "office_data": office_data,
            "domain_data": domain_data,
            "officer_data": officer_data,
            "progress_by_status": progress_by_status,
            "offices": offices,
            "domains": domains,
            "financial_years": get_financial_years(),
            "filter_office": filter_office,
            "filter_domain": filter_domain,
            "financial_year": financial_year,
            "date_from": date_from,
            "date_to": date_to,
            "totals": totals,
            "fy_progress": fy_progress,
            "sort_by": sort_by,
            "sort_order": sort_order
        }
    )


@router.get("/office/{office_id}", response_class=HTMLResponse)
async def office_detail(request: Request, office_id: str):
    """Detailed view for a specific office with target vs achievement."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()

        # Get office info with target
        cursor.execute("""
            SELECT o.*, fyt.annual_target as fy_target, fyt.training_target, fyt.lecture_target
            FROM offices o
            LEFT JOIN financial_year_targets fyt ON o.office_id = fyt.office_id
                AND fyt.financial_year = ?
            WHERE o.office_id = ?
        """, (f"{date.today().year}-{str(date.today().year + 1)[-2:]}" if date.today().month >= 4
              else f"{date.today().year - 1}-{str(date.today().year)[-2:]}", office_id))
        office = cursor.fetchone()
        if not office:
            return RedirectResponse(url="/mis", status_code=302)
        office = dict(office)

        # Get assignments for this office with milestones count
        cursor.execute("""
            SELECT
                a.*,
                (SELECT COUNT(*) FROM revenue_shares rs WHERE rs.assignment_id = a.id) as share_count,
                (SELECT COUNT(*) FROM milestones m WHERE m.assignment_id = a.id) as milestone_count,
                (SELECT COUNT(*) FROM milestones m WHERE m.assignment_id = a.id AND m.status = 'Completed') as completed_milestones
            FROM assignments a
            WHERE a.office_id = ?
            ORDER BY a.start_date DESC
        """, (office_id,))
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get ALL officers in this office with their targets and achievements
        cursor.execute("""
            SELECT
                o.*,
                COALESCE(SUM(rs.share_amount), 0) as total_share,
                COUNT(DISTINCT rs.assignment_id) as assignment_count
            FROM officers o
            LEFT JOIN revenue_shares rs ON o.officer_id = rs.officer_id
            WHERE o.office_id = ? AND o.is_active = 1
            GROUP BY o.officer_id
            ORDER BY total_share DESC
        """, (office_id,))
        officers = [dict(row) for row in cursor.fetchall()]

        # Calculate achievement for each officer
        for o in officers:
            target = o.get('annual_target', 60.0) or 60.0
            o['prorata_target'] = round(target * fy_progress, 2)
            o['achievement_pct'] = round((o['total_share'] / target * 100), 1) if target > 0 else 0

        # Get status breakdown for this office
        cursor.execute("""
            SELECT
                status,
                COUNT(*) as count,
                AVG(COALESCE(physical_progress_percent, 0)) as avg_progress
            FROM assignments
            WHERE office_id = ?
            GROUP BY status
            ORDER BY count DESC
        """, (office_id,))
        status_breakdown = [dict(row) for row in cursor.fetchall()]

        # Summary stats with target comparison
        target = office.get('fy_target') or office.get('annual_revenue_target') or 0
        total_revenue = sum(a['total_revenue'] or 0 for a in assignments)
        total_expenditure = sum(a['total_expenditure'] or 0 for a in assignments)
        prorata_target = round(target * fy_progress, 2)
        avg_progress = sum(a['physical_progress_percent'] or 0 for a in assignments) / len(assignments) if assignments else 0

        summary = {
            'total_assignments': len(assignments),
            'total_revenue': total_revenue,
            'total_expenditure': total_expenditure,
            'surplus_deficit': total_revenue - total_expenditure,
            'officer_count': office.get('officer_count', len(officers)),
            'annual_target': target,
            'prorata_target': prorata_target,
            'achievement_pct': round((total_revenue / prorata_target * 100), 1) if prorata_target > 0 else 0,
            'avg_progress': round(avg_progress, 1)
        }

    return templates.TemplateResponse(
        "office_detail.html",
        {
            "request": request,
            "user": user,
            "office": office,
            "assignments": assignments,
            "officers": officers,
            "summary": summary,
            "status_breakdown": status_breakdown,
            "fy_progress": fy_progress
        }
    )


@router.get("/officer/{officer_id}", response_class=HTMLResponse)
async def officer_detail(request: Request, officer_id: str):
    """Detailed view for a specific officer's revenue shares with target comparison."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    fy_progress = calculate_fy_progress()

    with get_db() as conn:
        cursor = conn.cursor()

        # Get officer info
        cursor.execute("SELECT * FROM officers WHERE officer_id = ?", (officer_id,))
        officer = cursor.fetchone()
        if not officer:
            return RedirectResponse(url="/mis", status_code=302)
        officer = dict(officer)

        # Get revenue shares for this officer with assignment details
        cursor.execute("""
            SELECT
                rs.*,
                a.assignment_no,
                a.title,
                a.type,
                a.office_id,
                a.total_revenue,
                a.gross_value,
                a.status,
                a.physical_progress_percent,
                a.start_date,
                a.target_date
            FROM revenue_shares rs
            JOIN assignments a ON rs.assignment_id = a.id
            WHERE rs.officer_id = ?
            ORDER BY rs.share_amount DESC
        """, (officer_id,))
        shares = [dict(row) for row in cursor.fetchall()]

        # Summary stats with target comparison
        target = officer.get('annual_target', 60.0) or 60.0
        total_share = sum(s['share_amount'] or 0 for s in shares)

        summary = {
            'total_assignments': len(shares),
            'total_share_amount': total_share,
            'avg_share_percent': sum(s['share_percent'] or 0 for s in shares) / len(shares) if shares else 0,
            'annual_target': target,
            'prorata_target': round(target * fy_progress, 2),
            'achievement_pct': round((total_share / target * 100), 1) if target > 0 else 0,
            'prorata_achievement_pct': round((total_share / (target * fy_progress) * 100), 1) if target * fy_progress > 0 else 0
        }

    return templates.TemplateResponse(
        "officer_detail.html",
        {
            "request": request,
            "user": user,
            "officer": officer,
            "shares": shares,
            "summary": summary,
            "fy_progress": fy_progress
        }
    )


@router.get("/assignment/{assignment_id}/progress", response_class=HTMLResponse)
async def assignment_progress(request: Request, assignment_id: int):
    """View milestones and progress for a specific assignment."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get assignment details
        cursor.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment:
            return RedirectResponse(url="/mis", status_code=302)
        assignment = dict(assignment)

        # Get milestones
        cursor.execute("""
            SELECT * FROM milestones
            WHERE assignment_id = ?
            ORDER BY milestone_no
        """, (assignment_id,))
        milestones = [dict(row) for row in cursor.fetchall()]

        # Get expenditure items
        cursor.execute("""
            SELECT ei.*, eh.category, eh.head_code, eh.head_name
            FROM expenditure_items ei
            JOIN expenditure_heads eh ON ei.head_id = eh.id
            WHERE ei.assignment_id = ?
            ORDER BY eh.category, eh.head_code
        """, (assignment_id,))
        expenditure_items = [dict(row) for row in cursor.fetchall()]

        # Group expenditure by category
        expenditure_by_category = {}
        for item in expenditure_items:
            cat = item['category']
            if cat not in expenditure_by_category:
                expenditure_by_category[cat] = {'items': [], 'estimated_total': 0, 'actual_total': 0}
            expenditure_by_category[cat]['items'].append(item)
            expenditure_by_category[cat]['estimated_total'] += item['estimated_amount'] or 0
            expenditure_by_category[cat]['actual_total'] += item['actual_amount'] or 0

        # Calculate summary
        completed_milestones = [m for m in milestones if m['status'] == 'Completed']
        summary = {
            'total_milestones': len(milestones),
            'completed_milestones': len(completed_milestones),
            'physical_progress': sum(m['revenue_percent'] for m in completed_milestones),
            'total_estimated_expenditure': sum(e['estimated_amount'] or 0 for e in expenditure_items),
            'total_actual_expenditure': sum(e['actual_amount'] or 0 for e in expenditure_items),
        }

    return templates.TemplateResponse(
        "assignment_progress.html",
        {
            "request": request,
            "user": user,
            "assignment": assignment,
            "milestones": milestones,
            "expenditure_by_category": expenditure_by_category,
            "summary": summary
        }
    )


@router.get("/assignments", response_class=HTMLResponse)
async def assignments_list(
    request: Request,
    filter_office: Optional[str] = Query(None),
    filter_domain: Optional[str] = Query(None),
    filter_status: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("revenue"),
    sort_order: Optional[str] = Query("desc")
):
    """List all assignments with sorting by revenue and timeline progress."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        cursor = conn.cursor()

        # Build query with filters
        conditions = "WHERE 1=1"
        params = []

        if filter_office:
            conditions += " AND a.office_id = ?"
            params.append(filter_office)

        if filter_domain:
            conditions += " AND a.domain = ?"
            params.append(filter_domain)

        if filter_status:
            conditions += " AND a.status = ?"
            params.append(filter_status)

        # Determine sort column
        sort_column = "a.total_revenue"
        if sort_by == "timeline":
            sort_column = "a.timeline_progress_percent"
        elif sort_by == "physical":
            sort_column = "a.physical_progress_percent"
        elif sort_by == "value":
            sort_column = "a.total_value"

        order = "DESC" if sort_order == "desc" else "ASC"

        query = f"""
            SELECT
                a.*,
                o.office_name,
                (SELECT COUNT(*) FROM milestones WHERE assignment_id = a.id) as milestone_count,
                (SELECT COUNT(*) FROM milestones WHERE assignment_id = a.id AND payment_received = 1) as paid_milestones,
                (SELECT COUNT(*) FROM milestones WHERE assignment_id = a.id AND invoice_raised = 1) as invoiced_milestones
            FROM assignments a
            LEFT JOIN offices o ON a.office_id = o.office_id
            {conditions}
            ORDER BY {sort_column} {order}
        """

        cursor.execute(query, params)
        assignments = [dict(row) for row in cursor.fetchall()]

        # Get filter options
        cursor.execute("SELECT office_id FROM offices ORDER BY office_id")
        offices = [row['office_id'] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT domain FROM assignments WHERE domain IS NOT NULL ORDER BY domain")
        domains = [row['domain'] for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT status FROM assignments WHERE status IS NOT NULL ORDER BY status")
        statuses = [row['status'] for row in cursor.fetchall()]

    return templates.TemplateResponse(
        "assignments_list.html",
        {
            "request": request,
            "user": user,
            "assignments": assignments,
            "offices": offices,
            "domains": domains,
            "statuses": statuses,
            "filter_office": filter_office,
            "filter_domain": filter_domain,
            "filter_status": filter_status,
            "sort_by": sort_by,
            "sort_order": sort_order
        }
    )
