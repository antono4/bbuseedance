#!/usr/bin/env python3
"""pipeline_tracker.py — Continuous-pipeline job tracker for seedane-2.5-30s.
Built-in tools only (text_to_video / image_to_video), FORCED model seedance_2.5.
TRUE model capability: duration [4, 30] seconds (legacy 15s cap REJECTED).
No API key. Video Extension fallback available if tool layer still limits.

Dispatch: next call immediately after previous returns OR 5s after previous dispatch.
State: /tmp/seedane_2_5_30s_pipeline.json
Log:   /tmp/seedane_2_5_30s_pipeline.log

Subcommands:
  init | enqueue | dispatch-next | mark <id> <status> [--url --error --attempts]
  | status | summary
"""
from __future__ import annotations
import argparse, json, sys, time
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path("/tmp/seedane_2_5_30s_pipeline.json")
LOG_FILE = Path("/tmp/seedane_2_5_30s_pipeline.log")
VALID_STATUSES = {"pending", "dispatched", "done", "failed", "retry",
                  "extension_pending", "extension_dispatched"}
FORCED_MODEL = "seedance_2.5"
TRUE_DURATION_MIN = 4
TRUE_DURATION_MAX = 30
LEGACY_TOOL_CAP = 15  # informational only — not enforced by this skill


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(msg):
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))


def clamp_duration(value):
    """Clamp to TRUE model range [4, 30], NOT the legacy 15s cap."""
    v = int(value)
    if v < TRUE_DURATION_MIN:
        log(f"duration {v}s raised to model min {TRUE_DURATION_MIN}s")
        return TRUE_DURATION_MIN
    if v > TRUE_DURATION_MAX:
        log(f"duration {v}s capped to model max {TRUE_DURATION_MAX}s")
        return TRUE_DURATION_MAX
    return v


def cmd_init():
    s = {
        "pipeline_id": f"pipe_{int(time.time())}",
        "model": FORCED_MODEL,
        "skill": "seedane-2.5-30s",
        "true_duration_range": [TRUE_DURATION_MIN, TRUE_DURATION_MAX],
        "legacy_tool_cap_note": f"{LEGACY_TOOL_CAP}s — informational only, NOT enforced",
        "started_at": now_iso(),
        "jobs": {}
    }
    save_state(s)
    log(f"initialized (model={FORCED_MODEL}, true duration [{TRUE_DURATION_MIN},{TRUE_DURATION_MAX}]s, built-in tools only, no api key)")
    print(f"State -> {STATE_FILE}")
    return 0


def cmd_enqueue(mode, prompt, ratio, duration, image_urls, needs_extension=False):
    s = load_state() or {
        "pipeline_id": f"pipe_{int(time.time())}",
        "model": FORCED_MODEL,
        "skill": "seedane-2.5-30s",
        "true_duration_range": [TRUE_DURATION_MIN, TRUE_DURATION_MAX],
        "started_at": now_iso(),
        "jobs": {}
    }
    jid = f"job_{len(s['jobs']) + 1:02d}"
    clamped = clamp_duration(duration)
    s["jobs"][jid] = {
        "status": "pending",
        "attempts": 0,
        "url": None,
        "error": None,
        "mode": mode,
        "prompt": prompt,
        "ratio": ratio,
        "duration_requested": int(duration),
        "duration_clamped": clamped,
        "model_version": FORCED_MODEL,
        "enqueued_at": now_iso(),
        "needs_extension_fallback": bool(needs_extension)
    }
    if image_urls:
        s["jobs"][jid]["image_urls"] = image_urls
    save_state(s)
    log(f"enqueued {jid} ({mode}) duration_requested={duration}s clamped={clamped}s")
    print(f"Enqueued {jid}. Duration clamped to true model range: {clamped}s.")
    print("Dispatch: next immediately on return OR 5s after dispatch.")
    return 0


def cmd_dispatch_next():
    s = load_state()
    if not s:
        print("No state. Run 'init'.")
        return 1
    pending = [jid for jid, j in s["jobs"].items()
               if j["status"] in ("pending", "retry", "extension_pending")]
    if not pending:
        print("No pending jobs.")
        return 0
    jid = pending[0]
    j = s["jobs"][jid]
    j["status"] = "dispatched" if j["status"] != "extension_pending" else "extension_dispatched"
    j["dispatched_at"] = now_iso()
    save_state(s)
    log(f"dispatching {jid} ({j['mode']}) model={FORCED_MODEL} duration={j['duration_clamped']}s")
    print(json.dumps({"id": jid, **j}, ensure_ascii=False, indent=2))
    return 0


