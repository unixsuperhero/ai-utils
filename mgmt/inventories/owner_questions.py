#!/usr/bin/env python3
"""Inventory the open owner questions in a plans folder, as an mgmt inventory.

  python3 -I owner_questions.py scan [--root DIR] [--out DIR] [--include-answered]
  python3 -I owner_questions.py decisions SESSION [--root DIR] [--date YYYY-MM-DD]

scan finds sections titled "Owner questions", "Open questions" or "Questions for
the owner" (and "Open owner decisions") in DIR/*.md and DIR/plans/*.md, takes
their numbered items (bullets when a section has none), and splits each into the
question and its "Recommended:"/"Recommend"/"Proposal:" text. A question counts as
answered when its section heading says "answered", the section holds an
"Owner answers"/"Owner decisions" subheading, or the plan has a numbered
"Owner decisions" section with an item of the same number. Answered questions are
left out unless --include-answered. Writes OUT/inventory.json (default
~/.local/state/mgmt/owner-questions-<date>/).

decisions reads a reviewed mgmt session and prints, per plan, the
"## Owner decisions (<date>)" section to paste above that plan's questions.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys

QUESTION_HEAD = re.compile(r'owner questions|open questions|questions for the owner|open owner decisions', re.I)
DECISION_HEAD = re.compile(r'owner (decisions|answers)|decision \(owner', re.I)
HEADING = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
NUMBERED = re.compile(r'^ {0,3}(\d+)[.)]\s+(.*)$')
BULLET = re.compile(r'^ {0,1}[-*]\s+(.*)$')
REC = re.compile(r'\[?\s*(?:\*{1,2}|_)?\s*\b(Recommended|Recommend|Proposal|Proposed)\b\s*:?\s*', re.I)
LONE_STAR = re.compile(r'(?<!\*)\*(?!\*)')
ACTIONS = ['yes', 'no', 'later', 'moot']


def headings(lines):
    out = []
    fence = False
    for n, line in enumerate(lines):
        if line.lstrip().startswith('```'):
            fence = not fence
        m = None if fence else HEADING.match(line)
        if m:
            out.append((n, len(m.group(1)), m.group(2)))
    return out


def section_end(lines, heads, index):
    start, level, _ = heads[index]
    for n, lvl, _ in heads[index + 1:]:
        if lvl <= level:
            return n
    return len(lines)


def list_items(lines, start, end, pattern):
    """Return (number, first_line_index, text) for top-level list items in lines[start:end]."""
    items, n = [], start
    while n < end:
        m = pattern.match(lines[n])
        if not m or HEADING.match(lines[n]):
            n += 1
            continue
        first, body = n, [lines[n]]
        n += 1
        while n < end:
            line = lines[n]
            if HEADING.match(line) or pattern.match(line):
                break
            if not line.strip():
                ahead = next((l for l in lines[n + 1:end] if l.strip()), '')
                if not ahead.startswith((' ', '\t')):
                    break
            body.append(line)
            n += 1
        number = int(m.group(1)) if pattern is NUMBERED else len(items) + 1
        items.append((number, first, '\n'.join(body).strip()))
    return items


def strip_emphasis(text):
    parts = text.split('`')
    return '`'.join(p if i % 2 else LONE_STAR.sub('', p) for i, p in enumerate(parts))


def split_item(raw):
    """Return (title, question, recommendation) from a list item's text."""
    text = re.sub(r'^ {0,3}(\d+[.)]|[-*])\s+', '', raw, count=1)
    flat = ' '.join(l.strip() for l in text.splitlines())
    m = REC.search(flat)
    question, rec = (flat[:m.start()], flat[m.end():]) if m else (flat, '')
    question = strip_emphasis(question).strip().rstrip('[').strip()
    rec = strip_emphasis(rec).strip().rstrip(']').strip()
    bold = re.match(r'\*\*(.+?)\*\*', question)
    title = bold.group(1).strip() if bold else re.split(r'(?<=[?.])\s', question, maxsplit=1)[0]
    title = title.replace('**', '')
    if len(title) > 160:
        title = title[:157].rstrip() + '...'
    return title or question[:160], question, rec


def git(root, *args):
    try:
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                              timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def scan(root, include_answered=False):
    files = sorted(set(root.glob('*.md')) | set(root.glob('plans/*.md')))
    questions = []
    for path in files:
        lines = path.read_text(encoding='utf-8').splitlines()
        heads = headings(lines)
        rel = path.relative_to(root).as_posix()
        plan = next((t for _, lvl, t in heads if lvl == 1), rel)
        covered, unnumbered = set(), []
        q_sections = []
        for i, (n, lvl, text) in enumerate(heads):
            if QUESTION_HEAD.search(text):
                q_sections.append(i)
            elif DECISION_HEAD.search(text):
                end = section_end(lines, heads, i)
                nums = [num for num, _, _ in list_items(lines, n + 1, end, NUMBERED)]
                covered.update(nums)
                if not nums:
                    unnumbered.append(n + 1)
        for i in q_sections:
            n, lvl, text = heads[i]
            end = section_end(lines, heads, i)
            inner = [h for h in heads if n < h[0] < end]
            answers_sub = next((h for h in inner if DECISION_HEAD.search(h[2])), None)
            stop = answers_sub[0] if answers_sub else end
            found = list_items(lines, n + 1, stop, NUMBERED) or list_items(lines, n + 1, stop, BULLET)
            for number, first, raw in found:
                title, question, rec = split_item(raw)
                if 'answered' in text.lower():
                    answered = 'the section heading says answered'
                elif answers_sub:
                    answered = f'owner answers at line {answers_sub[0] + 1}'
                elif number in covered:
                    answered = f'owner decision {number} in this plan'
                else:
                    answered = ''
                ident = 'oq-' + hashlib.sha256(f'{rel}\0{text}\0{number}'.encode()).hexdigest()[:12]
                questions.append(dict(id=ident, path=path, rel=rel, line=first + 1, plan=plan, section=text,
                                      number=number, title=title, question=question, recommendation=rec,
                                      raw=raw, answered=answered,
                                      unnumbered_decisions=unnumbered))
    if not include_answered:
        questions = [q for q in questions if not q['answered']]
    return questions


