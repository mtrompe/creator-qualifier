"""Fetch public channel data from the YouTube Data API v3 and the Twitch Helix API.

Usage:
    python -m qualifier.fetch            # fetch every creator not fetched yet
    python -m qualifier.fetch --limit 20 # try on a few first
    python -m qualifier.fetch --refresh  # re-fetch everyone (e.g. after adding new fields)
"""
import argparse
import json
import os
import re
import time
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from .db import connect

load_dotenv()
YT = "https://www.googleapis.com/youtube/v3"
HELIX = "https://api.twitch.tv/helix"
N_TITLES = 10


class FetchError(Exception):
    pass


# ---------------------------------------------------------------- YouTube
def _yt_channel_params(url: str) -> dict:
    path = urlparse(url).path.rstrip("/")
    if m := re.search(r"/channel/(UC[\w-]+)", path):
        return {"id": m.group(1)}
    if m := re.search(r"/@([\w.\-]+)", path):
        return {"forHandle": "@" + m.group(1)}
    if m := re.search(r"/(?:c|user)/([\w.\-]+)", path):
        return {"forUsername": m.group(1)}
    raise FetchError(f"unrecognised YouTube URL: {url}")


def fetch_youtube(client: httpx.Client, url: str) -> dict:
    key = os.environ["YOUTUBE_API_KEY"]
    r = client.get(f"{YT}/channels", params={
        "part": "snippet,statistics,contentDetails", "key": key, **_yt_channel_params(url)})
    r.raise_for_status()
    items = r.json().get("items") or []
    if not items:
        raise FetchError("channel not found")
    ch = items[0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    r = client.get(f"{YT}/playlistItems", params={
        "part": "snippet,contentDetails", "playlistId": uploads, "maxResults": N_TITLES, "key": key})
    r.raise_for_status()
    items = r.json().get("items", [])
    titles = [it["snippet"]["title"] for it in items]
    dates = [it["contentDetails"].get("videoPublishedAt") or it["snippet"]["publishedAt"] for it in items]
    views = []
    if items:
        r = client.get(f"{YT}/videos", params={
            "part": "statistics", "id": ",".join(it["contentDetails"]["videoId"] for it in items), "key": key})
        r.raise_for_status()
        views = [int(v["statistics"].get("viewCount", 0)) for v in r.json().get("items", [])]
    stats = ch.get("statistics", {})
    return {
        "channel_title": ch["snippet"]["title"],
        "description": ch["snippet"].get("description", "")[:2000],
        "language": ch["snippet"].get("defaultLanguage") or ch["snippet"].get("country"),
        "subscribers": None if stats.get("hiddenSubscriberCount") else int(stats.get("subscriberCount", 0)),
        "current_game": None,
        "recent_titles": titles,
        "last_upload_at": max(dates) if dates else None,
        "avg_recent_views": int(sum(views) / len(views)) if views else None,
        "raw": ch,
    }


# ---------------------------------------------------------------- Twitch
_twitch_token: str | None = None


def _twitch_headers(client: httpx.Client) -> dict:
    global _twitch_token
    if _twitch_token is None:
        r = client.post("https://id.twitch.tv/oauth2/token", params={
            "client_id": os.environ["TWITCH_CLIENT_ID"],
            "client_secret": os.environ["TWITCH_CLIENT_SECRET"],
            "grant_type": "client_credentials"})
        r.raise_for_status()
        _twitch_token = r.json()["access_token"]
    return {"Client-Id": os.environ["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {_twitch_token}"}


def fetch_twitch(client: httpx.Client, url: str) -> dict:
    login = urlparse(url).path.strip("/").split("/")[0].lower()
    if not login:
        raise FetchError(f"unrecognised Twitch URL: {url}")
    h = _twitch_headers(client)
    r = client.get(f"{HELIX}/users", params={"login": login}, headers=h)
    r.raise_for_status()
    users = r.json().get("data") or []
    if not users:
        raise FetchError("user not found")
    u = users[0]
    r = client.get(f"{HELIX}/channels", params={"broadcaster_id": u["id"]}, headers=h)
    r.raise_for_status()
    chan = (r.json().get("data") or [{}])[0]
    r = client.get(f"{HELIX}/videos", params={"user_id": u["id"], "first": N_TITLES}, headers=h)
    r.raise_for_status()
    vids = r.json().get("data", [])
    titles = [v["title"] for v in vids]
    return {
        "channel_title": u["display_name"],
        "description": (u.get("description") or "")[:2000],
        "language": chan.get("broadcaster_language"),
        "subscribers": None,
        "current_game": chan.get("game_name"),
        "recent_titles": titles,
        "last_upload_at": max((v["created_at"] for v in vids), default=None),
        "avg_recent_views": int(sum(v["view_count"] for v in vids) / len(vids)) if vids else None,
        "raw": {"user": u, "channel": chan},
    }


# ---------------------------------------------------------------- runner
REQUIRED = ["YOUTUBE_API_KEY", "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"]


def run(limit: int | None, refresh: bool = False) -> None:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing in .env: {', '.join(missing)}")
    con = connect()
    rows = con.execute(
        """SELECT c.id, c.platform, c.channel_url FROM creators c
           WHERE ? OR NOT EXISTS (SELECT 1 FROM channel_snapshots s WHERE s.creator_id = c.id AND s.ok = 1)
           ORDER BY c.id""", (int(refresh),)).fetchall()
    rows = rows[:limit] if limit else rows
    ok = failed = 0
    with httpx.Client(timeout=20) as client:
        for row in rows:
            try:
                fetcher = fetch_youtube if row["platform"] == "YouTube" else fetch_twitch
                d = fetcher(client, row["channel_url"])
                with con:
                    con.execute(
                        """INSERT INTO channel_snapshots (creator_id, ok, channel_title, description,
                               language, subscribers, current_game, recent_titles, raw_json,
                               last_upload_at, avg_recent_views)
                           VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (row["id"], d["channel_title"], d["description"], d["language"],
                         d["subscribers"], d["current_game"],
                         json.dumps(d["recent_titles"], ensure_ascii=False),
                         json.dumps(d["raw"], ensure_ascii=False),
                         d["last_upload_at"], d["avg_recent_views"]))
                ok += 1
            except (FetchError, httpx.HTTPError, KeyError) as e:
                with con:
                    con.execute("INSERT INTO channel_snapshots (creator_id, ok, error) VALUES (?, 0, ?)",
                                (row["id"], f"{type(e).__name__}: {e}"[:500]))
                failed += 1
            time.sleep(0.1)  # stay well under API rate limits
    print(f"fetched {ok}, failed {failed}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int)
    p.add_argument("--refresh", action="store_true", help="re-fetch every creator (new snapshot)")
    a = p.parse_args()
    run(a.limit, a.refresh)
