#!/usr/bin/env python3
"""Audit agent rights across mtm and the family tools, as an mgmt inventory.

  python3 -I rights_audit.py scan [--out DIR] [--mtm-bin PATH] [--tool PATH]...
                                  [--judged FILE] [--path DIR:DIR]

scan runs `mtm catalog` and `mtm ochazuke agent rights`, and `catalog` of every
family tool (the executables o-* on PATH, plus nabe; --tool adds or replaces
them), each with temp --data/--config, HOME, XDG_* and TMPDIR directories and a
scrubbed environment, so it never reads the owner's data. help-prototype and
json-pre are excluded; a symlink or a copy with the same nouns counts once.
Rows are joined on verb: mtm's rows are NOUN.VERB, a tool's are TOOL.NOUN.VERB,
TOOL being the executable's name without o- (as mtm mounts it); the tool's
ochazuke.* framework nouns are mtm's and are skipped.

A verb is a hit when its name, its destructive flag, its confirm prompt, its
right (confirm) or its description suggests that it removes something. The word
lists below are for review only: they decide what a human looks at, never what
an agent may do. Every hit must be judged in rights_audit_judged.json (beside
this file): {"rows": {VERB: {"right": allow|confirm|never, "reason": "..."}}}.
The report lists unjudged hits, rows whose right differs from the judged one,
judged rows no longer in any catalog, and allow/confirm/never totals per tool.

Writes OUT/report.md, OUT/result.json and OUT/inventory.json (the findings, as
an mgmt inventory), default ~/.local/state/mgmt/rights-audit-<date>/. Exits 1
only when a judged row differs or an unjudged hit exists.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
EXCLUDED = {'help-prototype', 'json-pre', 'mtm-help-prototype', 'o-json-pre'}
RIGHTS = ('allow', 'confirm', 'never')
ACTIONS = ['judged', 'fix', 'later']

# Review aids, never a gate: what a human is shown, not what an agent may do.
NAME_WORDS = ('delete remove rm forget clear kill reset purge prune drop wipe destroy trash erase truncate '
              'unset discard clean cleanup gc empty reap close cancel stop unbind detach deregister '
              'unregister uninstall revert overwrite').split()
DESC_WORDS = ('delet remov forget clear kill reset prun drop wipe purg destroy trash eras discard overwrit '
              'replace force merge squash rebase uninstall empties empty unlink stash hard revert abandon '
              'terminate shut bootout retire').split()
NAME_RE = re.compile(r'(^|[.-])(' + '|'.join(NAME_WORDS) + r')([.-]|$)')
DESC_RE = re.compile(r'\b(' + '|'.join(DESC_WORDS) + ')', re.I)


# --- running the programs -------------------------------------------------

def clean_env(root):
    """A scrubbed environment: temp HOME/XDG/TMPDIR under root, nothing of the owner's."""
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL') if k in os.environ}
    dirs = {name: root / name for name in ('home', 'config', 'state', 'share', 'tmp')}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(dirs['home']), XDG_CONFIG_HOME=str(dirs['config']), XDG_STATE_HOME=str(dirs['state']),
               XDG_DATA_HOME=str(dirs['share']), TMPDIR=str(dirs['tmp']), TERM='dumb')
    return env