def inventory(root, questions, include_answered):
    status = git(root, 'status', '--porcelain', '--', '.')
    items = []
    for q in questions:
        details = [f"Plan: {q['plan']} ({q['rel']})", f"Section: {q['section']}, question {q['number']}", '',
                   q['raw']]
        if q['unnumbered_decisions']:
            details += ['', 'Note: this plan has an unnumbered owner decision section (line '
                        + ', '.join(map(str, q['unnumbered_decisions']))
                        + '); check whether it already settles this question.']
        if q['answered']:
            details += ['', 'Already answered: ' + q['answered']]
        item = dict(id=q['id'], title=f"{q['rel'].removeprefix('plans/')} #{q['number']}: {q['title']}",
                    source=f"{q['path']}:{q['line']}", details='\n'.join(details))
        if q['recommendation']:
            item.update(recommendation=q['recommendation'], recommended_action='yes')
        items.append(item)
    return dict(
        title='Owner questions in ' + root.name,
        scope=f'Open owner questions in {root}/*.md and {root}/plans/*.md'
              + ('' if include_answered else '; questions already answered in their plan are left out')
              + '. Applying writes an "Owner decisions (date)" section into each plan.',
        default_action='yes', actions=ACTIONS, kind='owner-questions',
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        origin=dict(repo=git(root, 'rev-parse', '--show-toplevel'), commit=git(root, 'rev-parse', 'HEAD'),
                    dirty=bool(status)),
        items=items)


def decisions(session, root, date):
    data = json.loads(session.read_text())
    known = {q['id']: q for q in scan(root, include_answered=True)}
    by_plan, missing = {}, []
    for item in data['items']:
        if not item['action'] or (item['action'] == 'ask' and data.get('ask', True) is not False):
            continue  # undecided, or asked and still waiting for the agent's answer
        q = known.get(item.get('id'))
        if not q:
            missing.append(item.get('id') or item['title'])
            continue
        by_plan.setdefault(q['rel'], []).append((q, item))
    for rel, rows in sorted(by_plan.items()):
        print(f'<!-- {rel}: insert above "{rows[0][0]["section"]}" -->')
        print(f'## Owner decisions ({date})\n')
        for q, item in sorted(rows, key=lambda r: r[0]['number']):
            action, note = item['action'], item['note'].strip()
            if action == 'yes':
                text = (q['recommendation'] or 'Yes.') + (f' {note}' if note else '')
            elif action == 'later':
                text = 'Later; still open.' + (f' {note}' if note else '')
            elif action == 'moot':
                text = 'Moot; no longer needed.' + (f' {note}' if note else '')
            elif action == 'no':
                text = 'No, not the recommendation.' + (f' {note}' if note else ' (no reason given)')
            else:
                text = f'{action}.' + (f' {note}' if note else '')
            text = text[:1].upper() + text[1:]
            print(f"{q['number']}. **{q['title'].rstrip('?.')}.** {text}")
        print()
    for m in missing:
        print(f'warning: {m} not found in {root}; its question moved or changed', file=sys.stderr)
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scan')
    s.add_argument('--root', type=pathlib.Path, default=pathlib.Path('~/hub/o-plans'))
    s.add_argument('--out', type=pathlib.Path)
    s.add_argument('--include-answered', action='store_true')
    d = sub.add_parser('decisions')
    d.add_argument('session', type=pathlib.Path)
    d.add_argument('--root', type=pathlib.Path, default=pathlib.Path('~/hub/o-plans'))
    d.add_argument('--date', default=datetime.date.today().isoformat())
    a = ap.parse_args(argv)
    root = a.root.expanduser().resolve()
    if a.command == 'decisions':
        return decisions(a.session.expanduser().resolve(), root, a.date)
    questions = scan(root, a.include_answered)
    if not questions:
        print('No open owner questions found under ' + str(root), file=sys.stderr)
        return 1
    out = (a.out or pathlib.Path('~/.local/state/mgmt') / f'owner-questions-{datetime.date.today().isoformat()}').expanduser()
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'inventory.json'
    target.write_text(json.dumps(inventory(root, questions, a.include_answered), indent=2, ensure_ascii=False) + '\n')
    counts = {}
    for q in questions:
        counts[q['rel']] = counts.get(q['rel'], 0) + 1
    for rel, count in sorted(counts.items()):
        print(f'{count:3}  {rel}')
    print(f'{len(questions):3}  total -> {target}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
