#!/usr/bin/env python3
"""Claude Code PreToolUse hook: refuse a Bash command whose `pgrep -f` /
`pkill -f` pattern has no character class.

Such a pattern also matches every shell whose command line holds it (the
wait loop's own shell included), so `until ! pgrep -f "x y"` never ends.
Rule: ~/hub/ai/instructions/AGENTS.md, "Waiting on processes".

Reads the hook JSON on stdin; exit 2 with a reason on stderr blocks the call.
"""
import json
import re
import shlex
import sys

FLAGGED = re.compile(r"\b(pgrep|pkill)\b")
TAKES_VALUE = {"-u", "-U", "-g", "-G", "-P", "-t", "-F", "-s", "-d", "-J"}


def patterns(cmd: str):
    """Yield the pattern argument of every pgrep/pkill call that uses -f."""
    # Tokenize the whole line first, so text inside quotes (a message that
    # mentions pgrep) stays one word and is never read as a command.
    lex = shlex.shlex(cmd.replace("$(", " ( ").replace("`", " ( "), posix=True, punctuation_chars=";&|()\n")
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        tokens = cmd.split()
    segments, cur = [], []
    for t in tokens:
        if t and set(t) <= set(";&|()\n"):
            segments.append(cur)
            cur = []
        else:
            cur.append(t)
    segments.append(cur)
    for words in segments:
        for i, w in enumerate(words):
            if w not in ("pgrep", "pkill") and not w.endswith(("/pgrep", "/pkill")):
                continue
            args = words[i + 1:]
            if not any(a.startswith("-") and "f" in a.lstrip("-") and not a.startswith("--") for a in args):
                continue
            it = iter(args)
            for a in it:
                if a in TAKES_VALUE:
                    next(it, None)  # the option's value, not the pattern
                    continue
                if a.startswith("-"):
                    continue  # a flag, or a pkill signal such as -9 / -TERM
                yield a
                break


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not FLAGGED.search(cmd):
        return 0
    bad = [p for p in patterns(cmd) if "[" not in p]
    if not bad:
        return 0
    fixed = re.sub(r"(\w)", r"[\1]", bad[0], count=1)
    print(
        f"pgrep-guard: pattern {bad[0]!r} has no character class, so it matches the "
        f"shell running it and a wait loop never ends. Bracket one character "
        f"(e.g. {fixed!r}) or wait on a PID with `while kill -0 \"$pid\"`. "
        "Rule: ~/hub/ai/instructions/AGENTS.md, 'Waiting on processes'.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
