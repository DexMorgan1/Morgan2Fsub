"""Pure file-name parsing and season selection for AutoBatch.

No Telegram calls or media copies happen in this module.
"""
import hashlib
import os
import re
from collections import defaultdict

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".ts"}

_PATTERNS = (
    re.compile(r"(?i)^(?P<title>.+?)[\s._-]+s(?:eason)?\s*0*(?P<season>\d{1,2})[\s._-]*e(?:p(?:isode)?)?\s*0*(?P<episode>\d{1,3})(?!\d)"),
    re.compile(r"(?i)^(?P<title>.+?)[\s._-]+season[\s._-]*0*(?P<season>\d{1,2})[\s._-]*(?:episode|ep|e)[\s._-]*0*(?P<episode>\d{1,3})(?!\d)"),
    re.compile(r"(?i)^(?P<title>.+?)[\s._-]+0*(?P<season>\d{1,2})x0*(?P<episode>\d{1,3})(?!\d)"),
)


def parse_episode(text):
    """Return a conservative {title, series_id, series_key, season, episode} or None.

    Supports S01E02, Season 1 Episode 2, and 1x02. Ambiguous multi-episode
    filenames, unknown titles, or season/episode 0 are intentionally rejected.
    """
    if not text or not isinstance(text, str):
        return None
    candidate = text.strip().split("\n", 1)[0].strip()
    candidate = re.sub(r"^(?:\[[^]]{1,35}\][\s._-]*)+", "", candidate)
    for pattern in _PATTERNS:
        match = pattern.search(candidate)
        if not match:
            continue
        remainder = candidate[match.end():]
        # A range or extra E## may indicate a multi-episode file. Do not guess.
        if re.match(r"(?i)^[\s._-]*(?:-?e\d{1,3}|-?episode\s*\d{1,3})\b", remainder):
            return None
        title = re.sub(r"[._]+", " ", match.group("title"))
        title = re.sub(r"\s+", " ", title).strip(" -_[]().")
        season = int(match.group("season"))
        episode = int(match.group("episode"))
        if not title or not (1 <= season <= 99 and 1 <= episode <= 999):
            return None
        key = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
        if not key:
            return None
        return {
            "series_title": title,
            "series_key": key,
            "series_id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
            "season": season,
            "episode": episode,
        }
    return None


def parse_media(filename, caption, is_video=False):
    """Try clear caption, then the file name; reject non-video documents."""
    if not is_video and os.path.splitext(filename or "")[1].lower() not in VIDEO_EXTENSIONS:
        return None
    for candidate in (filename, caption):
        result = parse_episode(candidate)
        if result:
            return result
    return None


def organize_seasons(records):
    """Choose one file per episode in ascending order; report gaps and duplicates."""
    grouped = defaultdict(lambda: defaultdict(list))
    for record in records:
        try:
            season = int(record["season"])
            episode = int(record["episode"])
            message_id = int(record["message_id"])
        except (KeyError, ValueError, TypeError):
            continue
        if season <= 0 or episode <= 0 or message_id <= 0:
            continue
        grouped[season][episode].append(message_id)
    result = []
    for season, episodes in sorted(grouped.items()):
        kept = [min(episodes[episode]) for episode in sorted(episodes)]
        missing = [i for i in range(1, max(episodes) + 1) if i not in episodes]
        duplicates = sum(len(ids) - 1 for ids in episodes.values())
        result.append({
            "season": season,
            "episodes": len(episodes),
            "message_ids": kept,
            "missing": missing,
            "duplicates": duplicates,
        })
    return result
