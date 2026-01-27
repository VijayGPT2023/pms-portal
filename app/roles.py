"""
Role-based access control for PMS Portal.

Role Hierarchy:
1. ADMIN - System administrator (full access)
2. DG - Director General (view all, approve escalated matters)
3. DDG_I / DDG_II - Deputy Director General (view all, approve escalated)
4. RD_HEAD - Regional Director Head (manage office assignments)
5. GROUP_HEAD - Group Head (manage group assignments)
6. TEAM_LEADER - Team Leader (manage assigned projects)
7. OFFICER - Regular Officer (view, register new assignments)
"""

# Role Constants
ROLE_ADMIN = 'ADMIN'
ROLE_DG = 'DG'
ROLE_DDG_I = 'DDG-I'
ROLE_DDG_II = 'DDG-II'
ROLE_RD_HEAD = 'RD_HEAD'
ROLE_GROUP_HEAD = 'GROUP_HEAD'
ROLE_TEAM_LEADER = 'TEAM_LEADER'
ROLE_OFFICER = 'OFFICER'

# All roles in hierarchy order (highest to lowest)
ALL_ROLES = [
    ROLE_ADMIN,
    ROLE_DG,
    ROLE_DDG_I,
    ROLE_DDG_II,
    ROLE_RD_HEAD,
    ROLE_GROUP_HEAD,
    ROLE_TEAM_LEADER,
    ROLE_OFFICER
]

# Role display names
ROLE_NAMES = {
    ROLE_ADMIN: 'System Administrator',
    ROLE_DG: 'Director General',
    ROLE_DDG_I: 'Deputy Director General - I',
    ROLE_DDG_II: 'Deputy Director General - II',
    ROLE_RD_HEAD: 'Regional Director / Head',
    ROLE_GROUP_HEAD: 'Group Head',
    ROLE_TEAM_LEADER: 'Team Leader',
    ROLE_OFFICER: 'Officer'
}

# Permissions
PERM_VIEW_ALL_MIS = 'view_all_mis'
PERM_VIEW_OFFICE_MIS = 'view_office_mis'
PERM_EXPORT_DATA = 'export_data'
PERM_IMPORT_DATA = 'import_data'
PERM_MANAGE_CONFIG = 'manage_config'
PERM_MANAGE_USERS = 'manage_users'
PERM_RESET_PASSWORD = 'reset_password'
PERM_CHANGE_ROLES = 'change_roles'
PERM_APPROVE_ESCALATED = 'approve_escalated'
PERM_ALLOCATE_TEAM_LEADER = 'allocate_team_leader'
PERM_APPROVE_ASSIGNMENT = 'approve_assignment'
PERM_APPROVE_MILESTONE = 'approve_milestone'
PERM_APPROVE_REVENUE_SHARE = 'approve_revenue_share'
PERM_SET_TEAM = 'set_team'
PERM_FILL_ASSIGNMENT_DETAILS = 'fill_assignment_details'
PERM_FILL_MILESTONE_DETAILS = 'fill_milestone_details'
PERM_REGISTER_ASSIGNMENT = 'register_assignment'
PERM_RAISE_REQUEST = 'raise_request'
PERM_DOWNLOAD_REPORTS = 'download_reports'

