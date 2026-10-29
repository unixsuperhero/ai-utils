#!/usr/bin/env python3
"""Persistent human review, followed by an assistant-executed action queue."""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('This session is open elsewhere. Close its review first.')
        yield


def load(path):
    data = json.loads(path.read_text())
    if data.get('version') != 1:
        raise ValueError('Unsupported session version')
    return data


def item_at(data, number):
    if number < 1 or number > len(data['items']):
        raise ValueError('Item number out of range')
    return data['items'][number - 1]


def display(data):
    print('\n' + data['title'])
    print('Scope: ' + data['scope'])
    for number, item in enumerate(data['items'], 1):
        selected = 'x' if item['action'] else ' '
        print(f"{number:3}. [{selected}] {item['title']} [{item['status']}]")
        if item['action']:
            print('         Action: ' + item['action'])
        if item['note']:
            print('         Note: ' + item['note'])


def change(data, number, action=None, note=None):
    item = item_at(data, number)
    if item['status'] in ('applying', 'done'):
        raise ValueError('Active/completed items are locked; record a result or create a new session')
    if action is not None:
        item['action'] = action
    if note is not None:
        item['note'] = note
    item['status'] = 'pending'
    item.pop('result', None)
    item.pop('context_changed', None)
    item.pop('new_reply', None)
    data['updated_at'] = now()


ITEM_FIELDS = ('title', 'source', 'details')
OPTIONAL_ITEM_FIELDS = ('id', 'recommendation', 'recommended_action', 'group')
OPTIONAL_FIELDS = ('kind', 'generated_at', 'origin', 'actions', 'ask', 'groups')
ASK = 'ask'
ROLES = ('owner', 'agent')


def asks(data):
    """Whether the built-in "ask" outcome is offered (inventory `ask: false` turns it off)."""
    return data.get('ask', True) is not False


def asking(data, item):
    """True when the owner chose "ask": the item is open, waiting for the agent's answer."""
    return asks(data) and item.get('action') == ASK


def is_decided(data, item):
    return bool(item.get('action')) and not asking(data, item)


def group_of(item):
    """The item's topic: its `group`, else its source file without a trailing :line."""
    if item.get('group'):
        return item['group']
    head, sep, tail = item['source'].rpartition(':')
    return head if sep and head and tail.replace('-', '').isdigit() else item['source']


def group_order(data):
    """Topics in display order: the inventory's `groups` first, then the rest as they first appear."""
    order = list(dict.fromkeys(data.get('groups') or []))
    for item in data['items']:
        if group_of(item) not in order:
            order.append(group_of(item))
    return order


def check_thread(thread):
    if not isinstance(thread, list) or not all(isinstance(m, dict) for m in thread):
        raise ValueError('Item thread must be a list of {role, text, at} objects')
    for message in thread:
        if message.get('role') not in ROLES:
            raise ValueError('Thread role must be "owner" or "agent"')
        if not isinstance(message.get('text'), str) or not message['text'].strip():
            raise ValueError('Every thread message requires a nonempty text')
        if 'at' in message and not isinstance(message['at'], str):
            raise ValueError('Thread at must be a string when present')
        if set(message) - {'role', 'text', 'at'}:
            raise ValueError('Thread messages hold only role, text, and at')
    return [dict(message) for message in thread]


def agent_messages(thread):
    return sum(m.get('role') == 'agent' for m in thread or [])


