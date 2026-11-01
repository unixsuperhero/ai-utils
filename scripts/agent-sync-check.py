#!/usr/bin/env python3
"""Check shared agent rules; --write refreshes marked copies inside this repo.

Default is read-only and has no dependencies. --upstream additionally checks the
reviewed external family/global/Claude UX sources; it never writes those files.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "workflow": "agents/rules/workflow.md",
    "lane": "agents/ofam-lane.md",
    "planner": "agents/ofam-planner.md",
    "ux-review": "agents/rules/ux-review.md",
    "ux-apply": "agents/rules/ux-apply.md",
}
TARGETS = {
    "agents/ofam-lane.md": ("workflow",),
    "agents/ofam-planner.md": ("workflow",),
    "prompts/sol/lane.md": ("workflow", "lane", "ux-apply"),
    "prompts/sol/planner.md": ("workflow", "planner"),
    "prompts/sol/ux-review.md": ("workflow", "ux-review"),
    "agents/omp/ofam-lane.md": ("workflow", "lane"),
    "agents/omp/ofam-planner.md": ("workflow", "planner"),
    "agents/omp/ux-reviewer.md": ("workflow", "ux-review"),
    "agents/omp/ux-applier.md": ("workflow", "lane", "ux-apply"),
}


def span(text, name, path):
    begin, end = (f"<!-- agent-sync:{name}:{suffix} -->" for suffix in ("begin", "end"))
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(f"{path}: expected exactly one {name} begin/end pair")
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    if stop < start or not text[start:stop].strip():
        raise ValueError(f"{path}: empty or reversed {name} block")
    return start, stop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="refresh marked copies from canonical sources")
    parser.add_argument("--upstream", action="store_true", help="fail when reviewed home-directory sources changed or are missing")
    args = parser.parse_args()
    try:
        sources = {}
        for name, path in SOURCES.items():
            text = (ROOT / path).read_text()
            if name in ("lane", "planner"):
                start, stop = span(text, name, path)
                text = text[start:stop]
            if not text.strip():
                raise ValueError(f"{path}: empty source")
            sources[name] = "\n" + text.strip() + "\n"
        errors, count = [], 0
        pending = {}
        for path, names in TARGETS.items():
            text = (ROOT / path).read_text()
            actual_names = re.findall(r"<!-- agent-sync:([\w-]+):begin -->", text)
            expected_names = set(names) | ({"lane"} if path == SOURCES["lane"] else set()) | ({"planner"} if path == SOURCES["planner"] else set())
            if set(actual_names) != expected_names or len(actual_names) != len(expected_names):
                raise ValueError(f"{path}: unexpected or duplicate shared blocks: {actual_names}")
            for name in names:
                start, stop = span(text, name, path)
                expected, actual = sources[name], text[start:stop]
                if actual != expected:
                    if args.write:
                        text = text[:start] + expected + text[stop:]
                    else:
                        errors.append(f"{path}: {name} differs from {SOURCES[name]}")
                        print("".join(difflib.unified_diff(expected.splitlines(True), actual.splitlines(True), fromfile=SOURCES[name], tofile=path)), file=sys.stderr)
                count += 1
            pending[path] = text
        # Verify native metadata as well as the shared prose, without a YAML dependency.
        for path, text in pending.items():
            if not path.startswith("agents/omp/"):
                continue
            if not text.startswith("---\n") or "\n---\n" not in text[4:]:
                raise ValueError(f"{path}: missing YAML frontmatter")
            meta = text.split("---\n", 2)[1]
            expected_meta = {
                "name": Path(path).stem,
                "model": "openai-codex/gpt-6.1-sol",
                "thinkingLevel": "high",
                "spawns": "[]",
                "prewalk": "false",
            }
            for key, value in expected_meta.items():
                if re.findall(rf"^{re.escape(key)}: (.+)$", meta, re.M) != [value]:
                    errors.append(f"{path}: expected {key}: {value}")
        for path in (ROOT / "prompts/sol").glob("*.md"):
            if "gpt-6-sol" in path.read_text():
                errors.append(f"{path.relative_to(ROOT)}: stale Sol model id")
        if args.upstream:
            for path, reviewed in json.loads((ROOT / "agents/rules/upstreams.json").read_text()).items():
                current = hashlib.sha256(Path(path).expanduser().read_bytes()).hexdigest()
                if current != reviewed["sha256"]:
                    errors.append(f"{path}: changed since review; reconcile {reviewed['reviewed_for']} before updating its digest")
        if errors:
            print("agent-sync-check: FAIL\n" + "\n".join(errors), file=sys.stderr)
            return 1
        if args.write:
            for path, text in pending.items():
                if (ROOT / path).read_text() != text:
                    (ROOT / path).write_text(text)
        print(f"agent-sync-check: PASS ({count} shared blocks; 4 omp model/thinking pins" + ("; upstream sources reviewed" if args.upstream else "") + ")")
        return 0
    except (OSError, ValueError) as exc:
        print(f"agent-sync-check: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