def cmd_mark(job_id, status, url, error, attempts):
    if status not in VALID_STATUSES:
        print(f"status must be one of {VALID_STATUSES}")
        return 1
    s = load_state()
    if not s or job_id not in s.get("jobs", {}):
        print(f"job '{job_id}' not found")
        return 1
    j = s["jobs"][job_id]
    j["status"] = status
    j["updated_at"] = now_iso()
    if url is not None:
        j["url"] = url
    if error is not None:
        j["error"] = error
    if attempts is not None:
        j["attempts"] = attempts
    save_state(s)
    msg = f"job {job_id} -> {status}"
    if url:
        msg += f" url={url}"
    if error:
        msg += f" error={error}"
    log(msg)
    print(f"Marked {job_id} = {status}")
    return 0


def print_status(s):
    jobs = s.get("jobs", {})
    counts = {st: 0 for st in VALID_STATUSES}
    for j in jobs.values():
        st = j.get("status", "pending")
        counts[st] = counts.get(st, 0) + 1
    print(f"Pipeline {s.get('pipeline_id', '?')}")
    print(f"  skill={s.get('skill', 'seedane-2.5-30s')}  model={s.get('model', FORCED_MODEL)}")
    print(f"  true_duration_range={s.get('true_duration_range', [TRUE_DURATION_MIN, TRUE_DURATION_MAX])}s")
    print(f"  total={len(jobs)}  " +
          "  ".join(f"{k}={v}" for k, v in counts.items() if v))
    for jid, j in jobs.items():
        if j.get("status") in ("done", "failed"):
            extra = ""
            if j.get("url"):
                extra = f" url={j['url']}"
            elif j.get("error"):
                extra = f" error={j['error']}"
            print(f"    {jid}: {j['status']} dur={j.get('duration_clamped', '?')}s{extra}")


def cmd_status():
    s = load_state()
    if not s:
        print("No active pipeline.")
        return 0
    print_status(s)
    return 0


def cmd_summary():
    s = load_state()
    if not s:
        print("No state.")
        return 0
    print_status(s)
    if any(j.get("url") for j in s["jobs"].values()):
        print("\nDelivered videos:")
        for jid, j in s["jobs"].items():
            if j.get("url"):
                print(f"  {jid}: dur={j.get('duration_clamped', '?')}s -> {j['url']}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Pipeline tracker for seedane-2.5-30s (true 4-30s capability)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    e = sub.add_parser("enqueue")
    e.add_argument("--mode", choices=["text_to_video", "image_to_video"],
                   default="text_to_video")
    e.add_argument("--prompt", required=True)
    e.add_argument("--ratio", default="16:9")
    e.add_argument("--duration", type=int, default=TRUE_DURATION_MAX,
                   help=f"Duration in seconds. True model range: [{TRUE_DURATION_MIN}, {TRUE_DURATION_MAX}]. Default = max capability.")
    e.add_argument("--image-url", action="append", dest="image_urls")
    e.add_argument("--needs-extension", action="store_true", dest="needs_extension",
                   help="Flag that this job may need Video Extension fallback")

    sub.add_parser("dispatch-next")

    m = sub.add_parser("mark")
    m.add_argument("job_id")
    m.add_argument("status")
    m.add_argument("--url")
    m.add_argument("--error")
    m.add_argument("--attempts", type=int)

    sub.add_parser("status")
    sub.add_parser("summary")

    a = ap.parse_args()

    if a.cmd == "init":
        return cmd_init()
    if a.cmd == "enqueue":
        return cmd_enqueue(a.mode, a.prompt, a.ratio, a.duration,
                           a.image_urls, a.needs_extension)
    if a.cmd == "dispatch-next":
        return cmd_dispatch_next()
    if a.cmd == "mark":
        return cmd_mark(a.job_id, a.status, a.url, a.error, a.attempts)
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "summary":
        return cmd_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