def build_session(data, previous=None):
    """Validate an inventory and return a new session; carry decisions from previous by item id."""
    for field in ('title', 'scope', 'default_action'):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f'Inventory requires a nonempty {field}')
    if not isinstance(data.get('items'), list) or not data['items']:
        raise ValueError('Inventory requires a nonempty items array')
    actions = data.get('actions')
    if actions is not None and (not isinstance(actions, list) or not actions
                                or not all(isinstance(a, str) and a.strip() for a in actions)):
        raise ValueError('Inventory actions must be a nonempty list of nonempty strings')
    if 'origin' in data and not isinstance(data['origin'], dict):
        raise ValueError('Inventory origin must be an object')
    if 'ask' in data and not isinstance(data['ask'], bool):
        raise ValueError('Inventory ask must be true or false')
    groups = data.get('groups')
    if groups is not None and (not isinstance(groups, list)
                               or not all(isinstance(g, str) and g.strip() for g in groups)):
        raise ValueError('Inventory groups must be a list of nonempty strings')
    carried = {}
    for old in (previous or {}).get('items', []):
        if old.get('id'):
            carried[old['id']] = old
    items, seen = [], set()
    for item in data['items']:
        for field in ITEM_FIELDS:
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f'Every item requires a nonempty {field}')
        for field in OPTIONAL_ITEM_FIELDS:
            if field in item and not (isinstance(item[field], str) and item[field].strip()):
                raise ValueError(f'Item {field} must be a nonempty string when present')
        if item.get('id'):
            if item['id'] in seen:
                raise ValueError('Duplicate item id: ' + item['id'])
            seen.add(item['id'])
        entry = {key: item[key] for key in ITEM_FIELDS + OPTIONAL_ITEM_FIELDS if key in item}
        if entry.get('recommendation') and not entry.get('recommended_action'):
            entry['recommended_action'] = data['default_action']
        if 'thread' in item:
            entry['thread'] = check_thread(item['thread'])
        entry.update(action='', note='', status='pending')
        old = carried.get(entry.get('id'))
        if old:
            # A thread missing from the new inventory (e.g. a rescan) keeps the old one.
            if 'thread' not in entry and old.get('thread'):
                entry['thread'] = old['thread']
            replied = agent_messages(entry.get('thread')) > agent_messages(old.get('thread'))
            if old.get('status') != 'done' and (old.get('action') or old.get('note')):
                entry.update(action=old.get('action', ''), note=old.get('note', ''))
                if replied and asking(previous, old):
                    # The question was answered: clear the ask, and the note once the thread records it.
                    entry['action'] = ''
                    asked = {m['text'].strip() for m in entry['thread'] if m['role'] == 'owner'}
                    if entry['note'].strip() in asked:
                        entry['note'] = ''
                if (old.get('details'), old.get('recommendation')) != (entry['details'], entry.get('recommendation')):
                    entry['context_changed'] = True
            if replied:
                entry.update(context_changed=True, new_reply=True)
        items.append(entry)
    session = {key: data[key] for key in ('title', 'scope', 'default_action')}
    session.update({key: data[key] for key in OPTIONAL_FIELDS if key in data})
    session.update(version=1, items=items, created_at=now(), updated_at=now())
    return session


def accepted(item):
    """True when the decision just takes the item's recommendation, with nothing to read."""
    return bool(item.get('recommended_action')) and item['action'] == item['recommended_action'] \
        and not item['note'].strip() and not item.get('context_changed')


def to_inventory(data):
    """An inventory holding a session's items as they stand, ready for init --carry."""
    inventory = {key: data[key] for key in ('title', 'scope', 'default_action')}
    inventory.update({key: data[key] for key in OPTIONAL_FIELDS if key in data})
    inventory['items'] = [{key: item[key] for key in ITEM_FIELDS + OPTIONAL_ITEM_FIELDS + ('thread',) if key in item}
                          for item in data['items']]
    return inventory


def find_item(data, ref):
    """An item by its id or its 1-based number."""
    for item in data['items']:
        if item.get('id') == ref:
            return item
    if ref.isdigit():
        return item_at(data, int(ref))
    raise ValueError('No item with id or number ' + ref)


def next_session_dir(path):
    """Sibling directory for the next round: name -> name-r2 -> name-r3."""
    head, sep, tail = path.parent.name.rpartition('-r')
    name = f'{head}-r{int(tail) + 1}' if sep and tail.isdigit() else path.parent.name + '-r2'
    return path.parent.with_name(name)


