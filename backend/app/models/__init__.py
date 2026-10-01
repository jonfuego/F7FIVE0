"""SQLAlchemy models.

Importing this package registers every model on `Base.metadata`, which is
what Alembic autogenerate reads. Keep all model modules imported here.
"""
from app.db import Base

# Identity
from app.models.user import User, Session as UserSession, AuthEvent  # noqa: F401
from app.models.webauthn import WebAuthnCredential, WebAuthnChallenge  # noqa: F401

# Libraries + canonical metadata
from app.models.library import Library  # noqa: F401
from app.models.movie import Movie  # noqa: F401
from app.models.tv import Series, Season, Episode  # noqa: F401
from app.models.music import (  # noqa: F401
    Artist, Album, MusicVideo, MusicVideoRelease, Track,
)

# Physical files + playback + transcoding + sharing
from app.models.media_file import MediaFile  # noqa: F401
from app.models.playback import PlaybackQueue, WatchProgress, WatchHistory  # noqa: F401
from app.models.track_play import TrackPlay  # noqa: F401
from app.models.transcode import TranscodeSession, TranscodeCache  # noqa: F401
from app.models.share import ShareLink  # noqa: F401

# Admin overrides
from app.models.art import ArtOverride  # noqa: F401

# Media requests
from app.models.request import Request  # noqa: F401

# Intro / credits markers
from app.models.markers import MediaMarker  # noqa: F401

# Phase 2 smart-audio analysis
from app.models.audio_analysis import (  # noqa: F401
    TrackAudioAnalysis, TrackSimilarity,
)

__all__ = ["Base"]
