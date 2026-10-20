"""Audio tag writer for the library organizer.

Writes tags to MP3 (ID3), FLAC, OGG (Vorbis), and M4A files via mutagen.
All imports are lazy (inside each _write_* function) so the module is
importable on machines without mutagen.

write_tags(path, tags, profile) -> str | None
  Returns None on success, a short error string on any failure.
  Never raises.

Full tag backup is stored in OrganizerJournalItem.old_tags before any write
(caller's responsibility to save old_tags before calling this).
"""
from __future__ import annotations

import os
from typing import Any, Optional

_AUDIO_EXTS = {"mp3", "flac", "ogg", "oga", "m4a"}

# Managed ID3 frame types for strip_unmanaged. TXXX frames are included as a set.
_MANAGED_ID3_FRAMES = frozenset({
    "TIT2", "TPE1", "TPE2", "TALB", "TRCK", "TPOS", "TCON", "TDRC",
    "TXXX:MusicBrainz Recording Id",
    "TXXX:MusicBrainz Album Id",
    "TXXX:MusicBrainz Artist Id",
})


def write_tags(path: str, tags: dict, profile: dict) -> Optional[str]:
    """Write audio tags to the file at `path`.

    Returns None on success, an error string on any failure.
    """
    try:
        ext = os.path.splitext(path)[1].lstrip('.').lower()
        if ext == 'mp3':
            return _write_mp3(path, tags, profile)
        elif ext == 'flac':
            return _write_flac(path, tags, profile)
        elif ext in ('ogg', 'oga'):
            return _write_ogg(path, tags, profile)
        elif ext == 'm4a':
            return _write_m4a(path, tags, profile)
        else:
            return f"unsupported format: {ext}"
    except Exception as exc:
        return str(exc)


def backup_tags(path: str) -> Optional[dict]:
    """Read all tags from a file and return them as a serializable dict.

    Returns None when the file cannot be read. Captures all frames including
    APIC, USLT, TXXX, RVA2 for MP3; all Vorbis comments and PICTURE for
    FLAC/OGG; all MP4 atoms for M4A.
    """
    try:
        ext = os.path.splitext(path)[1].lstrip('.').lower()
        if ext == 'mp3':
            return _backup_mp3(path)
        elif ext == 'flac':
            return _backup_flac(path)
        elif ext in ('ogg', 'oga'):
            return _backup_ogg(path)
        elif ext == 'm4a':
            return _backup_m4a(path)
        else:
            return None
    except Exception:
        return None


def restore_tags(path: str, backup: dict) -> Optional[str]:
    """Restore the exact tag set from a backup created by backup_tags.

    Returns None on success, an error string on failure.
    """
    try:
        ext = os.path.splitext(path)[1].lstrip('.').lower()
        if ext == 'mp3':
            return _restore_mp3(path, backup)
        elif ext == 'flac':
            return _restore_flac(path, backup)
        elif ext in ('ogg', 'oga'):
            return _restore_ogg(path, backup)
        elif ext == 'm4a':
            return _restore_m4a(path, backup)
        else:
            return f"unsupported format: {ext}"
    except Exception as exc:
        return str(exc)