def reply(path, data, ref, text, recommendation=None, recommended_action=None, question=None, out=None):
    """Append the owner's question and the agent's answer to an item's thread in the next inventory.

    The next inventory starts as a copy of the session and accumulates replies, so several
    questions are answered into one file before a single init --carry."""
    if not text.strip():
        raise ValueError('A nonempty --text answer is required')
    for name, value in (('--recommendation', recommendation), ('--recommended-action', recommended_action)):
        if value is not None and not value.strip():
            raise ValueError(name + ' must be nonempty when given')
    item = find_item(data, ref)
    if not item.get('id'):
        raise ValueError('Replies carry by id; this item has none. Give the inventory stable item ids.')
    folder = (out or next_session_dir(path)).expanduser().resolve()
    target = folder / 'inventory.json'
    if folder == path.parent:
        raise ValueError('Write the next inventory outside the session folder being answered')
    if (folder / 'session.json').exists():
        raise ValueError(f'{folder} already holds a session; pass --out for a new folder')
    inventory = json.loads(target.read_text()) if target.exists() else dict(to_inventory(data), generated_at=now())
    entry = next((i for i in inventory['items'] if i.get('id') == item['id']), None)
    if entry is None:
        raise ValueError(f"{target} has no item {item['id']}")
    thread = entry.setdefault('thread', [])
    if question is None and asking(data, item):
        question = item['note']
    stamp = now()
    owner = [m['text'].strip() for m in thread if m['role'] == 'owner']
    if question and question.strip() and question.strip() not in owner:
        thread.append(dict(role='owner', text=question.strip(), at=stamp))
    thread.append(dict(role='agent', text=text.strip(), at=stamp))
    if recommendation is not None:
        entry['recommendation'] = recommendation.strip()
    if recommended_action is not None:
        entry['recommended_action'] = recommended_action.strip()
    build_session(inventory)  # validate before writing
    save(target, inventory)
    return target


def export(data, path):
    """One Markdown block with a fenced JSON payload, to paste back to an agent."""
    numbered = [dict(number=n, **i) for n, i in enumerate(data['items'], 1)]
    order = group_order(data)
    asked = [i for i in numbered if asking(data, i)]
    decided = [i for i in numbered if is_decided(data, i)]
    easy = [i for i in decided if accepted(i)]
    read = [i for i in decided if not accepted(i)]
    undecided = [dict(number=i['number'], id=i.get('id'), group=group_of(i), source=i['source'], note=i['note'],
                      new_reply=bool(i.get('new_reply')))
                 for i in numbered if not i['action']]
    origin = data.get('origin') or {}
    stamp = now()
    payload = dict(
        format='mgmt-export/1', session=str(path), title=data['title'], kind=data.get('kind', ''),
        generated_at=data.get('generated_at', data.get('created_at', '')), exported_at=stamp, origin=origin,
        counts=dict(items=len(data['items']), decided=len(decided), accepted=len(easy), asked=len(asked),
                    undecided=len(undecided)),
        groups=order,
        questions=[dict(number=i['number'], id=i.get('id'), group=group_of(i), source=i['source'], title=i['title'],
                        question=i['note'], thread=i.get('thread', [])) for i in asked],
        items=[dict(number=i['number'], id=i.get('id'), group=group_of(i), source=i['source'], title=i['title'],
                    action=i['action'],
                    recommended_action=i.get('recommended_action'), accepted_recommendation=accepted(i),
                    note=i['note'], status=i['status'], context_changed=bool(i.get('context_changed')),
                    new_reply=bool(i.get('new_reply')))
               for i in decided],
        undecided=undecided)

    def line(i):
        return f"- {i['number']}. `{i.get('id') or '-'}` {i['source']} — {i['title']}"

    def by_topic(rows, entry):
        """Lines for rows under a ### heading per topic, topics in display order."""
        lines = []
        for topic in order:
            members = [i for i in rows if group_of(i) == topic]
            if members:
                lines += ['', '### ' + topic]
                for i in members:
                    lines += entry(i)
        return lines

    def question(i):
        text = ' / '.join(i['note'].strip().splitlines()) or '(no question text; ask what they need)'
        lines = [line(i), '  - Question: ' + text]
        if i.get('thread'):
            lines.append(f"  - Earlier in this thread: {len(i['thread'])} messages (see the JSON)")
        return lines

    def reading(i):
        rec = f" (recommended: {i['recommended_action']})" if i.get('recommended_action') else ''
        lines = [line(i), f"  - Action: {i['action']}{rec}"
                 + (' — CONTEXT CHANGED since decided' if i.get('context_changed') else '')]
        if i['note'].strip():
            lines.append('  - Note: ' + ' / '.join(i['note'].strip().splitlines()))
        return lines
    out = ['# mgmt export: ' + data['title'], '',
           '- Session: ' + str(path),
           f"- Kind: {data.get('kind') or '-'} · generated {payload['generated_at']} · exported {stamp}"]
    if origin:
        out.append(f"- Source: {origin.get('repo', '-')} @ {origin.get('commit', '-')}"
                   + (' (uncommitted changes)' if origin.get('dirty') else ''))
    out.append(f"- Decided {len(decided)} of {len(data['items'])}: {len(easy)} just accept the recommendation, "
               f"{len(read)} need reading; {len(asked)} asked; {len(undecided)} undecided (left untouched)")
    if asked:
        out += ['', '## Questions for you',
                'Open, not decided: the owner asked before deciding. Answer each with `mgmt.py reply`, then `init --carry`.']
        out += by_topic(asked, question)
    if read:
        out += ['', '## Read these'] + by_topic(read, reading)
    if easy:
        out += ['', '## Accept the recommendation (skim)'] + by_topic(easy, lambda i: [line(i)])
    out += ['', '```json', json.dumps(payload, indent=2, ensure_ascii=False), '```', '']
    return '\n'.join(out)


