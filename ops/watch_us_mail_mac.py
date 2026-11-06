"""Run on the owner's Mac; fetch public sanitized records, notify once per ID."""

import argparse
import json
import platform
import subprocess
import time
from pathlib import Path

APPLE_SCRIPT = """on run argv
display notification (item 1 of argv) with title "米国情報" sound name "Glass"
end run"""


def announce(summary, speak=False):
    if len(summary) != 40 or any(c in summary for c in "\r\n"):
        raise ValueError("40-character Japanese summary required")
    # Untrusted text is an argument, never interpolated into executable code.
    subprocess.run(["osascript", "-e", APPLE_SCRIPT, summary], check=True)
    if speak:
        subprocess.run(["say", "--", summary], check=True)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout


def scan(repo, state_path, speak=False):
    git(repo, "fetch", "--quiet", "origin", "main")
    paths = [
        p
        for p in git(
            repo, "ls-tree", "-r", "--name-only", "FETCH_HEAD", "data/knowledge/us/"
        ).splitlines()
        if p.endswith(".json")
    ]
    state_path = Path(state_path)
    first = not state_path.exists()
    seen = set() if first else set(json.loads(state_path.read_text()))
    for path in paths:
        doc = json.loads(git(repo, "show", "FETCH_HEAD:" + path))
        key = doc["id"]
        if key in seen:
            continue
        if first or not doc.get("notification_eligible"):
            seen.add(key)
            continue
        announce(doc["summary_ja_40"], speak)
        seen.add(key)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(sorted(seen)))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sorted(seen)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--state",
        type=Path,
        default=Path.home() / "Library/Application Support/invest-mail/seen.json",
    )
    parser.add_argument("--speak", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--interval", type=int, default=20)
    args = parser.parse_args()
    if platform.system() != "Darwin":
        parser.error("Run this notification script on macOS, not a cloud runner")
    if args.test:
        announce(
            "米国情報通知テストです。実際の市場ニュースではなく配信と音声の動作を確認します。",
            args.speak,
        )
        return
    if args.interval < 20:
        parser.error("interval must be at least 20 seconds")
    while True:
        try:
            scan(args.repo.resolve(), args.state, args.speak)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            print(f"Notification retry pending: {type(exc).__name__}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
