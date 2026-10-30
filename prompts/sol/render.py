#!/usr/bin/env python3
"""Fill {{KEY}} placeholders in a Sol prompt.

    python3 -I render.py TEMPLATE [BRIEF.md] [KEY=VALUE | KEY=@FILE ...] > prompt.md

A brief is a markdown file whose `## KEY` sections (KEY in capitals, e.g.
`## TASK`) give the values; the text under each heading, trimmed, is the
value. KEY=VALUE arguments override the brief; KEY=@FILE reads the value
from FILE. Exits 1 and names the keys when any placeholder is left unfilled,
so a half-filled prompt is never launched.
"""
import re
import sys

PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
SECTION = re.compile(r"^## ([A-Z][A-Z0-9_]*)\s*$")


def read_brief(path):
    values, key, lines = {}, None, []
    in_comment = False
    for line in open(path, encoding="utf-8").read().splitlines():
        if "<!--" in line and "-->" not in line:
            in_comment = True
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        line = re.sub(r"\s*<!--.*?-->", "", line)
        if not line.strip() and "<!--" not in line and lines and not lines[-1].strip():
            continue
        m = SECTION.match(line)
        if m:
            if key:
                values[key] = "\n".join(lines).strip()
            key, lines = m.group(1), []
        elif key:
            lines.append(line)
    if key:
        values[key] = "\n".join(lines).strip()
    return values


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    template = open(argv[0], encoding="utf-8").read()
    values = {}
    for arg in argv[1:]:
        if "=" in arg and re.match(r"[A-Z][A-Z0-9_]*=", arg):
            key, val = arg.split("=", 1)
            if val.startswith("@"):
                val = open(val[1:], encoding="utf-8").read().strip()
            values[key] = val
        else:
            values = {**read_brief(arg), **values}
    missing = sorted({k for k in PLACEHOLDER.findall(template) if not values.get(k)})
    if missing:
        print("render.py: unfilled: " + ", ".join(missing), file=sys.stderr)
        return 1
    sys.stdout.write(PLACEHOLDER.sub(lambda m: values[m.group(1)], template))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
