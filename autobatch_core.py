"""Conservative TV episode recognition for the AutoBatch index."""
import hashlib
import os
import re
from collections import defaultdict

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".ts"}

# Match only explicit season-and-episode labels; do not mistake years for seasons.
PATTERNS = [
    re.compile(r"(?i)(?<![A-Za-z0-9])s(?:eason)?[\s._-]*0*(?P<season>\d{1,2})[\s._-]*e(?:p(?:isode)?)?[\s._-]*0*(?P<episode>\d{1,3})(?!\d)"),
    re.compile(r"(?i)(?<![A-Za-z0-9])season[\s._-]*0*(?P<season>\d{1,2})[\s._-]*(?:episode|ep|e)[\s._-]*0*(?P<episode>\d{1,3})(?!\d)"),
    re.compile(r"(?i)(?<![A-Za-z0-9])(?P<season>\d{1,2})[\s._-]*x[\s._-]*0*(?P<episode>\d{1,3})(?!\d)"),
]

def parse_episode(text):
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.split("\n", 1)[0].strip()
    raw = re.sub(r"(?i)^(?:\s*[\[(](?:[^\])]{1,45})[\])][\s._-]*)+", "", raw)
    for pattern in PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        rest = raw[match.end():]
        # Avoid treating a multipart E01-E02 release as just one episode.
        if re.match(r"(?i)^(?:[\s._-]*(?:-?\s*e(?:p(?:isode)?)?[\s._-]*\d{1,3}|\d{1,3}\s*-\s*\d{1,3}))", rest):
            return None
        title = raw[:match.start()]
        title = re.sub(r"(?i)^(?:\s*[\[(][^\])]{1,45}[\])][\s._-]*)+", "", title)
        title = re.sub(r"[._]+", " ", title)
        title = re.sub(r"\s+", " ", title).strip(" -_[]().")
        season, episode = int(match.group("season")), int(match.group("episode"))
        if not title or len(title) > 125 or not (1 <= season <= 99 and 1 <= episode <= 999):
            continue
        key = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
        if not key:
            continue
        return {
            "series_title": title,
            "series_key": key,
            "series_id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
            "season": season,
            "episode": episode,
        }
    return None

def parse_media(filename, caption, is_video=False):
    if not is_video and os.path.splitext(filename or "")[1].lower() not in VIDEO_EXTENSIONS:
        return None
    # Some caption titles contain watermarks in filename; try both.
    for candidate in (filename, caption):
        result = parse_episode(candidate)
        if result:
            return result
    return None

def organize_seasons(records):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in records:
        try:
            season, episode, message_id = int(row["season"]), int(row["episode"]), int(row["message_id"])
        except (KeyError, ValueError, TypeError):
            continue
        if season > 0 and episode > 0 and message_id > 0:
            grouped[season][episode].append(message_id)
    result = []
    for season, episodes in sorted(grouped.items()):
        kept = [min(episodes[episode]) for episode in sorted(episodes)]
        missing = [i for i in range(1, max(episodes) + 1) if i not in episodes]
        result.append({
            "season": season,
            "episodes": len(episodes),
            "message_ids": kept,
            "missing": missing,
            "duplicates": sum(len(ids) - 1 for ids in episodes.values()),
        })
    return result