# ---------------------------------------------------------------------------
# MP3 (ID3)
# ---------------------------------------------------------------------------
def _write_mp3(path: str, tags: dict, profile: dict) -> Optional[str]:
    try:
        import mutagen.id3 as id3  # type: ignore
    except ImportError:
        return "mutagen not installed"
    try:
        try:
            audio = id3.ID3(path)
        except id3.ID3NoHeaderError:
            audio = id3.ID3()

        id3_version = profile.get("id3_version", "2.3")
        v2_version = 4 if id3_version == "2.4" else 3

        if profile.get("strip_unmanaged"):
            keys_to_remove = [k for k in list(audio.keys()) if not _is_managed_id3(k)]
            for k in keys_to_remove:
                del audio[k]

        if tags.get("title"):
            audio["TIT2"] = id3.TIT2(encoding=3, text=tags["title"])
        if tags.get("artist"):
            audio["TPE1"] = id3.TPE1(encoding=3, text=tags["artist"])
        if tags.get("album_artist"):
            audio["TPE2"] = id3.TPE2(encoding=3, text=tags["album_artist"])
        if tags.get("album"):
            audio["TALB"] = id3.TALB(encoding=3, text=tags["album"])
        if tags.get("track_number") is not None:
            trck = str(tags["track_number"])
            if tags.get("track_total"):
                trck = f"{trck}/{tags['track_total']}"
            audio["TRCK"] = id3.TRCK(encoding=3, text=trck)
        if tags.get("disc_number") is not None:
            tpos = str(tags["disc_number"])
            if tags.get("disc_total"):
                tpos = f"{tpos}/{tags['disc_total']}"
            audio["TPOS"] = id3.TPOS(encoding=3, text=tpos)
        if tags.get("genre"):
            audio["TCON"] = id3.TCON(encoding=3, text=tags["genre"])
        if tags.get("year"):
            audio["TDRC"] = id3.TDRC(encoding=3, text=str(tags["year"]))

        if profile.get("mb_ids"):
            if tags.get("mb_recording_id"):
                audio["TXXX:MusicBrainz Recording Id"] = id3.TXXX(
                    encoding=3, desc="MusicBrainz Recording Id", text=tags["mb_recording_id"]
                )
            if tags.get("mb_album_id"):
                audio["TXXX:MusicBrainz Album Id"] = id3.TXXX(
                    encoding=3, desc="MusicBrainz Album Id", text=tags["mb_album_id"]
                )
            if tags.get("mb_artist_id"):
                audio["TXXX:MusicBrainz Artist Id"] = id3.TXXX(
                    encoding=3, desc="MusicBrainz Artist Id", text=tags["mb_artist_id"]
                )

        if profile.get("embed_art") and tags.get("art_bytes"):
            audio["APIC:"] = id3.APIC(
                encoding=3, mime="image/jpeg", type=3, desc="", data=tags["art_bytes"]
            )

        audio.save(path, v2_version=v2_version)
        return None
    except Exception as exc:
        return str(exc)


def _is_managed_id3(key: str) -> bool:
    if key in _MANAGED_ID3_FRAMES:
        return True
    if key.startswith("TXXX:MusicBrainz"):
        return True
    if key.startswith("APIC") and False:  # art embedding is separate
        return True
    return False


def _backup_mp3(path: str) -> dict:
    import base64
    try:
        import mutagen.id3 as id3  # type: ignore
    except ImportError:
        return {}
    try:
        audio = id3.ID3(path)
    except id3.ID3NoHeaderError:
        return {"_empty": True}
    result: dict[str, Any] = {}
    for key in audio.keys():
        frame = audio[key]
        try:
            result[key] = {"encoding": getattr(frame, "encoding", 3),
                           "data": frame._pprint() if hasattr(frame, "_pprint") else repr(frame)}
        except Exception:
            result[key] = repr(frame)
    result["_frames_raw"] = {k: audio[k].HashKey + ":" + repr(audio[k]) for k in audio.keys()}
    # Store the raw ID3 header bytes so restore_tags can do a faithful round-trip.
    # Read the raw bytes directly from the file to preserve the original ID3 version
    # and all frame bytes without re-serialization through mutagen (which would change
    # the version to ID3v2.4 by default).
    try:
        with open(path, "rb") as _f:
            _hdr = _f.read(10)
            if _hdr[:3] == b"ID3":
                _size_bytes = _hdr[6:10]
                _sync_size = (
                    ((_size_bytes[0] & 0x7F) << 21)
                    | ((_size_bytes[1] & 0x7F) << 14)
                    | ((_size_bytes[2] & 0x7F) << 7)
                    | (_size_bytes[3] & 0x7F)
                )
                _id3_end = 10 + _sync_size
                _f.seek(0)
                raw_id3 = _f.read(_id3_end)
                result["_raw_id3_b64"] = base64.b64encode(raw_id3).decode("ascii")
    except Exception:
        pass
    return result


def _restore_mp3(path: str, backup: dict) -> Optional[str]:
    """Restore MP3 tags from a backup produced by _backup_mp3.

    When the backup carries ``_raw_id3_b64`` (raw ID3 header bytes), those
    bytes replace the existing ID3 header in the file so all frames survive
    the round-trip faithfully.  Falls back to no-op when the field is absent
    (old backups pre-dating this field).
    """
    import base64
    raw_b64 = backup.get("_raw_id3_b64")
    if not raw_b64:
        return None
    try:
        import mutagen.id3 as id3  # type: ignore
    except ImportError:
        return "mutagen not installed"
    try:
        raw_id3 = base64.b64decode(raw_b64)
        # Read the file to find where the audio data starts (after the old ID3 header)
        with open(path, "rb") as f:
            header = f.read(10)
            if header[:3] == b"ID3":
                size_bytes = header[6:10]
                # ID3v2 synchsafe integer
                sync_size = (
                    ((size_bytes[0] & 0x7F) << 21)
                    | ((size_bytes[1] & 0x7F) << 14)
                    | ((size_bytes[2] & 0x7F) << 7)
                    | (size_bytes[3] & 0x7F)
                )
                old_id3_size = 10 + sync_size
                # Include extended header if present (flag bit 6)
                f.seek(0)
                f.seek(old_id3_size)
            else:
                f.seek(0)
            audio_data = f.read()
        with open(path, "wb") as f:
            f.write(raw_id3 + audio_data)
        return None
    except Exception as exc:
        return str(exc)