def run_json(argv, env, cwd):
    """Run argv with no stdin and a timeout; return (parsed JSON or None, error text)."""
    try:
        p = subprocess.run(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f'{type(e).__name__}: {e}'
    if p.returncode:
        return None, f'exit {p.returncode}: ' + p.stderr.decode(errors='replace').strip()[:200]
    try:
        return json.loads(p.stdout), ''
    except ValueError as e:
        return None, f'not JSON: {e}'


def find_tools(path_dirs, extra=()):
    """Return {label: path}: o-* executables in path_dirs, nabe, and any extra paths."""
    found = {}
    for d in path_dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            p = os.path.join(d, name)
            if (name.startswith('o-') or name == 'nabe') and name not in found \
                    and os.path.isfile(p) and os.access(p, os.X_OK):
                found[name] = p
    for p in extra:
        found[os.path.basename(p)] = p
    return found


def nouns_hash(catalog):
    return hashlib.sha1(json.dumps(catalog.get('nouns', []), sort_keys=True).encode()).hexdigest()


def load_world(mtm_bin, tools, runner=run_json):
    """Run everything. Returns (mtm_catalog, mtm_rights, {tool: catalog}, notes)."""
    notes = []
    with tempfile.TemporaryDirectory(prefix='rights-audit-') as tmp:
        root = pathlib.Path(tmp)
        env = clean_env(root)
        work = root / 'cwd'
        work.mkdir()
        base = [mtm_bin, '-data', str(root / 'mtm.db'), '-config', str(root / 'config')]
        catalog, err = runner(base + ['catalog'], env, work)
        if catalog is None:
            raise SystemExit(f'mtm catalog failed: {err}')
        rights, err = runner(base + ['ochazuke', 'agent', 'rights'], env, work)
        if rights is None:
            raise SystemExit(f'mtm ochazuke agent rights failed: {err}')
        out, seen_real, seen_hash = {}, {}, {}
        for label, path in sorted(tools.items(), key=lambda kv: (os.path.islink(kv[1]), kv[0])):
            real = os.path.realpath(path)
            if label in EXCLUDED or os.path.basename(real) in EXCLUDED:
                notes.append(f'{label}: excluded')
                continue
            if real in seen_real:
                notes.append(f'{label}: same file as {seen_real[real]}')
                continue
            seen_real[real] = label
            cat, err = runner([path, 'catalog'], env, work)
            if cat is None or not isinstance(cat, dict) or 'nouns' not in cat:
                notes.append(f'{label}: catalog failed ({err or "no nouns"})')
                continue
            h = nouns_hash(cat)
            if h in seen_hash:
                notes.append(f'{label}: same catalog as {seen_hash[h]}')
                continue
            seen_hash[h] = label
            out[label[2:] if label.startswith('o-') else label] = cat
    return catalog, rights, out, notes


# --- joining and scanning -------------------------------------------------

def make_row(src, key, v):
    return dict(src=src, verb=key, name=v.get('name', ''), right=v.get('agent') or '',
                destructive=bool(v.get('destructive')), prompt=str(v.get('confirm') or ''),
                history=v.get('history') or '', description=(v.get('description') or '')[:200])


def join(mtm_catalog, mtm_rights, tool_catalogs):
    """One row per verb. mtm's right is the one `agent rights` reports; a catalog that
    disagrees is noted in row['mismatch']. Tool rows carry the tool's own declaration."""
    rights = {r['verb']: r for r in mtm_rights}
    rows = []
    for n in mtm_catalog.get('nouns', []):
        for v in n.get('verbs', []):
            key = f"{n['name']}.{v['name']}"
            row = make_row('mtm', key, v)
            r = rights.get(key)
            if r:
                if row['right'] and row['right'] != r['right']:
                    row['mismatch'] = f"catalog says {row['right']}, rights says {r['right']}"
                row['right'], row['rule'] = r['right'], r.get('rule', '')
            rows.append(row)
    for tool, cat in sorted(tool_catalogs.items()):
        for n in cat.get('nouns', []):
            if n['name'].startswith('ochazuke.'):
                continue
            for v in n.get('verbs', []):
                rows.append(make_row(tool, f"{tool}.{n['name']}.{v['name']}", v))
    return rows


def hit_reasons(row):
    why = []
    if NAME_RE.search('.' + row['name']):
        why.append('name')
    if row['destructive']:
        why.append('destructive flag')
    if row['prompt']:
        why.append('prompt')
    if row['right'] == 'confirm':
        why.append('right confirm')
    if not why and row['history'] != 'fetch' and DESC_RE.search(row['description']):
        why.append('description')
    return why


def load_judged(path):
    data = json.loads(pathlib.Path(path).read_text())
    rows = data.get('rows', {})
    for k, v in rows.items():
        if v.get('right') not in RIGHTS or not v.get('reason', '').strip():
            raise SystemExit(f'{path}: row {k} needs a right ({"|".join(RIGHTS)}) and a reason')
    return rows


def audit(rows, judged):
    """Compare rows with judged rows. 'allow' is the right of a row with no declaration."""
    by_key = {r['verb']: r for r in rows}
    hits, unjudged, differs = [], [], []
    for r in rows:
        why = hit_reasons(r)
        j = judged.get(r['verb'])
        if why:
            hits.append(dict(r, why=why))
            if not j:
                unjudged.append(dict(r, why=why))
        if j and (r['right'] or 'allow') != j['right']:
            differs.append(dict(r, judged=j['right'], reason=j['reason']))
    stale = sorted(k for k in judged if k not in by_key)
    totals = {}
    for r in rows:
        t = totals.setdefault(r['src'], dict(allow=0, confirm=0, never=0, undeclared=0, verbs=0))
        t['verbs'] += 1
        right = r['right'] or 'allow'
        t[right] = t.get(right, 0) + 1
        if not r['right']:
            t['undeclared'] += 1
    return dict(rows=len(rows), hits=hits, unjudged=unjudged, differs=differs, stale=stale, totals=totals)


# --- output ---------------------------------------------------------------

def table(header, lines):
    out = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    out += ['| ' + ' | '.join(str(c).replace('|', '/').replace('\n', ' ') for c in l) + ' |' for l in lines]
    return out


def report(result, notes, mtm_bin, tools):
    t = result['totals']
    total = {k: sum(x[k] for x in t.values()) for k in ('verbs', 'allow', 'confirm', 'never', 'undeclared')}
    lines = ['# Agent rights audit', '',
             f"Generated {result['generated_at']}. mtm: `{mtm_bin}`; tools: {', '.join(sorted(tools))}.", '',
             f"{total['verbs']} verbs; {len(result['hits'])} hits; {len(result['unjudged'])} unjudged; "
             f"{len(result['differs'])} differ from the judged right; {len(result['stale'])} judged rows not found.", '',
             '## Totals per source', '']
    lines += table(['source', 'verbs', 'allow', 'confirm', 'never', 'undeclared (counted as allow)'],
                   [(s, x['verbs'], x['allow'], x['confirm'], x['never'], x['undeclared'])
                    for s, x in sorted(t.items(), key=lambda kv: (kv[0] != 'mtm', kv[0]))]
                   + [('total', total['verbs'], total['allow'], total['confirm'], total['never'], total['undeclared'])])
    lines += ['', '## Unjudged hits', '']
    lines += table(['verb', 'right', 'why', 'description'],
                   [(r['verb'], r['right'] or '-', ', '.join(r['why']), r['description'][:90]) for r in result['unjudged']]) \
        if result['unjudged'] else ['None.']
    lines += ['', '## Rows whose right differs from the judged one', '']
    lines += table(['verb', 'now', 'judged', 'reason'],
                   [(r['verb'], r['right'] or 'allow (undeclared)', r['judged'], r['reason']) for r in result['differs']]) \
        if result['differs'] else ['None.']
    lines += ['', '## Judged rows not in any catalog', ''] + ([f'- {k}' for k in result['stale']] or ['None.'])
    mism = [r for r in result['rows_all'] if r.get('mismatch')]
    if mism:
        lines += ['', '## mtm catalog and rights disagree', ''] + [f"- {r['verb']}: {r['mismatch']}" for r in mism]
    lines += ['', '## Notes', ''] + ([f'- {n}' for n in notes] or ['None.'])
    return '\n'.join(lines) + '\n'


def inventory(result, rows_root):
    items = []
    for kind, rows in (('unjudged', result['unjudged']), ('differs', result['differs'])):
        for r in rows:
            if kind == 'unjudged':
                title = f"Judge {r['verb']} (now {r['right'] or 'allow, undeclared'})"
                details = f"Hit by: {', '.join(r['why'])}.\n{r['description']}"
            else:
                title = f"{r['verb']} is {r['right'] or 'allow, undeclared'}, judged {r['judged']}"
                details = f"Judged reason: {r['reason']}\n{r['description']}"
            items.append(dict(id=hashlib.sha1(f"{kind}:{r['verb']}".encode()).hexdigest()[:12], title=title,
                              group=r['src'], source='rights_audit.py', details=details))
    return dict(title='Agent rights audit', scope='Verbs of mtm and the family tools judged against rights_audit_judged.json',
                default_action='judged', actions=ACTIONS, kind='rights-audit',
                groups=list(dict.fromkeys(i['group'] for i in items)),
                generated_at=result['generated_at'], items=items)


def scan(args, runner=run_json):
    mtm_bin = args.mtm_bin or shutil.which('mtm')
    if not mtm_bin:
        raise SystemExit('mtm not found; pass --mtm-bin')
    path_dirs = (args.path or os.environ.get('PATH', '')).split(os.pathsep)
    tools = find_tools([d for d in path_dirs if d], args.tool)
    judged = load_judged(args.judged)
    catalog, rights, tool_cats, notes = load_world(mtm_bin, tools, runner)
    rows = join(catalog, rights, tool_cats)
    result = audit(rows, judged)
    result['generated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    result['rows_all'] = rows
    out = (args.out or pathlib.Path('~/.local/state/mgmt') / f'rights-audit-{datetime.date.today().isoformat()}').expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.md').write_text(report(result, notes, mtm_bin, tool_cats))
    saved = {k: v for k, v in result.items() if k != 'rows_all'}
    saved.update(notes=notes, mtm_bin=mtm_bin, tools=sorted(tool_cats))
    (out / 'result.json').write_text(json.dumps(saved, indent=2, ensure_ascii=False) + '\n')
    (out / 'inventory.json').write_text(json.dumps(inventory(result, None), indent=2, ensure_ascii=False) + '\n')
    for s, x in sorted(result['totals'].items()):
        print(f"{x['verbs']:5}  {s}: allow {x['allow']}, confirm {x['confirm']}, never {x['never']}")
    print(f"{result['rows']:5}  verbs; {len(result['hits'])} hits, {len(result['unjudged'])} unjudged, "
          f"{len(result['differs'])} differ -> {out}")
    return 1 if result['unjudged'] or result['differs'] else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scan')
    s.add_argument('--out', type=pathlib.Path)
    s.add_argument('--mtm-bin')
    s.add_argument('--tool', action='append', default=[], help='an extra tool executable (repeatable)')
    s.add_argument('--path', help='directories to search for o-* tools, instead of PATH')
    s.add_argument('--judged', type=pathlib.Path, default=HERE / 'rights_audit_judged.json')
    a = ap.parse_args(argv)
    return scan(a)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
