"""Run with python3 -m unittest discover -s mgmt/inventories -p 'test_*.py'. No real binaries."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rights_audit as ra


def verb(name, agent=None, destructive=False, confirm=None, history='change', description=''):
    v = dict(name=name, history=history, description=description, destructive=destructive)
    if agent:
        v['agent'] = agent
    if confirm:
        v['confirm'] = confirm
    return v


MTM = dict(nouns=[
    dict(name='task', verbs=[verb('delete', 'never', True, 'Delete?'), verb('archive', 'allow'), verb('get', 'allow', history='fetch')]),
    dict(name='pane', verbs=[verb('kill', 'confirm', False, 'Kill?'), verb('rename', 'allow', description='Rename it')]),
    dict(name='ochazuke.list', verbs=[verb('sort-clear', 'allow')]),
])
RIGHTS = [dict(verb='task.delete', right='never', rule='destructive verb'),
          dict(verb='task.archive', right='allow', rule='derived default'),
          dict(verb='task.get', right='allow', rule=''),
          dict(verb='pane.kill', right='confirm', rule=''),
          dict(verb='pane.rename', right='allow', rule=''),
          dict(verb='ochazuke.list.sort-clear', right='allow', rule='')]
TOOL = dict(name='o-md', nouns=[
    dict(name='doc', verbs=[verb('delete', 'confirm', False, 'Delete the file?'), verb('wipe-cache'), verb('show', 'allow', history='fetch')]),
    dict(name='ochazuke.settings', verbs=[verb('reset-all', 'never')]),
])


def fake_runner(tools):
    calls = []

    def runner(argv, env, cwd):
        calls.append((argv, env))
        if argv[-1] == 'catalog' and argv[0] == 'mtm':
            return MTM, ''
        if argv[-3:] == ['ochazuke', 'agent', 'rights']:
            return RIGHTS, ''
        if argv[-1] == 'catalog' and argv[0] in tools:
            cat = tools[argv[0]]
            return (cat, '') if cat is not None else (None, 'exit 1: boom')
        return None, 'unexpected ' + ' '.join(argv)
    runner.calls = calls
    return runner


class JoinAndAuditTest(unittest.TestCase):
    def rows(self):
        return ra.join(MTM, RIGHTS, dict(md=TOOL))

    def test_join_keys_and_framework_nouns(self):
        keys = {r['verb'] for r in self.rows()}
        self.assertIn('task.delete', keys)
        self.assertIn('ochazuke.list.sort-clear', keys)
        self.assertIn('md.doc.delete', keys)
        self.assertNotIn('md.ochazuke.settings.reset-all', keys)

    def test_rights_win_and_mismatch_is_noted(self):
        rights = [dict(r, right='confirm') if r['verb'] == 'task.delete' else r for r in RIGHTS]
        row = {r['verb']: r for r in ra.join(MTM, rights, {})}['task.delete']
        self.assertEqual(row['right'], 'confirm')
        self.assertIn('never', row['mismatch'])

    def test_hit_reasons(self):
        by = {r['verb']: r for r in self.rows()}
        self.assertEqual(ra.hit_reasons(by['task.delete']), ['name', 'destructive flag', 'prompt'])
        self.assertEqual(ra.hit_reasons(by['pane.kill']), ['name', 'prompt', 'right confirm'])
        self.assertEqual(ra.hit_reasons(by['md.doc.wipe-cache']), ['name'])
        self.assertEqual(ra.hit_reasons(by['task.archive']), [])
        self.assertEqual(ra.hit_reasons(by['task.get']), [])

    def test_description_hit_skips_fetch(self):
        quiet = ra.make_row('t', 't.n.show', verb('show', history='fetch', description='removes nothing'))
        loud = ra.make_row('t', 't.n.edit', verb('edit', description='removes the old text'))
        self.assertEqual(ra.hit_reasons(quiet), [])
        self.assertEqual(ra.hit_reasons(loud), ['description'])

    def test_unjudged_differs_stale_and_totals(self):
        judged = {'task.delete': dict(right='never', reason='x'),
                  'pane.kill': dict(right='confirm', reason='x'),
                  'md.doc.delete': dict(right='never', reason='x'),
                  'ochazuke.list.sort-clear': dict(right='allow', reason='x'),
                  'gone.verb': dict(right='allow', reason='x')}
        result = ra.audit(self.rows(), judged)
        self.assertEqual([r['verb'] for r in result['unjudged']], ['md.doc.wipe-cache'])
        self.assertEqual([(r['verb'], r['right'], r['judged']) for r in result['differs']], [('md.doc.delete', 'confirm', 'never')])
        self.assertEqual(result['stale'], ['gone.verb'])
        md = result['totals']['md']
        self.assertEqual((md['verbs'], md['allow'], md['confirm'], md['never'], md['undeclared']), (3, 2, 1, 0, 1))
        self.assertEqual(result['totals']['mtm']['never'], 1)

    def test_undeclared_counts_as_allow_and_matches_a_judged_allow(self):
        result = ra.audit(self.rows(), {'md.doc.wipe-cache': dict(right='allow', reason='cache only')})
        self.assertEqual(result['differs'], [])
        self.assertNotIn('md.doc.wipe-cache', [r['verb'] for r in result['unjudged']])


class LoadWorldTest(unittest.TestCase):
    def test_runs_in_temp_dirs_with_a_scrubbed_environment(self):
        runner = fake_runner(dict(a=TOOL))
        old = {k: os.environ.get(k) for k in ('TUIOS_PANE_ID', 'OCHAZUKE_ACTOR')}
        os.environ.update(TUIOS_PANE_ID='pane-1', OCHAZUKE_ACTOR='agent')
        try:
            with tempfile.TemporaryDirectory() as d:
                tool = Path(d, 'o-a')
                tool.write_text('')
                ra.load_world('mtm', {'o-a': 'a'}, runner)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        home = os.environ.get('HOME')
        for argv, env in runner.calls:
            self.assertNotIn('TUIOS_PANE_ID', env)
            self.assertNotIn('OCHAZUKE_ACTOR', env)
            self.assertIn('rights-audit-', env['HOME'])
            self.assertNotEqual(env['HOME'], home)
            for k in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME', 'TMPDIR'):
                self.assertIn('rights-audit-', env[k])
        mtm_calls = [a for a, _ in runner.calls if a[0] == 'mtm']
        self.assertTrue(all(a[1] == '-data' and 'rights-audit-' in a[2] and a[3] == '-config' for a in mtm_calls))

    def test_exclusions_aliases_duplicates_and_failures(self):
        with tempfile.TemporaryDirectory() as d:
            real = Path(d, 'o-md')
            real.write_text('')
            link = Path(d, 'o-md2')
            link.symlink_to(real)
            tools = {'o-md': str(real), 'o-md2': str(link), 'o-copy': 'copy', 'o-json-pre': 'pre',
                     'mtm-help-prototype': 'hp', 'o-bad': 'bad'}
            runner = fake_runner({str(real): TOOL, 'copy': TOOL, 'bad': None, 'pre': TOOL, 'hp': TOOL})
            _, _, cats, notes = ra.load_world('mtm', tools, runner)
        self.assertEqual(len(cats), 1)
        text = '\n'.join(notes)
        self.assertIn('o-json-pre: excluded', text)
        self.assertIn('mtm-help-prototype: excluded', text)
        self.assertIn('o-md2: same file as o-md', text)
        self.assertIn('same catalog as', text)
        self.assertIn('o-bad: catalog failed', text)

    def test_find_tools_takes_o_star_and_nabe_only(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('o-git', 'nabe', 'mtm', 'other', 'o-notexec'):
                p = Path(d, name)
                p.write_text('')
                if name != 'o-notexec':
                    p.chmod(0o755)
            found = ra.find_tools([d, '/nonexistent-dir'])
        self.assertEqual(sorted(found), ['nabe', 'o-git'])


class ScanTest(unittest.TestCase):
    def run_scan(self, judged):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tool = root / 'o-md'
            tool.write_text('')
            tool.chmod(0o755)
            jf = root / 'judged.json'
            jf.write_text(json.dumps(dict(rows=judged)))
            args = argparse.Namespace(out=root / 'out', mtm_bin='mtm', tool=[], path=str(root), judged=jf)
            code = ra.scan(args, fake_runner({str(tool): TOOL}))
            files = {p.name: p.read_text() for p in (root / 'out').iterdir()}
        return code, files

    ALL = {'task.delete': dict(right='never', reason='r'), 'pane.kill': dict(right='confirm', reason='r'),
           'md.doc.delete': dict(right='confirm', reason='r'), 'md.doc.wipe-cache': dict(right='allow', reason='r'),
           'ochazuke.list.sort-clear': dict(right='allow', reason='r')}

    def test_clean_run_exits_zero_and_writes_three_files(self):
        code, files = self.run_scan(self.ALL)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(files), ['inventory.json', 'report.md', 'result.json'])
        self.assertIn('## Totals per source', files['report.md'])
        self.assertEqual(json.loads(files['inventory.json'])['items'], [])

    def test_unjudged_hit_exits_one_and_becomes_an_inventory_item(self):
        code, files = self.run_scan({k: v for k, v in self.ALL.items() if k != 'md.doc.wipe-cache'})
        self.assertEqual(code, 1)
        inv = json.loads(files['inventory.json'])
        self.assertEqual([i['title'] for i in inv['items']], ['Judge md.doc.wipe-cache (now allow, undeclared)'])
        self.assertEqual(inv['kind'], 'rights-audit')
        self.assertIn('md.doc.wipe-cache', files['report.md'])

    def test_differing_row_exits_one(self):
        code, files = self.run_scan(dict(self.ALL, **{'md.doc.delete': dict(right='never', reason='r')}))
        self.assertEqual(code, 1)
        self.assertIn('| md.doc.delete | confirm | never | r |', files['report.md'])

    def test_judged_file_needs_a_reason(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, 'j.json')
            p.write_text(json.dumps(dict(rows={'x.y': dict(right='allow', reason=' ')})))
            with self.assertRaises(SystemExit):
                ra.load_judged(p)
            p.write_text(json.dumps(dict(rows={'x.y': dict(right='maybe', reason='r')})))
            with self.assertRaises(SystemExit):
                ra.load_judged(p)

    def test_shipped_judged_file_is_valid(self):
        rows = ra.load_judged(Path(ra.__file__).with_name('rights_audit_judged.json'))
        self.assertTrue(rows)


if __name__ == '__main__':
    unittest.main()
