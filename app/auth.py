"""
Authentication utilities: password hashing, session management, and auth helpers.
"""
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from itsdangerous import URLSafeTimedSerializer

from app.config import SECRET_KEY, SESSION_MAX_AGE
from app.database import get_db, USE_POSTGRES


def generate_password(length: int = 12) -> str:
    """Generate a random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    try:
        password_bytes = password.encode('utf-8')
        hash_bytes = password_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception:
        return False


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return secrets.token_urlsafe(32)


def create_session(officer_id: str, active_role: str = None) -> str:
    """Create a new session for an officer and return the session ID."""
    session_id = generate_session_id()
    expires_at = datetime.now() + timedelta(seconds=SESSION_MAX_AGE)

    with get_db() as conn:
        cursor = conn.cursor()
        # Remove any existing sessions for this officer
        if USE_POSTGRES:
            cursor.execute("DELETE FROM sessions WHERE officer_id = %s", (officer_id,))
            cursor.execute(
                """INSERT INTO sessions (session_id, officer_id, active_role, expires_at)
                   VALUES (%s, %s, %s, %s)""",
                (session_id, officer_id, active_role, expires_at)
            )
        else:
            cursor.execute("DELETE FROM sessions WHERE officer_id = ?", (officer_id,))
            cursor.execute(
                """INSERT INTO sessions (session_id, officer_id, active_role, expires_at)
                   VALUES (?, ?, ?, ?)""",
                (session_id, officer_id, active_role, expires_at)
            )

    return session_id


def update_session_role(session_id: str, active_role: str) -> bool:
    """Update the active role for an existing session."""
    with get_db() as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute(
                "UPDATE sessions SET active_role = %s WHERE session_id = %s",
                (active_role, session_id)
            )
        else:
            cursor.execute(
                "UPDATE sessions SET active_role = ? WHERE session_id = ?",
                (active_role, session_id)
            )
        return cursor.rowcount > 0


def validate_session(session_id: str) -> Optional[dict]:
    """
    Validate a session ID and return officer info if valid.
    Returns None if session is invalid or expired.
    """
    if not session_id:
        return None

    with get_db() as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute(
                """SELECT s.officer_id, s.expires_at, s.active_role, o.name, o.email, o.office_id, o.designation, o.admin_role_id
                   FROM sessions s
                   JOIN officers o ON s.officer_id = o.officer_id
                   WHERE s.session_id = %s AND o.is_active = 1""",
                (session_id,)
            )
        else:
            cursor.execute(
                """SELECT s.officer_id, s.expires_at, s.active_role, o.name, o.email, o.office_id, o.designation, o.admin_role_id
                   FROM sessions s
                   JOIN officers o ON s.officer_id = o.officer_id
                   WHERE s.session_id = ? AND o.is_active = 1""",
                (session_id,)
            )
        row = cursor.fetchone()

        if not row:
            return None

        # Check expiration - PostgreSQL returns datetime objects, SQLite returns strings
        expires_at = row['expires_at']
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if datetime.now() > expires_at:
            # Session expired, delete it
            if USE_POSTGRES:
                cursor.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
            else:
                cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            return None

        from app.roles import get_user_role, get_user_roles, get_user_permissions, get_user_role_display, ROLE_ADMIN

        admin_role = row['admin_role_id']
        active_role = row['active_role']
        user_data = {
            'officer_id': row['officer_id'],
            'name': row['name'],
            'email': row['email'],
            'office_id': row['office_id'],
            'designation': row['designation'],
            'admin_role_id': admin_role,
            'is_admin': admin_role == ROLE_ADMIN,
            'active_role': active_role
        }

        # Add role and permissions
        user_data['role'] = get_user_role(user_data)
        user_data['roles'] = get_user_roles(user_data)
        user_data['role_display'] = get_user_role_display(user_data)
        user_data['permissions'] = get_user_permissions(user_data)

        return user_data


def delete_session(session_id: str) -> None:
    """Delete a session (logout)."""
    with get_db() as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
        else:
            cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def authenticate_officer(email: str, password: str) -> Optional[dict]:
    """
    Authenticate an officer by email and password.
    Returns officer info if successful, None otherwise.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute(
                """SELECT officer_id, name, email, password_hash, office_id, designation, is_active
                   FROM officers WHERE email = %s""",
                (email.lower().strip(),)
            )
        else:
            cursor.execute(
                """SELECT officer_id, name, email, password_hash, office_id, designation, is_active
                   FROM officers WHERE email = ?""",
                (email.lower().strip(),)
            )
        row = cursor.fetchone()

        if not row:
            return None

        if not row['is_active']:
            return None

        if not verify_password(password, row['password_hash']):
            return None

        return {
            'officer_id': row['officer_id'],
            'name': row['name'],
            'email': row['email'],
            'office_id': row['office_id'],
            'designation': row['designation']
        }


def get_serializer():
    """Get the URL-safe serializer for session cookies."""
    return URLSafeTimedSerializer(SECRET_KEY)


def serialize_session(session_id: str) -> str:
    """Serialize session ID for cookie storage."""
    serializer = get_serializer()
    return serializer.dumps(session_id)


def deserialize_session(token: str) -> Optional[str]:
    """Deserialize session ID from cookie."""
    try:
        serializer = get_serializer()
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except Exception:
        return None