# Role-Permission Mapping
ROLE_PERMISSIONS = {
    ROLE_ADMIN: [
        PERM_VIEW_ALL_MIS,
        PERM_EXPORT_DATA,
        PERM_IMPORT_DATA,
        PERM_MANAGE_CONFIG,
        PERM_MANAGE_USERS,
        PERM_RESET_PASSWORD,
        PERM_CHANGE_ROLES,
        PERM_DOWNLOAD_REPORTS,
    ],
    ROLE_DG: [
        PERM_VIEW_ALL_MIS,
        PERM_APPROVE_ESCALATED,
        PERM_DOWNLOAD_REPORTS,
    ],
    ROLE_DDG_I: [
        PERM_VIEW_ALL_MIS,
        PERM_APPROVE_ESCALATED,
        PERM_DOWNLOAD_REPORTS,
    ],
    ROLE_DDG_II: [
        PERM_VIEW_ALL_MIS,
        PERM_APPROVE_ESCALATED,
        PERM_DOWNLOAD_REPORTS,
    ],
    ROLE_RD_HEAD: [
        PERM_VIEW_ALL_MIS,
        PERM_ALLOCATE_TEAM_LEADER,
        PERM_APPROVE_ASSIGNMENT,
        PERM_APPROVE_MILESTONE,
        PERM_APPROVE_REVENUE_SHARE,
        PERM_DOWNLOAD_REPORTS,
    ],
    ROLE_GROUP_HEAD: [
        PERM_VIEW_ALL_MIS,
        PERM_ALLOCATE_TEAM_LEADER,
        PERM_APPROVE_ASSIGNMENT,
        PERM_APPROVE_MILESTONE,
        PERM_APPROVE_REVENUE_SHARE,
        PERM_DOWNLOAD_REPORTS,
    ],
    ROLE_TEAM_LEADER: [
        PERM_VIEW_ALL_MIS,
        PERM_SET_TEAM,
        PERM_FILL_ASSIGNMENT_DETAILS,
        PERM_FILL_MILESTONE_DETAILS,
        PERM_DOWNLOAD_REPORTS,
    ],
    ROLE_OFFICER: [
        PERM_VIEW_ALL_MIS,
        PERM_REGISTER_ASSIGNMENT,
        PERM_RAISE_REQUEST,
    ],
}


def get_user_roles(user: dict) -> list:
    """
    Get all roles of a user from officer_roles table, assignments, and add Individual view.
    Returns list of role dicts with role_type and scope info, sorted by hierarchy.
    """
    if not user:
        return []

    officer_id = user.get('officer_id')
    if not officer_id:
        return []

    from app.database import get_db, USE_POSTGRES

    roles_list = []
    seen_roles = set()  # Track unique roles

    with get_db() as conn:
        cursor = conn.cursor()

        # Get roles from officer_roles table
        if USE_POSTGRES:
            cursor.execute("""
                SELECT role_type, scope_type, scope_value, is_primary
                FROM officer_roles
                WHERE officer_id = %s
                AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
                ORDER BY is_primary DESC, role_type
            """, (officer_id,))
        else:
            cursor.execute("""
                SELECT role_type, scope_type, scope_value, is_primary
                FROM officer_roles
                WHERE officer_id = ?
                AND (effective_to IS NULL OR effective_to >= DATE('now'))
                ORDER BY is_primary DESC, role_type
            """, (officer_id,))

        for row in cursor.fetchall():
            role_key = f"{row['role_type']}:{row['scope_value'] or ''}"
            if role_key not in seen_roles:
                seen_roles.add(role_key)
                roles_list.append({
                    'role_type': row['role_type'],
                    'scope_type': row['scope_type'],
                    'scope_value': row['scope_value'],
                    'is_primary': row['is_primary']
                })

        # Check if user is team leader of any active assignment
        # Status values: 'Not Started', 'In Progress', 'Completed', 'Delayed', 'Cancelled'
        if USE_POSTGRES:
            cursor.execute("""
                SELECT COUNT(*) as tl_count FROM assignments
                WHERE team_leader_officer_id = %s
                AND status IN ('Not Started', 'In Progress', 'Delayed')
            """, (officer_id,))
        else:
            cursor.execute("""
                SELECT COUNT(*) as tl_count FROM assignments
                WHERE team_leader_officer_id = ?
                AND status IN ('Not Started', 'In Progress', 'Delayed')
            """, (officer_id,))
        tl_result = cursor.fetchone()

        if tl_result and tl_result['tl_count'] > 0:
            tl_key = f"{ROLE_TEAM_LEADER}:"
            if tl_key not in seen_roles:
                seen_roles.add(tl_key)
                roles_list.append({
                    'role_type': ROLE_TEAM_LEADER,
                    'scope_type': 'ASSIGNMENT',
                    'scope_value': None,
                    'is_primary': 0
                })

    # Also check legacy admin_role_id field
    admin_role = user.get('admin_role_id', '')
    if admin_role and admin_role != ROLE_OFFICER:
        role_key = f"{admin_role}:"
        if role_key not in seen_roles:
            seen_roles.add(role_key)
            roles_list.append({
                'role_type': admin_role,
                'scope_type': 'GLOBAL',
                'scope_value': None,
                'is_primary': 1 if not roles_list else 0
            })

    # Always add OFFICER (Individual) role as the last option
    roles_list.append({
        'role_type': ROLE_OFFICER,
        'scope_type': 'INDIVIDUAL',
        'scope_value': None,
        'is_primary': 1 if not roles_list else 0
    })

    # Sort by role hierarchy (highest first)
    def role_sort_key(r):
        try:
            return ALL_ROLES.index(r['role_type'])
        except ValueError:
            return 999

    roles_list.sort(key=role_sort_key)

    # Mark the first (highest) role as primary if none is marked
    if roles_list and not any(r['is_primary'] for r in roles_list):
        roles_list[0]['is_primary'] = 1

    return roles_list


