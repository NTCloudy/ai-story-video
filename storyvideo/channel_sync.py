"""Commit the channel data files (history / queue / attempts / trends) without losing anyone's changes.

Several writers touch channel/*.json at nearly the same time (the daily job, the FB/IG catch-up, the web
console). A plain `git pull --rebase` stops on a JSON conflict and the run's record was then silently lost
(the next run did not know today's Short existed). This script instead:
  1. keeps this run's versions of the files,
  2. resets to the latest origin/main,
  3. merges the data field by field, commits and pushes (retrying if someone pushed meanwhile).

python -m storyvideo.channel_sync --base <commit the run started from> --message "📱 Daily Short update"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

FILES = ["history.json", "queue.json", "attempts.json", "trends.json"]
CH = Path("channel")


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:400]}")
    return r.stdout


def at(ref: str, name: str, default):
    r = subprocess.run(["git", "show", f"{ref}:channel/{name}"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return default
    try:
        return json.loads(r.stdout)
    except ValueError:
        return default


def _key(h: dict) -> str:
    return h.get("video_id") or f"{h.get('date', '')}|{h.get('title', '')}"


def merge_history(base: list, ours: list, theirs: list) -> list:
    """Union of entries; for the same Short, fields changed by this run win, other writers' fields are kept."""
    base_by = {_key(h): h for h in base}
    removed = set(base_by) - {_key(h) for h in ours}   # e.g. a takedown deleted the entry in this run
    merged = {_key(h): dict(h) for h in theirs if _key(h) not in removed}
    order = [_key(h) for h in theirs if _key(h) not in removed]
    for h in ours:
        k = _key(h)
        if k not in merged:
            # a Short recorded before its video_id was known may now carry one on the other side
            alt = next((m for m in merged if merged[m].get("date") == h.get("date")
                        and merged[m].get("title") == h.get("title")), None)
            if alt:
                k = alt
            else:
                merged[k] = dict(h)
                order.append(k)
                continue
        b = base_by.get(_key(h), {})
        for f, v in h.items():
            if v != b.get(f) or f not in merged[k]:
                merged[k][f] = v
    out = [merged[k] for k in order]
    out.sort(key=lambda h: h.get("date", ""))
    return out


def merge_queue(base: list, ours: list, theirs: list) -> list:
    """Their queue minus what this run consumed, plus anything this run added."""
    dump = lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)
    consumed = {dump(x) for x in base} - {dump(x) for x in ours}
    added = [x for x in ours if dump(x) not in {dump(b) for b in base}]
    out = [x for x in theirs if dump(x) not in consumed]
    seen = {dump(x) for x in out}
    return out + [x for x in added if dump(x) not in seen]


def merge_attempts(ours: dict, theirs: dict) -> dict:
    out = dict(theirs)
    for d, n in ours.items():
        out[d] = max(int(n), int(out.get(d, 0)))
    return dict(sorted(out.items())[-14:])


def merge_trends(ours: dict, theirs: dict) -> dict:
    return ours if (ours or {}).get("fetched", "") >= (theirs or {}).get("fetched", "") else theirs


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="storyvideo.channel_sync")
    p.add_argument("--base", required=True, help="commit the run checked out")
    p.add_argument("--message", default="📱 Daily Short update")
    args = p.parse_args(argv)

    ours = {f: json.loads((CH / f).read_text(encoding="utf-8")) if (CH / f).exists() else None for f in FILES}
    base = {f: at(args.base, f, None) for f in FILES}
    if all(ours[f] == base[f] for f in FILES):
        print("[channel] nothing changed")
        return 0
    git("config", "user.name", "shorts-bot")
    git("config", "user.email", "shorts-bot@users.noreply.github.com")
    for attempt in range(5):
        git("fetch", "-q", "origin", "main")
        git("reset", "-q", "--hard", "origin/main")
        theirs = {f: at("origin/main", f, None) for f in FILES}
        merged = {
            "history.json": merge_history(base["history.json"] or [], ours["history.json"] or [],
                                          theirs["history.json"] or []),
            "queue.json": merge_queue(base["queue.json"] or [], ours["queue.json"] or [], theirs["queue.json"] or []),
            "attempts.json": merge_attempts(ours["attempts.json"] or {}, theirs["attempts.json"] or {}),
            "trends.json": merge_trends(ours["trends.json"] or {}, theirs["trends.json"] or {}),
        }
        changed = []
        for f, data in merged.items():
            if ours[f] is None and theirs[f] is None:
                continue
            if data != theirs[f]:
                (CH / f).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                changed.append(f"channel/{f}")
        if not changed:
            print("[channel] origin already has everything")
            return 0
        git("add", *changed)
        git("commit", "-q", "-m", args.message)
        r = subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"[channel] saved {', '.join(changed)}")
            return 0
        print(f"[channel] push rejected (attempt {attempt + 1}), merging again: {r.stderr.strip()[:200]}")
        time.sleep(5 + 5 * attempt)
    print("::error title=頻道紀錄沒有存成功::channel/*.json could not be pushed after 5 attempts")
    return 1


if __name__ == "__main__":
    sys.exit(main())
