#!/usr/bin/env python3
"""Grokbot: find the best GitHub repos tied to public YouTube videos.

Uses official public APIs only — no bot-protection bypass:

* GitHub REST Search + repo/readme endpoints
* YouTube Data API v3 when ``YOUTUBE_API_KEY`` is set
* YouTube oEmbed + official channel RSS as a no-key fallback
* xAI Grok (``XAI_API_KEY``) to rank the cross-referenced shortlist

Usage:
    python3 -m grokbot "open source ai agent" --limit 15
    python3 scripts/grokbot/__main__.py "yt-dlp" --json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .keys import format_keys_guide, format_keys_status, load_dotenv

GITHUB_API = "https://api.github.com"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_OEMBED = "https://www.youtube.com/oembed"
YOUTUBE_RSS = "https://www.youtube.com/feeds/videos.xml"
XAI_CHAT = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-4.3"
USER_AGENT = "grokbot/1.0 (+https://github.com/shawnj1983/hermes-agent; respectful public APIs)"

YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtube\.com/embed/|youtu\.be/|youtube\.com/shorts/)"
    r"([A-Za-z0-9_-]{11})"
)
GITHUB_REPO_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
CHANNEL_ID_RE = re.compile(r"youtube\.com/channel/(UC[A-Za-z0-9_-]{22})")


@dataclass
class Repo:
    full_name: str
    html_url: str
    description: str
    stars: int
    forks: int
    pushed_at: str
    homepage: str = ""
    topics: list[str] = field(default_factory=list)
    youtube_ids: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def activity_days(self) -> float:
        if not self.pushed_at:
            return 3650.0
        try:
            pushed = datetime.fromisoformat(self.pushed_at.replace("Z", "+00:00"))
        except ValueError:
            return 3650.0
        return max(0.0, (datetime.now(timezone.utc) - pushed).total_seconds() / 86400)


@dataclass
class Video:
    video_id: str
    title: str
    channel: str
    url: str
    view_count: int | None = None
    description: str = ""
    github_repos: list[str] = field(default_factory=list)


@dataclass
class RankedHit:
    repo: Repo
    videos: list[Video]
    reasons: list[str]
    grok_note: str = ""


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def http_json(
    url: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 45,
) -> tuple[int, Any]:
    data = None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"error": raw}
        return exc.code, parsed


def resolve_github_token() -> str | None:
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value
    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        proc = subprocess.run(
            [gh, "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    token = (proc.stdout or "").strip()
    return token or None


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = resolve_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def search_github_repos(query: str, limit: int = 20) -> list[Repo]:
    """Search public GitHub repos and rank by stars + recency."""
    q = f"{query} (youtube OR video OR transcript) in:name,description,readme"
    params = urllib.parse.urlencode(
        {"q": q, "sort": "stars", "order": "desc", "per_page": min(limit, 30)}
    )
    status, body = http_json(f"{GITHUB_API}/search/repositories?{params}", headers=github_headers())
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"GitHub search failed ({status}): {body}")
    repos: list[Repo] = []
    for item in body.get("items") or []:
        repos.append(
            Repo(
                full_name=item.get("full_name") or "",
                html_url=item.get("html_url") or "",
                description=item.get("description") or "",
                stars=int(item.get("stargazers_count") or 0),
                forks=int(item.get("forks_count") or 0),
                pushed_at=item.get("pushed_at") or "",
                homepage=item.get("homepage") or "",
                topics=list(item.get("topics") or []),
            )
        )
    for repo in repos:
        repo.score = repo_activity_score(repo)
    repos.sort(key=lambda r: r.score, reverse=True)
    return repos[:limit]


def repo_activity_score(repo: Repo) -> float:
    recency = 1.0 / (1.0 + repo.activity_days / 30.0)
    return repo.stars + (repo.forks * 0.25) + (recency * 80.0)


def fetch_readme_text(full_name: str) -> str:
    status, body = http_json(f"{GITHUB_API}/repos/{full_name}/readme", headers=github_headers())
    if status != 200 or not isinstance(body, dict):
        return ""
    encoded = body.get("content") or ""
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded.replace("\n", "")).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def extract_youtube_ids(*texts: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in YOUTUBE_ID_RE.finditer(text or ""):
            vid = match.group(1)
            if vid not in seen:
                seen.add(vid)
                found.append(vid)
    return found


def extract_github_repos(*texts: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in GITHUB_REPO_RE.finditer(text or ""):
            owner, name = match.group(1), match.group(2)
            if name.endswith(".git"):
                name = name[:-4]
            full = f"{owner}/{name}"
            if full.lower() in {"github.com/features", "github.com/settings"}:
                continue
            if full not in seen:
                seen.add(full)
                found.append(full)
    return found


def extract_channel_ids(*texts: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in CHANNEL_ID_RE.finditer(text or ""):
            cid = match.group(1)
            if cid not in seen:
                seen.add(cid)
                found.append(cid)
    return found


def attach_repo_youtube_links(repos: list[Repo], per_repo_readme: int = 8) -> None:
    for repo in repos:
        blob = " ".join([repo.description, repo.homepage, " ".join(repo.topics)])
        ids = extract_youtube_ids(blob)
        if len(ids) < 2:
            time.sleep(0.15)
            readme = fetch_readme_text(repo.full_name)
            ids = extract_youtube_ids(blob, readme[:40_000])
            repo.youtube_ids = ids[:per_repo_readme]
        else:
            repo.youtube_ids = ids[:per_repo_readme]


def youtube_api_key() -> str | None:
    return os.environ.get("YOUTUBE_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def grok_api_key() -> str | None:
    return os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")


def default_model() -> str:
    return os.environ.get("GROKBOT_MODEL", DEFAULT_MODEL)


def search_youtube_api(query: str, limit: int = 15) -> list[Video]:
    key = youtube_api_key()
    if not key:
        return []
    params = urllib.parse.urlencode(
        {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(limit, 25),
            "key": key,
        }
    )
    status, body = http_json(f"{YOUTUBE_API}/search?{params}")
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"YouTube search failed ({status}): {body}")
    videos: list[Video] = []
    ids: list[str] = []
    for item in body.get("items") or []:
        snippet = item.get("snippet") or {}
        vid = ((item.get("id") or {}).get("videoId")) or ""
        if not vid:
            continue
        ids.append(vid)
        videos.append(
            Video(
                video_id=vid,
                title=snippet.get("title") or "",
                channel=snippet.get("channelTitle") or "",
                url=f"https://www.youtube.com/watch?v={vid}",
                description=snippet.get("description") or "",
            )
        )
    if ids:
        stats = _youtube_statistics(ids, key)
        for video in videos:
            video.view_count = stats.get(video.video_id)
            extra = stats.get(f"desc:{video.video_id}")
            if isinstance(extra, str) and extra:
                video.description = extra
            video.github_repos = extract_github_repos(video.description)
    return videos[:limit]


def _youtube_statistics(ids: list[str], key: str) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {"part": "statistics,snippet", "id": ",".join(ids[:50]), "key": key}
    )
    status, body = http_json(f"{YOUTUBE_API}/videos?{params}")
    out: dict[str, Any] = {}
    if status != 200 or not isinstance(body, dict):
        return out
    for item in body.get("items") or []:
        vid = item.get("id") or ""
        stats = item.get("statistics") or {}
        snippet = item.get("snippet") or {}
        try:
            out[vid] = int(stats.get("viewCount") or 0)
        except (TypeError, ValueError):
            out[vid] = None
        out[f"desc:{vid}"] = snippet.get("description") or ""
    return out


def hydrate_videos_oembed(video_ids: list[str]) -> list[Video]:
    """Official oEmbed — title/channel, no view counts, no key required."""
    videos: list[Video] = []
    seen: set[str] = set()
    for vid in video_ids:
        if vid in seen:
            continue
        seen.add(vid)
        url = f"https://www.youtube.com/watch?v={vid}"
        params = urllib.parse.urlencode({"url": url, "format": "json"})
        time.sleep(0.1)
        status, body = http_json(f"{YOUTUBE_OEMBED}?{params}")
        if status != 200 or not isinstance(body, dict):
            videos.append(Video(video_id=vid, title="", channel="", url=url))
            continue
        videos.append(
            Video(
                video_id=vid,
                title=body.get("title") or "",
                channel=body.get("author_name") or "",
                url=url,
            )
        )
    return videos


def videos_from_channel_rss(channel_ids: list[str], per_channel: int = 8) -> list[Video]:
    """Official YouTube Atom feed for a known channel id."""
    videos: list[Video] = []
    for cid in channel_ids[:5]:
        params = urllib.parse.urlencode({"channel_id": cid})
        time.sleep(0.1)
        status, body = http_get(f"{YOUTUBE_RSS}?{params}")
        if status != 200:
            continue
        titles = re.findall(r"<title>([^<]+)</title>", body)
        ids = re.findall(r"<yt:videoId>([^<]+)</yt:videoId>", body)
        authors = re.findall(r"<name>([^<]+)</name>", body)
        channel = authors[0] if authors else ""
        # First <title> is the feed title; skip it.
        entry_titles = titles[1:]
        for vid, title in list(zip(ids, entry_titles))[:per_channel]:
            videos.append(
                Video(
                    video_id=vid,
                    title=title,
                    channel=channel,
                    url=f"https://www.youtube.com/watch?v={vid}",
                )
            )
    return videos


def collect_videos(query: str, repos: list[Repo], limit: int) -> list[Video]:
    videos: list[Video] = []
    by_id: dict[str, Video] = {}

    def _add(batch: list[Video]) -> None:
        for video in batch:
            existing = by_id.get(video.video_id)
            if existing is None:
                by_id[video.video_id] = video
                videos.append(video)
                continue
            if video.view_count and not existing.view_count:
                existing.view_count = video.view_count
            if video.description and not existing.description:
                existing.description = video.description
            if video.github_repos:
                existing.github_repos = list(dict.fromkeys(existing.github_repos + video.github_repos))

    if youtube_api_key():
        _add(search_youtube_api(query, limit=limit))

    ids_from_repos: list[str] = []
    for repo in repos:
        ids_from_repos.extend(repo.youtube_ids)
    missing = [vid for vid in dict.fromkeys(ids_from_repos) if vid not in by_id]
    if missing:
        _add(hydrate_videos_oembed(missing[:limit]))

    channel_ids: list[str] = []
    for repo in repos:
        channel_ids.extend(extract_channel_ids(repo.homepage, repo.description))
    if channel_ids and len(videos) < limit:
        _add(videos_from_channel_rss(list(dict.fromkeys(channel_ids))))

    return videos[: max(limit, 1)]


def cross_reference(repos: list[Repo], videos: list[Video]) -> list[RankedHit]:
    repo_index = {repo.full_name.lower(): repo for repo in repos}
    hits: dict[str, RankedHit] = {}

    def _hit(repo: Repo) -> RankedHit:
        hit = hits.get(repo.full_name)
        if hit is None:
            hit = RankedHit(repo=repo, videos=[], reasons=[])
            hits[repo.full_name] = hit
        return hit

    for repo in repos:
        if repo.youtube_ids:
            hit = _hit(repo)
            hit.reasons.append(f"README/homepage cites {len(repo.youtube_ids)} YouTube video(s)")

    videos_by_id = {video.video_id: video for video in videos}
    for repo in repos:
        for vid in repo.youtube_ids:
            video = videos_by_id.get(vid)
            if not video:
                continue
            hit = _hit(repo)
            if video.video_id not in {v.video_id for v in hit.videos}:
                hit.videos.append(video)
            if repo.full_name not in video.github_repos:
                video.github_repos.append(repo.full_name)

    for video in videos:
        for full in video.github_repos:
            repo = repo_index.get(full.lower())
            if repo is None:
                # Mentioned in a video but not in the GitHub search page —
                # keep a lightweight stub so Grok can still rank it.
                repo = Repo(
                    full_name=full,
                    html_url=f"https://github.com/{full}",
                    description=f"Mentioned in YouTube video {video.video_id}",
                    stars=0,
                    forks=0,
                    pushed_at="",
                )
                repo_index[full.lower()] = repo
            hit = _hit(repo)
            if video.video_id not in {v.video_id for v in hit.videos}:
                hit.videos.append(video)
            reason = f"Video cites {full}"
            if reason not in hit.reasons:
                hit.reasons.append(reason)

    for repo in repos:
        if repo.full_name not in hits:
            hit = _hit(repo)
            hit.reasons.append("GitHub search hit (stars/activity); no YouTube link found yet")

    ranked = list(hits.values())
    # Prefer repos that actually have a video link, then activity score.
    ranked.sort(
        key=lambda h: (
            len(h.videos),
            h.repo.score,
            h.repo.stars,
        ),
        reverse=True,
    )
    return ranked


def grok_rank(query: str, hits: list[RankedHit], model: str) -> list[RankedHit]:
    api_key = grok_api_key()
    if not api_key or not hits:
        return hits
    payload_hits = []
    for hit in hits[:20]:
        payload_hits.append(
            {
                "repo": hit.repo.full_name,
                "url": hit.repo.html_url,
                "stars": hit.repo.stars,
                "pushed_at": hit.repo.pushed_at,
                "description": hit.repo.description,
                "reasons": hit.reasons,
                "videos": [
                    {
                        "title": video.title,
                        "channel": video.channel,
                        "url": video.url,
                        "views": video.view_count,
                    }
                    for video in hit.videos[:5]
                ],
            }
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You rank GitHub repositories that are actually demonstrated or "
                "discussed in YouTube videos. Prefer a real video↔repo link over "
                "star count. Return ONLY a JSON array of objects with keys "
                "repo, note (one sentence), keep (true/false). Do not invent repos."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"query": query, "candidates": payload_hits}, indent=2),
        },
    ]
    status, body = http_json(
        XAI_CHAT,
        headers={"Authorization": f"Bearer {api_key}"},
        payload={
            "model": model,
            "temperature": 0.2,
            "messages": messages,
        },
    )
    if status != 200 or not isinstance(body, dict):
        sys.stderr.write(f"grokbot: Grok ranking skipped ({status}): {body}\n")
        return hits
    content = ""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return hits
    notes = _parse_grok_notes(content)
    if not notes:
        return hits
    by_name = {hit.repo.full_name.lower(): hit for hit in hits}
    ordered: list[RankedHit] = []
    used: set[str] = set()
    for item in notes:
        name = str(item.get("repo") or "").lower()
        hit = by_name.get(name)
        if hit is None or name in used:
            continue
        if item.get("keep") is False:
            continue
        hit.grok_note = str(item.get("note") or "")
        ordered.append(hit)
        used.add(name)
    for hit in hits:
        if hit.repo.full_name.lower() not in used:
            ordered.append(hit)
    return ordered


def _parse_grok_notes(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, flags=re.S)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    return parsed if isinstance(parsed, list) else []


def run(query: str, limit: int = 12, model: str | None = None, use_grok: bool = True) -> dict[str, Any]:
    load_dotenv()
    model = model or default_model()
    repos = search_github_repos(query, limit=max(limit, 8))
    attach_repo_youtube_links(repos)
    videos = collect_videos(query, repos, limit=max(limit, 8))
    hits = cross_reference(repos, videos)
    if use_grok:
        hits = grok_rank(query, hits, model=model)
    hits = hits[:limit]
    return {
        "query": query,
        "model": model if use_grok and grok_api_key() else None,
        "youtube_api": bool(youtube_api_key()),
        "github_authenticated": bool(resolve_github_token()),
        "repos_scanned": [repo.full_name for repo in repos],
        "videos": [
            {
                "id": video.video_id,
                "title": video.title,
                "channel": video.channel,
                "views": video.view_count,
                "url": video.url,
                "github_repos": video.github_repos,
            }
            for video in videos
        ],
        "top_repos": [
            {
                "repo": hit.repo.full_name,
                "url": hit.repo.html_url,
                "stars": hit.repo.stars,
                "forks": hit.repo.forks,
                "pushed_at": hit.repo.pushed_at,
                "score": round(hit.repo.score, 2),
                "reasons": hit.reasons,
                "grok_note": hit.grok_note,
                "videos": [
                    {
                        "title": video.title or video.video_id,
                        "channel": video.channel,
                        "views": video.view_count,
                        "url": video.url,
                    }
                    for video in hit.videos
                ],
            }
            for hit in hits
        ],
    }


def render_text(result: dict[str, Any]) -> str:
    lines = [
        f"Grokbot results for {result['query']!r}",
        f"GitHub auth: {'yes' if result['github_authenticated'] else 'anonymous'}"
        f" · YouTube Data API: {'yes' if result['youtube_api'] else 'oEmbed/RSS fallback'}"
        f" · Grok: {result['model'] or 'heuristic only (XAI_API_KEY missing)'}",
        "",
    ]
    if not result["top_repos"]:
        lines.append("No video-linked GitHub repos found.")
        return "\n".join(lines)
    for idx, item in enumerate(result["top_repos"], 1):
        lines.append(f"{idx}. {item['repo']}  ★{item['stars']}  {item['url']}")
        if item.get("grok_note"):
            lines.append(f"   Grok: {item['grok_note']}")
        for reason in item.get("reasons") or []:
            lines.append(f"   - {reason}")
        for video in item.get("videos") or []:
            views = f" · {video['views']:,} views" if video.get("views") is not None else ""
            title = video.get("title") or "YouTube video"
            channel = f" ({video['channel']})" if video.get("channel") else ""
            lines.append(f"   ▶ {title}{channel}{views}")
            lines.append(f"     {video['url']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grokbot",
        description="Rank GitHub repos from public GitHub + YouTube signals using Grok.",
    )
    parser.add_argument("query", nargs="?", help="Topic to search on GitHub and YouTube")
    parser.add_argument("--limit", type=int, default=10, help="Max repos to report (default 10)")
    parser.add_argument("--model", default=None, help=f"xAI model (default {DEFAULT_MODEL} or GROKBOT_MODEL)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--no-grok", action="store_true", help="Skip the Grok ranking pass")
    parser.add_argument(
        "--keys",
        action="store_true",
        help="Show the create-your-own key guide and which keys are loaded (names only)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write the JSON result to this path as well as stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()
    if args.keys or not args.query:
        sys.stdout.write(format_keys_guide())
        sys.stdout.write("\n")
        sys.stdout.write(format_keys_status())
        if args.keys and not args.query:
            return 0
        if not args.query:
            sys.stderr.write("grokbot: pass a search query, or use --keys\n")
            return 2
    try:
        result = run(
            query=args.query,
            limit=max(1, args.limit),
            model=args.model,
            use_grok=not args.no_grok,
        )
    except RuntimeError as exc:
        sys.stderr.write(f"grokbot: {exc}\n")
        return 2
    text = json.dumps(result, indent=2) if args.json else render_text(result)
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