def get_user_role(user: dict) -> str:
    """Get the primary/highest role of a user for display purposes."""
    if not user:
        return None

    # Check legacy admin_role_id first for backward compatibility
    admin_role = user.get('admin_role_id', '')

    # Check for specific roles
    if admin_role == ROLE_ADMIN:
        return ROLE_ADMIN
    if admin_role in [ROLE_DG, 'DG']:
        return ROLE_DG
    if admin_role in [ROLE_DDG_I, 'DDG-I', 'DDG1']:
        return ROLE_DDG_I
    if admin_role in [ROLE_DDG_II, 'DDG-II', 'DDG2']:
        return ROLE_DDG_II
    if admin_role in [ROLE_RD_HEAD, 'RD_HEAD', 'RD HEAD']:
        return ROLE_RD_HEAD
    if admin_role in [ROLE_GROUP_HEAD, 'GROUP_HEAD', 'GROUP HEAD']:
        return ROLE_GROUP_HEAD
    if admin_role in [ROLE_TEAM_LEADER, 'TEAM_LEADER', 'TL']:
        return ROLE_TEAM_LEADER

    # Check officer_roles table
    roles = get_user_roles(user)
    if roles:
        # Return highest role based on hierarchy
        for role in ALL_ROLES:
            if any(r['role_type'] == role for r in roles):
                return role

    # Default role for all officers
    return ROLE_OFFICER


def get_user_role_display(user: dict) -> str:
    """Get display string for all user roles."""
    if not user:
        return "Unknown"

    roles = get_user_roles(user)
    if not roles:
        admin_role = user.get('admin_role_id', '')
        if admin_role:
            return ROLE_NAMES.get(admin_role, admin_role)
        return "Officer"

    display_parts = []
    for r in roles:
        role_name = ROLE_NAMES.get(r['role_type'], r['role_type'])
        if r['scope_value']:
            display_parts.append(f"{role_name} ({r['scope_value']})")
        else:
            display_parts.append(role_name)

    return ", ".join(display_parts)


def has_permission(user: dict, permission: str) -> bool:
    """Check if user has a specific permission."""
    if not user:
        return False

    role = get_user_role(user)
    if not role:
        return False

    permissions = ROLE_PERMISSIONS.get(role, [])
    return permission in permissions


def has_any_permission(user: dict, permissions: list) -> bool:
    """Check if user has any of the given permissions."""
    return any(has_permission(user, perm) for perm in permissions)


def has_all_permissions(user: dict, permissions: list) -> bool:
    """Check if user has all of the given permissions."""
    return all(has_permission(user, perm) for perm in permissions)


def is_admin(user: dict) -> bool:
    """Check if user is admin."""
    return get_user_role(user) == ROLE_ADMIN


def is_head(user: dict) -> bool:
    """Check if user is a head (RD Head or Group Head)."""
    role = get_user_role(user)
    return role in [ROLE_RD_HEAD, ROLE_GROUP_HEAD]


def is_senior_management(user: dict) -> bool:
    """Check if user is DG/DDG level."""
    role = get_user_role(user)
    return role in [ROLE_DG, ROLE_DDG_I, ROLE_DDG_II]


def is_team_leader(user: dict) -> bool:
    """Check if user is a team leader."""
    return get_user_role(user) == ROLE_TEAM_LEADER


def can_approve_in_office(user: dict, office_id: str) -> bool:
    """Check if user can approve items in a specific office."""
    if not user:
        return False

    role = get_user_role(user)

    # Admin, DG, DDG can approve anywhere
    if role in [ROLE_ADMIN, ROLE_DG, ROLE_DDG_I, ROLE_DDG_II]:
        return True

    # RD/Group Head can approve in their own office
    if role in [ROLE_RD_HEAD, ROLE_GROUP_HEAD]:
        return user.get('office_id') == office_id

    return False


def get_role_display_name(role: str) -> str:
    """Get display name for a role."""
    return ROLE_NAMES.get(role, role)


