"""Score each creator's fit for RingOut with an LLM, using structured JSON output.

Runs locally through Ollama (http://localhost:11434), so no creator data leaves the machine.

    python -m qualifier.classify --model mistral --only-labeled   # the 100 hand-labelled creators
    python -m qualifier.classify --model mistral                  # everyone
"""
import argparse
import json
import time
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, Field, ValidationError

from .db import connect
from .prompts import PROMPTS, RULE_INACTIVE_DAYS

OLLAMA = "http://localhost:11434/api/chat"


class Assessment(BaseModel):
    fit_score: int = Field(ge=1, le=5)
    main_content: str
    games_mentioned: list[str] = Field(max_length=8)  # unbounded lists made the model loop on game-heavy channels
    plays_indie_games: bool
    plays_shooters: bool
    language: str
    reason: str


def ask_ollama(client: httpx.Client, model: str, system: str, user: str) -> tuple[Assessment, dict]:
    r = client.post(OLLAMA, json={
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": Assessment.model_json_schema(),   # constrained decoding: output must match the schema
        "stream": False,
        "options": {"temperature": 0, "num_predict": 400},  # hard cap: a runaway answer fails fast instead of hanging
    })
    r.raise_for_status()
    body = r.json()
    result = Assessment.model_validate_json(body["message"]["content"])
    usage = {"input_tokens": body.get("prompt_eval_count"), "output_tokens": body.get("eval_count")}
    return result, usage


def _days_since(iso: str | None) -> int:
    if not iso:
        return -1
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days


def channel_text(row, with_activity: bool = False) -> str:
    titles = json.loads(row["recent_titles"] or "[]")
    parts = [
        f"Platform: {row['platform']}",
        f"Channel: {row['channel_title'] or row['name']}",
        f"Language: {row['language'] or 'unknown'}",
        f"Audience: {row['subscribers'] or row['audience_note'] or 'unknown'}",
    ]
    if row["current_game"]:
        parts.append(f"Current Twitch category: {row['current_game']}")
    if with_activity:
        last = row["last_upload_at"]
        if last:
            days = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
            parts.append(f"Last upload / stream: {last[:10]} ({days} days ago)")
        else:
            parts.append("Last upload / stream: none found")
        avg = row["avg_recent_views"]
        parts.append(f"Average views on the last videos: {avg if avg is not None else 'unknown'}")
    parts.append(f"Channel description: {(row['description'] or '').strip()[:800] or '(empty)'}")
    parts.append("Recent video / stream titles:\n" + "\n".join(f"- {t}" for t in titles[:10]))
    return "\n".join(parts)


def run(model: str, prompt_version: str, only_labeled: bool, limit: int | None) -> None:
    system = PROMPTS[prompt_version]
    con = connect()
    rows = con.execute(f"""
        SELECT c.id, c.name, c.platform, c.audience_note, s.id AS snapshot_id, s.channel_title,
               s.description, s.language, s.subscribers, s.current_game, s.recent_titles,
               s.last_upload_at, s.avg_recent_views
        FROM creators c
        JOIN channel_snapshots s ON s.id = (SELECT MAX(id) FROM channel_snapshots
                                            WHERE creator_id = c.id AND ok = 1)
        {"JOIN labels l ON l.creator_id = c.id" if only_labeled else ""}
        WHERE NOT EXISTS (SELECT 1 FROM llm_runs r WHERE r.creator_id = c.id
                          AND r.model = ? AND r.prompt_version = ? AND r.error IS NULL)
        ORDER BY c.id""", (model, prompt_version)).fetchall()
    rows = rows[:limit] if limit else rows
    print(f"{len(rows)} creators to score with {model} / prompt {prompt_version}")
    done = 0
    with httpx.Client(timeout=120) as client:
        for row in rows:
            t0 = time.perf_counter()
            limit_days = RULE_INACTIVE_DAYS.get(prompt_version)
            if limit_days and row["platform"] == "YouTube" and _days_since(row["last_upload_at"]) > limit_days:
                # Deterministic rule, no LLM call: a dead YouTube channel will not cover the game.
                rule = {"rule": f"inactive: no upload for {_days_since(row['last_upload_at'])} days"}
                with con:
                    con.execute("""INSERT INTO llm_runs (creator_id, snapshot_id, model, prompt_version, fit_score,
                                       output_json, input_tokens, output_tokens, error, latency_ms)
                                   VALUES (?, ?, ?, ?, 1, ?, 0, 0, NULL, 0)""",
                                (row["id"], row["snapshot_id"], model, prompt_version, json.dumps(rule)))
                done += 1
                continue
            try:
                a, usage = ask_ollama(client, model, system, channel_text(row, prompt_version == "v2"))
                values = (a.fit_score, a.model_dump_json(), usage["input_tokens"], usage["output_tokens"], None)
            except (httpx.HTTPError, ValidationError, KeyError, json.JSONDecodeError) as e:
                values = (None, None, None, None, f"{type(e).__name__}: {e}"[:500])
            latency = int((time.perf_counter() - t0) * 1000)
            with con:
                con.execute("""INSERT INTO llm_runs (creator_id, snapshot_id, model, prompt_version, fit_score,
                                   output_json, input_tokens, output_tokens, error, latency_ms)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (row["id"], row["snapshot_id"], model, prompt_version, *values, latency))
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(rows)}")
    print("done")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="mistral")
    p.add_argument("--prompt", default="v1", choices=sorted(PROMPTS))
    p.add_argument("--only-labeled", action="store_true")
    p.add_argument("--limit", type=int)
    a = p.parse_args()
    run(a.model, a.prompt, a.only_labeled, a.limit)