# ---------------------------------------------------------------------------
# FLAC
# ---------------------------------------------------------------------------
def _write_flac(path: str, tags: dict, profile: dict) -> Optional[str]:
    try:
        import mutagen.flac as flac_mod  # type: ignore
    except ImportError:
        return "mutagen not installed"
    try:
        audio = flac_mod.FLAC(path)
        if audio.tags is None:
            audio.add_tags()

        if tags.get("title"):
            audio["title"] = [tags["title"]]
        if tags.get("artist"):
            audio["artist"] = [tags["artist"]]
        if tags.get("album_artist"):
            audio["albumartist"] = [tags["album_artist"]]
        if tags.get("album"):
            audio["album"] = [tags["album"]]
        if tags.get("track_number") is not None:
            audio["tracknumber"] = [str(tags["track_number"])]
        if tags.get("disc_number") is not None:
            audio["discnumber"] = [str(tags["disc_number"])]
        if tags.get("genre"):
            audio["genre"] = [tags["genre"]]
        if tags.get("year"):
            audio["date"] = [str(tags["year"])]

        if profile.get("mb_ids"):
            if tags.get("mb_recording_id"):
                audio["musicbrainz_trackid"] = [tags["mb_recording_id"]]
            if tags.get("mb_album_id"):
                audio["musicbrainz_albumid"] = [tags["mb_album_id"]]
            if tags.get("mb_artist_id"):
                audio["musicbrainz_artistid"] = [tags["mb_artist_id"]]

        if profile.get("embed_art") and tags.get("art_bytes"):
            pic = flac_mod.Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.data = tags["art_bytes"]
            audio.add_picture(pic)

        audio.save()
        return None
    except Exception as exc:
        return str(exc)


def _backup_flac(path: str) -> dict:
    try:
        import mutagen.flac as flac_mod  # type: ignore
    except ImportError:
        return {}
    try:
        audio = flac_mod.FLAC(path)
        result: dict[str, Any] = {}
        if audio.tags:
            result["tags"] = dict(audio.tags)
        result["pictures"] = []
        for pic in audio.pictures:
            result["pictures"].append({
                "type": pic.type,
                "mime": pic.mime,
                "desc": pic.desc,
                "data_hex": pic.data.hex() if pic.data else "",
            })
        return result
    except Exception:
        return {}


def _restore_flac(path: str, backup: dict) -> Optional[str]:
    try:
        import mutagen.flac as flac_mod  # type: ignore
    except ImportError:
        return "mutagen not installed"
    try:
        audio = flac_mod.FLAC(path)
        audio.delete()
        if backup.get("tags"):
            if audio.tags is None:
                audio.add_tags()
            for k, v in backup["tags"].items():
                audio[k] = v if isinstance(v, list) else [v]
        audio.clear_pictures()
        for pic_data in backup.get("pictures", []):
            pic = flac_mod.Picture()
            pic.type = pic_data.get("type", 3)
            pic.mime = pic_data.get("mime", "image/jpeg")
            pic.desc = pic_data.get("desc", "")
            if pic_data.get("data_hex"):
                pic.data = bytes.fromhex(pic_data["data_hex"])
            audio.add_picture(pic)
        audio.save()
        return None
    except Exception as exc:
        return str(exc)


# ---------------------------------------------------------------------------
# OGG Vorbis
# ---------------------------------------------------------------------------
def _write_ogg(path: str, tags: dict, profile: dict) -> Optional[str]:
    try:
        import mutagen.oggvorbis as ogg  # type: ignore
    except ImportError:
        return "mutagen not installed"
    try:
        audio = ogg.OggVorbis(path)
        if audio.tags is None:
            audio.add_tags()

        if tags.get("title"):
            audio["title"] = [tags["title"]]
        if tags.get("artist"):
            audio["artist"] = [tags["artist"]]
        if tags.get("album_artist"):
            audio["albumartist"] = [tags["album_artist"]]
        if tags.get("album"):
            audio["album"] = [tags["album"]]
        if tags.get("track_number") is not None:
            audio["tracknumber"] = [str(tags["track_number"])]
        if tags.get("disc_number") is not None:
            audio["discnumber"] = [str(tags["disc_number"])]
        if tags.get("genre"):
            audio["genre"] = [tags["genre"]]
        if tags.get("year"):
            audio["date"] = [str(tags["year"])]

        if profile.get("mb_ids"):
            if tags.get("mb_recording_id"):
                audio["musicbrainz_trackid"] = [tags["mb_recording_id"]]
            if tags.get("mb_album_id"):
                audio["musicbrainz_albumid"] = [tags["mb_album_id"]]
            if tags.get("mb_artist_id"):
                audio["musicbrainz_artistid"] = [tags["mb_artist_id"]]

        audio.save()
        return None
    except Exception as exc:
        return str(exc)