def review(path, data):
    display(data)
    print('\nCommands: show N | check N | uncheck N | action N TEXT | note N TEXT')
    print('          list | done (finish review) | quit (resume later)')
    print('Changes save immediately. Checking uses the session default action.')
    while True:
        try:
            text = input('mgmt> ').strip()
        except EOFError:
            return
        try:
            parts = text.split(maxsplit=2)
            if not parts:
                continue
            cmd = parts[0]
            if cmd in ('quit', 'q'):
                return
            if cmd == 'done':
                data['reviewed_at'] = now()
                save(path, data)
                print('Review saved. Ask your assistant to apply this session: ' + str(path))
                return
            if cmd == 'list':
                display(data)
                continue
            if cmd not in ('show', 'check', 'uncheck', 'action', 'note'):
                raise ValueError('Unknown command')
            if len(parts) < 2:
                raise ValueError('Supply an item number')
            number = int(parts[1])
            if cmd == 'show':
                print(json.dumps(item_at(data, number), indent=2, ensure_ascii=False))
                continue
            if cmd in ('action', 'note') and len(parts) < 3:
                raise ValueError('Supply text (use note N - to clear a note)')
            if cmd == 'note':
                change(data, number, note='' if parts[2] == '-' else parts[2])
            else:
                action = data['default_action'] if cmd == 'check' else '' if cmd == 'uncheck' else parts[2]
                change(data, number, action=action)
            save(path, data)
            print('Saved.')
        except (ValueError, IndexError) as error:
            print('Error: ' + str(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='Create a session from an assistant-generated inventory JSON')
    init.add_argument('session', type=Path)
    init.add_argument('inventory', type=Path)
    init.add_argument('--carry', type=Path, metavar='OLD_SESSION',
                      help='Copy decisions from an earlier session for items with the same id')
    for name in ('review', 'status', 'apply', 'export'):
        command = sub.add_parser(name)
        command.add_argument('session', type=Path)
    answer = sub.add_parser('reply', help="Answer an item's question into the next inventory for init --carry")
    answer.add_argument('session', type=Path)
    answer.add_argument('item', help='Item id (or its number)')
    answer.add_argument('--text', required=True, help="The agent's answer")
    answer.add_argument('--recommendation', help='Replace the recommendation')
    answer.add_argument('--recommended-action', help='Replace the recommended action')
    answer.add_argument('--question', help="The owner's question (default: the note on an item marked ask)")
    answer.add_argument('--out', type=Path, metavar='DIR',
                        help='Folder of the next session (default: a sibling SESSION_DIR-r2, -r3, ...)')
    result = sub.add_parser('result', help='Record an executor result; never executes actions itself')
    result.add_argument('session', type=Path)
    result.add_argument('number', type=int)
    result.add_argument('outcome', choices=('done', 'failed'))
    result.add_argument('receipt', help='What changed and verification, or the failure/recovery details')
    web = sub.add_parser('serve', help='Open the browser review workspace (loopback only)')
    web.add_argument('path', nargs='?', type=Path, default=Path.home() / '.local/state/mgmt',
                     help='Session JSON or directory containing sessions')
    web.add_argument('--port', type=int, default=8765, help='Local port (0 chooses an available port)')
    web.add_argument('--no-open', action='store_true', help='Print the URL without opening a browser')
    args = parser.parse_args()
    if args.command == 'serve':
        from mgmt_web import serve
        if not 0 <= args.port <= 65535:
            raise ValueError('Port must be between 0 and 65535')
        serve(args.path, args.port, not args.no_open, sys.modules[__name__])
        return
    path = args.session.expanduser().resolve()
    with locked(path):
        if args.command == 'init':
            if path.exists():
                raise ValueError('Session already exists; refusing to overwrite choices')
            previous = load(args.carry.expanduser().resolve()) if args.carry else None
            data = build_session(json.loads(args.inventory.read_text()), previous)
            save(path, data)
            print('Created ' + str(path))
            if previous:
                kept = sum(bool(i['action'] or i['note']) for i in data['items'])
                changed = sum(bool(i.get('context_changed')) for i in data['items'])
                replies = sum(bool(i.get('new_reply')) for i in data['items'])
                print(f'Carried {kept} decisions by id; {changed} need a recheck (context changed)'
                      + (f'; {replies} with a new reply (answered asks are open again)' if replies else ''))
            print('Review: ' + shlex.join([sys.executable, str(Path(__file__).resolve()), 'serve', str(path)]))
            return
        data = load(path)
        if args.command == 'review':
            review(path, data)
        elif args.command == 'status':
            print(json.dumps(data, indent=2, ensure_ascii=False))
        elif args.command == 'export':
            print(export(data, path), end='')
        elif args.command == 'reply':
            target = reply(path, data, args.item, args.text, args.recommendation, args.recommended_action,
                           args.question, args.out)
            print('Replied in ' + str(target))
            print('When every question is answered: ' + shlex.join(
                [sys.executable, str(Path(__file__).resolve()), 'init', str(target.parent / 'session.json'),
                 str(target), '--carry', str(path)]))
        elif args.command == 'apply':
            if any(item['status'] == 'applying' for item in data['items']):
                raise ValueError('Unresolved applying items: inspect actual effects and record results before retrying')
            queue = []
            for number, item in enumerate(data['items'], 1):
                if is_decided(data, item) and item['status'] != 'done':
                    item['status'] = 'applying'
                    queue.append(dict(number=number, **item))
            data['updated_at'] = now()
            save(path, data)
            print(json.dumps({
                'mode': 'apply', 'session': str(path), 'scope': data['scope'],
                'executor': 'The assistant using the mgmt skill must execute these actions, verify them, and record each result. This command does not modify source material.',
                'items': queue,
            }, indent=2, ensure_ascii=False))
        else:
            item = item_at(data, args.number)
            if item['status'] != 'applying':
                raise ValueError('Only an applying item can receive a result')
            if not args.receipt.strip():
                raise ValueError('A nonempty result receipt is required')
            item.update(status=args.outcome, result=args.receipt, completed_at=now())
            data['updated_at'] = now()
            save(path, data)
            print(f'Item {args.number}: {args.outcome}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('Error: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nStopped. Previously saved choices are retained.', file=sys.stderr)
        sys.exit(130)
