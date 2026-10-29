"""Run with python3 -m unittest discover -s mgmt -p 'test_*.py'."""
import fcntl
import http.client
import json
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit


class BrowserReviewTest(unittest.TestCase):
    def test_decisions_persist_without_lost_updates_or_unauthorized_writes(self):
        tool = Path(__file__).with_name('mgmt.py')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'outline.md'
            source.write_text('Keep this source unchanged.\n')
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps(dict(title='Review', scope=str(source), default_action='remove', items=[
                dict(title='First', source=str(source), details='Original requirement'),
                dict(title='Second', source=str(source), details='Another requirement'),
            ])))
            session = root / 'session.json'
            subprocess.run([sys.executable, str(tool), 'init', str(session), str(inventory)], capture_output=True, timeout=10, check=True)
            process = subprocess.Popen([sys.executable, str(tool), 'serve', str(root), '--port', '0', '--no-open'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 10)[0], 'Server startup timed out')
                line = process.stdout.readline().decode()
                address = urlsplit(line.removeprefix('Review workspace: ').strip())
                self.assertEqual(address.hostname, '127.0.0.1')

                def request(method, path, body=None, headers=None):
                    connection = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
                    try:
                        connection.request(method, path, json.dumps(body) if body is not None else None, headers or {})
                        response = connection.getresponse()
                        return response.status, response.read().decode()
                    finally:
                        connection.close()

                status, html = request('GET', '/')
                self.assertEqual(status, 200)
                token = re.search(r'name="mgmt-token" content="([^"]+)"', html).group(1)
                auth = {'X-Mgmt-Token': token, 'Content-Type': 'application/json'}
                self.assertEqual(request('GET', '/api/sessions')[0], 403)
                self.assertEqual(request('GET', '/', headers={'Host': 'attacker.example'})[0], 403)
                status, listing = request('GET', '/api/sessions', headers=auth)
                self.assertEqual(status, 200)
                identity = json.loads(listing)['sessions'][0]['id']
                _, text = request('GET', '/api/session?id=' + identity, headers=auth)
                original = json.loads(text)
                change = dict(id=identity, revision=original['revision'], number=1, action='remove', note='Preserve the example.')
                self.assertEqual(request('POST', '/api/session', change, {**auth, 'Origin': 'https://attacker.example'})[0], 403)
                self.assertEqual(request('POST', '/api/session', {**change, 'number': True}, auth)[0], 400)
                status, text = request('POST', '/api/session', change, auth)
                self.assertEqual(status, 200)
                saved = json.loads(text)
                self.assertEqual((saved['data']['items'][0]['action'], saved['data']['items'][0]['note']), ('remove', 'Preserve the example.'))
                self.assertEqual(request('POST', '/api/session', {**change, 'note': 'Stale overwrite'}, auth)[0], 409)
                self.assertEqual(json.loads(session.read_text())['items'][0]['note'], 'Preserve the example.')
                with open(str(session) + '.lock', 'a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.assertNotEqual(request('POST', '/api/session', {**change, 'revision': saved['revision']}, auth)[0], 200)
                note_only = {**change, 'revision': saved['revision'], 'number': 2, 'action': '', 'note': 'Personal reminder'}
                status, _ = request('POST', '/api/session', note_only, auth)
                self.assertEqual(status, 200)
                queue = subprocess.run([sys.executable, str(tool), 'apply', str(session)], capture_output=True, text=True, timeout=10, check=True)
                self.assertEqual([(i['number'], i['action'], i['note']) for i in json.loads(queue.stdout)['items']], [(1, 'remove', 'Preserve the example.')])
                _, text = request('GET', '/api/session?id=' + identity, headers=auth)
                active = json.loads(text)
                self.assertEqual(request('POST', '/api/session', {**change, 'revision': active['revision']}, auth)[0], 409)
                self.assertEqual(source.read_text(), 'Keep this source unchanged.\n')
                self.assertEqual(session.stat().st_mode & 0o777, 0o600)
            finally:
                process.terminate()
                process.communicate(timeout=10)


class RecommendationExportTest(unittest.TestCase):
    tool = Path(__file__).with_name('mgmt.py')

    def run_tool(self, *args, check=True):
        return subprocess.run([sys.executable, str(self.tool), *map(str, args)], capture_output=True, text=True, timeout=10, check=check)

    def test_ids_actions_recommendations_carry_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / 'inventory.json'
            base = dict(title='Questions', scope='fixture', default_action='yes', actions=['yes', 'no', 'later'],
                        kind='owner-questions', origin=dict(repo='/repo', commit='abc123', dirty=False))
            items = [
                dict(id='q1', title='Tabs first?', source='/plan.md:3', details='1. Tabs first?', recommendation='Yes, app first.'),
                dict(id='q2', title='Rename it?', source='/plan.md:4', details='2. Rename it?', recommendation='No.', recommended_action='no'),
                dict(id='q3', title='Open one', source='/plan.md:5', details='3. Open one'),
            ]
            inventory.write_text(json.dumps(dict(base, items=items)))
            first = root / 'one' / 'session.json'
            self.run_tool('init', first, inventory)
            data = json.loads(first.read_text())
            self.assertEqual(data['actions'], ['yes', 'no', 'later'])
            self.assertEqual([i.get('recommended_action') for i in data['items']], ['yes', 'no', None])
            self.assertEqual(data['origin']['commit'], 'abc123')

            process = subprocess.Popen([sys.executable, str(self.tool), 'serve', str(first), '--port', '0', '--no-open'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 10)[0], 'Server startup timed out')
                address = urlsplit(process.stdout.readline().decode().removeprefix('Review workspace: ').strip())

                def request(method, path, body=None, headers=None):
                    connection = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
                    try:
                        connection.request(method, path, json.dumps(body) if body is not None else None, headers or {})
                        response = connection.getresponse()
                        return response.status, response.read().decode()
                    finally:
                        connection.close()

                _, html = request('GET', '/')
                self.assertIn('id="recommendation"', html)
                token = re.search(r'name="mgmt-token" content="([^"]+)"', html).group(1)
                auth = {'X-Mgmt-Token': token, 'Content-Type': 'application/json'}
                identity = json.loads(request('GET', '/api/sessions', headers=auth)[1])['sessions'][0]['id']
                self.assertEqual(request('GET', '/api/export?id=' + identity)[0], 403)
                revision = json.loads(request('GET', '/api/session?id=' + identity, headers=auth)[1])['revision']
                for number, action, note in ((1, 'yes', ''), (2, 'yes', 'Rename it to tabs.')):
                    status, text = request('POST', '/api/session', dict(id=identity, revision=revision, number=number, action=action, note=note), auth)
                    self.assertEqual(status, 200)
                    revision = json.loads(text)['revision']
                status, text = request('GET', '/api/export?id=' + identity, headers=auth)
                self.assertEqual(status, 200)
                exported = json.loads(text)['text']
            finally:
                process.terminate()
                process.communicate(timeout=10)
            payload = json.loads(re.search(r'```json\n(.*)\n```', exported, re.S).group(1))
            self.assertEqual(payload['format'], 'mgmt-export/1')
            self.assertEqual(payload['origin']['commit'], 'abc123')
            self.assertEqual(payload['counts'], dict(items=3, decided=2, accepted=1, undecided=1))
            self.assertEqual([(i['id'], i['accepted_recommendation']) for i in payload['items']], [('q1', True), ('q2', False)])
            self.assertEqual([u['id'] for u in payload['undecided']], ['q3'])
            self.assertIn('## Read these', exported)
            self.assertIn('## Accept the recommendation', exported)
            self.assertEqual(self.run_tool('export', first).stdout.split('```json')[0].count('`q1`'), 1)

            items[0]['details'] = '1. Tabs first, always?'
            items.reverse()
            inventory.write_text(json.dumps(dict(base, items=items)))
            second = root / 'two' / 'session.json'
            out = self.run_tool('init', second, inventory, '--carry', first).stdout
            self.assertIn('Carried 2 decisions', out)
            carried = {i['id']: i for i in json.loads(second.read_text())['items']}
            self.assertEqual((carried['q1']['action'], carried['q1'].get('context_changed')), ('yes', True))
            self.assertEqual((carried['q2']['note'], carried['q2'].get('context_changed')), ('Rename it to tabs.', None))
            self.assertEqual(carried['q3']['action'], '')
            self.assertFalse(json.loads(self.run_tool('export', second).stdout.split('```json')[1].split('```')[0])['items'][0]['accepted_recommendation'])

            for bad in (dict(base, items=[items[0], items[0]]), dict(base, actions=[], items=items),
                        dict(base, items=[dict(items[0], recommendation='')])):
                inventory.write_text(json.dumps(bad))
                result = self.run_tool('init', root / 'bad' / 'session.json', inventory, check=False)
                self.assertNotEqual(result.returncode, 0, bad)

    def test_owner_questions_inventory(self):
        script = Path(__file__).with_name('inventories') / 'owner_questions.py'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'plans').mkdir()
            (root / 'plans' / 'open.md').write_text(
                '# Open plan\n\n## Owner questions (recommended answers)\n\n'
                '1. **Tab order.** Which first? Recommended: the app first.\n'
                '2. **Title?** *Recommend: `ochazuke`.* It matches\n   the palette.\n\n## Lanes\n\n1. Not a question\n')
            (root / 'plans' / 'done.md').write_text(
                '# Done plan\n\n## Owner decisions (2026-10-29)\n\n1. Session.\n\n'
                '## Owner questions\n\n1. Session or file? Recommended: session.\n2. Still open?\n')
            out = root / 'out'
            subprocess.run([sys.executable, '-I', str(script), 'scan', '--root', str(root), '--out', str(out)], capture_output=True, text=True, timeout=10, check=True)
            data = json.loads((out / 'inventory.json').read_text())
            self.assertEqual(data['actions'], ['yes', 'no', 'later', 'moot'])
            got = [(i['title'], i.get('recommendation')) for i in data['items']]
            self.assertEqual(got, [('done.md #2: Still open?', None),
                                   ('open.md #1: Tab order.', 'the app first.'),
                                   ('open.md #2: Title?', '`ochazuke`. It matches the palette.')])
            self.assertEqual(len({i['id'] for i in data['items']}), 3)
            session = root / 'session' / 'session.json'
            self.run_tool('init', session, out / 'inventory.json')
            saved = json.loads(session.read_text())
            saved['items'][1]['action'] = 'yes'
            session.write_text(json.dumps(saved))
            sections = subprocess.run([sys.executable, '-I', str(script), 'decisions', str(session), '--root', str(root), '--date', '2026-10-30'], capture_output=True, text=True, timeout=10, check=True).stdout
            self.assertIn('## Owner decisions (2026-10-30)', sections)
            self.assertIn('1. **Tab order.** The app first.', sections)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_web_js_parses(self):
        subprocess.run(['node', '--check', str(Path(__file__).with_name('web.js'))], check=True, timeout=20)


if __name__ == '__main__':
    unittest.main()