def _backup_ogg(path: str) -> dict:
    try:
        import mutagen.oggvorbis as ogg  # type: ignore
    except ImportError:
        return {}
    try:
        audio = ogg.OggVorbis(path)
        if audio.tags:
            return {"tags": dict(audio.tags)}
        return {}
    except Exception:
        return {}


def _restore_ogg(path: str, backup: dict) -> Optional[str]:
    try:
        import mutagen.oggvorbis as ogg  # type: ignore
    except ImportError:
        return "mutagen not installed"
    try:
        audio = ogg.OggVorbis(path)
        audio.delete()
        if backup.get("tags"):
            if audio.tags is None:
                audio.add_tags()
            for k, v in backup["tags"].items():
                audio[k] = v if isinstance(v, list) else [v]
        audio.save()
        return None
    except Exception as exc:
        return str(exc)


# ---------------------------------------------------------------------------
# M4A (MP4)
# ---------------------------------------------------------------------------
def _write_m4a(path: str, tags: dict, profile: dict) -> Optional[str]:
    try:
        import mutagen.mp4 as mp4  # type: ignore
    except ImportError:
        return "mutagen not installed"
    try:
        audio = mp4.MP4(path)
        if audio.tags is None:
            audio.add_tags()

        if tags.get("title"):
            audio["\xa9nam"] = [tags["title"]]
        if tags.get("artist"):
            audio["\xa9ART"] = [tags["artist"]]
        if tags.get("album_artist"):
            audio["aART"] = [tags["album_artist"]]
        if tags.get("album"):
            audio["\xa9alb"] = [tags["album"]]
        if tags.get("track_number") is not None:
            total = int(tags.get("track_total") or 0)
            audio["trkn"] = [(int(tags["track_number"]), total)]
        if tags.get("disc_number") is not None:
            disc_total = int(tags.get("disc_total") or 0)
            audio["disk"] = [(int(tags["disc_number"]), disc_total)]
        if tags.get("genre"):
            audio["\xa9gen"] = [tags["genre"]]
        if tags.get("year"):
            audio["\xa9day"] = [str(tags["year"])]

        if profile.get("embed_art") and tags.get("art_bytes"):
            audio["covr"] = [mp4.MP4Cover(tags["art_bytes"], imageformat=mp4.MP4Cover.FORMAT_JPEG)]

        audio.save()
        return None
    except Exception as exc:
        return str(exc)


def _backup_m4a(path: str) -> dict:
    try:
        import mutagen.mp4 as mp4  # type: ignore
    except ImportError:
        return {}
    try:
        audio = mp4.MP4(path)
        if not audio.tags:
            return {}
        result: dict[str, Any] = {}
        for k, v in audio.tags.items():
            try:
                if isinstance(v, list) and v and isinstance(v[0], mp4.MP4Cover):
                    result[k] = [{"format": v[0].imageformat, "data_hex": bytes(v[0]).hex()}]
                else:
                    result[k] = v
            except Exception:
                result[k] = repr(v)
        return result
    except Exception:
        return {}


def _restore_m4a(path: str, backup: dict) -> Optional[str]:
    try:
        import mutagen.mp4 as mp4  # type: ignore
    except ImportError:
        return "mutagen not installed"
    try:
        audio = mp4.MP4(path)
        if audio.tags is None:
            audio.add_tags()
        else:
            audio.tags.clear()
        for k, v in backup.items():
            if k.startswith("_"):
                continue
            try:
                if k == "covr" and isinstance(v, list) and isinstance(v[0], dict):
                    covers = []
                    for c in v:
                        covers.append(mp4.MP4Cover(bytes.fromhex(c["data_hex"]),
                                                   imageformat=c.get("format", mp4.MP4Cover.FORMAT_JPEG)))
                    audio[k] = covers
                else:
                    audio[k] = v
            except Exception:
                pass
        audio.save()
        return None
    except Exception as exc:
        return str(exc)
