"""SEC-P1-2: decide whether a signed URL's issuing session still authorizes it.

Every signed stream / art / subtitle / download URL carries the id of the
session that minted it (`sid`). After the HMAC check passes, the gateway and
the API call `session_authorizes` to reject a URL whose session is gone.

Rotation tolerance is the whole trick for playback continuity. The web and
native clients rotate their session on every ~15-minute access-token refresh:
the old session row gets `revoked_at` AND `rotated_at` stamped, a new row is
created. If a 4-hour stream URL died the moment its session rotated, a 3-hour
movie or a cast session would stop at the first refresh. So a session revoked
*by rotation* (rotated_at set) keeps authorizing its already-issued URLs until
they expire. A session revoked for any other reason -- logout, password change,
admin disable, refresh-reuse detection -- leaves rotated_at null and is dead
immediately, which is what revocation is for.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Union

from sqlalchemy.orm import Session

from app.models.user import Session as UserSession


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def session_authorizes(db: Session, session_id: Union[str, uuid.UUID]) -> bool:
    """True when the session may still authorize a signed URL.

    False when the session is unknown, expired, or explicitly revoked (not a
    rotation). Called only after the HMAC has verified, so an attacker can't
    probe sessions with a forged signature.
    """
    try:
        sid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
    except (ValueError, AttributeError):
        return False
    sess = db.get(UserSession, sid)
    if sess is None:
        return False
    now = datetime.now(timezone.utc)
    expires_at = _as_utc(sess.expires_at)
    if expires_at is not None and expires_at <= now:
        return False
    # Revoked for a real reason (rotated_at is null) -> dead. Revoked by
    # rotation (rotated_at set) -> still authorizes its outstanding URLs.
    if sess.revoked_at is not None and sess.rotated_at is None:
        return False
    return True