def get_user_permissions(user: dict) -> list:
    """Get all permissions for a user based on all their roles."""
    # Get permissions from all roles
    all_permissions = set()

    roles = get_user_roles(user)
    for r in roles:
        role_perms = ROLE_PERMISSIONS.get(r['role_type'], [])
        all_permissions.update(role_perms)

    # Also check primary role
    primary_role = get_user_role(user)
    primary_perms = ROLE_PERMISSIONS.get(primary_role, [])
    all_permissions.update(primary_perms)

    return list(all_permissions)


def is_group_head_for(user: dict, group_code: str) -> bool:
    """Check if user is Group Head for a specific group."""
    if not user:
        return False

    roles = get_user_roles(user)
    for r in roles:
        if r['role_type'] == ROLE_GROUP_HEAD and r['scope_value'] == group_code:
            return True
    return False


def is_rd_head_for(user: dict, office_id: str) -> bool:
    """Check if user is RD Head for a specific office."""
    if not user:
        return False

    roles = get_user_roles(user)
    for r in roles:
        if r['role_type'] == ROLE_RD_HEAD and r['scope_value'] == office_id:
            return True
    return False


def get_user_groups(user: dict) -> list:
    """Get list of groups the user is head of."""
    if not user:
        return []

    roles = get_user_roles(user)
    groups = []
    for r in roles:
        if r['role_type'] == ROLE_GROUP_HEAD and r['scope_value']:
            groups.append(r['scope_value'])
    return groups


def get_user_offices(user: dict) -> list:
    """Get list of offices the user is RD head of."""
    if not user:
        return []

    roles = get_user_roles(user)
    offices = []
    for r in roles:
        if r['role_type'] == ROLE_RD_HEAD and r['scope_value']:
            offices.append(r['scope_value'])
    return offices


def can_receive_revenue(user: dict, assignment_id: int = None) -> bool:
    """
    Check if user can receive revenue share.
    Any officer (including DDG/Head/TL) can receive revenue if they are part of the
    assignment team as a MEMBER. Revenue is based on team membership, not admin role.
    """
    if not user:
        return False

    # Check if user is part of the assignment team as MEMBER
    if assignment_id:
        from app.database import get_db, USE_POSTGRES
        with get_db() as conn:
            cursor = conn.cursor()
            if USE_POSTGRES:
                cursor.execute("""
                    SELECT role FROM assignment_team
                    WHERE assignment_id = %s AND officer_id = %s AND is_active = 1
                """, (assignment_id, user.get('officer_id')))
            else:
                cursor.execute("""
                    SELECT role FROM assignment_team
                    WHERE assignment_id = ? AND officer_id = ? AND is_active = 1
                """, (assignment_id, user.get('officer_id')))
            team_role = cursor.fetchone()

            if team_role:
                # MEMBER role gets revenue (can be anyone including DDG/Head)
                return team_role['role'] == 'MEMBER'

    # Also check if officer has direct revenue share entry (for backwards compatibility)
    if assignment_id:
        from app.database import get_db, USE_POSTGRES
        with get_db() as conn:
            cursor = conn.cursor()
            if USE_POSTGRES:
                cursor.execute("""
                    SELECT share_percent FROM revenue_shares
                    WHERE assignment_id = %s AND officer_id = %s
                """, (assignment_id, user.get('officer_id')))
            else:
                cursor.execute("""
                    SELECT share_percent FROM revenue_shares
                    WHERE assignment_id = ? AND officer_id = ?
                """, (assignment_id, user.get('officer_id')))
            share = cursor.fetchone()
            if share and share['share_percent'] > 0:
                return True

    return False


def get_reporting_ddg(entity_type: str, entity_value: str) -> str:
    """Get which DDG an entity reports to."""
    from app.database import get_db, USE_POSTGRES

    with get_db() as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute("""
                SELECT reports_to_role FROM reporting_hierarchy
                WHERE entity_type = %s AND entity_value = %s
                AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
            """, (entity_type, entity_value))
        else:
            cursor.execute("""
                SELECT reports_to_role FROM reporting_hierarchy
                WHERE entity_type = ? AND entity_value = ?
                AND (effective_to IS NULL OR effective_to >= DATE('now'))
            """, (entity_type, entity_value))
        row = cursor.fetchone()
        if row:
            return row['reports_to_role']
    return None
