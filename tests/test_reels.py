import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_prompt
import reels
from quality import InputError


class ReelsTests(unittest.TestCase):
    def setUp(self):
        self.script = json.loads((ROOT / 'examples/reels.json').read_text())

    def test_sample_and_read_only_cli(self):
        original = copy.deepcopy(self.script)
        result = reels.check(self.script)
        self.assertTrue(result['ok'])
        self.assertLessEqual(result['words'], self.script['max_words'])
        self.assertEqual(original, self.script)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reels.json'
            path.write_text(json.dumps(self.script))
            before = path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = reels.main(['check', str(path)])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(out.getvalue())['ok'])
            self.assertEqual(path.read_bytes(), before)

    def test_mismatch_in_recording_and_chosen_hook_is_rejected(self):
        for mutate in [lambda s: s.update(recording_text=s['recording_text'] + ' Подпишитесь.'),
                       lambda s: s['hooks'].__setitem__(0, 'Другая первая фраза.')]:
            script = copy.deepcopy(self.script)
            mutate(script)
            self.assertFalse(reels.check(script)['ok'])

    def test_identical_versions_can_still_exceed_word_limit(self):
        self.script['max_words'] = 1
        result = reels.check(self.script)
        self.assertFalse(result['ok'])
        self.assertGreater(result['words'], result['max_words'])

    def test_whitespace_is_ignored_but_word_changes_are_not(self):
        self.script['recording_text'] = self.script['recording_text'].replace(' ', '\n  ')
        self.assertTrue(reels.check(self.script)['ok'])
        self.script['blocks'][1]['speech'] = self.script['blocks'][1]['speech'].replace('пятницу', 'субботу')
        self.assertFalse(reels.check(self.script)['ok'])

    def test_hook_cannot_be_matched_inside_another_word(self):
        self.script['hooks'][0] = 'Хот'
        self.assertFalse(reels.check(self.script)['ok'])

    def test_planned_intervals_must_cover_duration_without_gaps(self):
        for mutate in [lambda s: s['blocks'][0].pop('start'),
                       lambda s: s['blocks'][1].update(start=6),
                       lambda s: s['blocks'][-1].update(end=24),
                       lambda s: s['blocks'][1].update(start=4)]:
            script = copy.deepcopy(self.script)
            mutate(script)
            try:
                self.assertFalse(reels.check(script)['ok'])
            except InputError:
                pass

    def test_incomplete_hooks_invalid_limits_and_unspoken_tokens(self):
        for mutate in [lambda s: s.update(max_words=True),
                       lambda s: s.update(max_words=0),
                       lambda s: s.update(recording_text=''),
                       lambda s: s.update(hooks=['Раз', 'Два']),
                       lambda s: s['hooks'].__setitem__(1, s['hooks'][0]),
                       lambda s: s['hooks'].__setitem__(1, '{name}'),
                       lambda s: s.update(recording_text='<b>Текст</b>'),
                       lambda s: s['blocks'][0].update(speech='Имя: %s')]:
            script = copy.deepcopy(self.script)
            mutate(script)
            with self.assertRaises(InputError):
                reels.check(script)

    def test_exit_codes_distinguish_mismatch_from_invalid_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reels.json'
            self.script['recording_text'] += ' Ещё слово.'
            path.write_text(json.dumps(self.script))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(reels.main(['check', str(path)]), 2)
            path.write_text('{"max_words": 10, "max_words": 20}')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(reels.main(['check', str(path)]), 1)

    def test_export_includes_russian_core_and_only_requested_guides(self):
        _, base = build_prompt.compile_prompt('reels', 'create')
        self.assertIn('SKILL.md', base)
        self.assertIn('references/spoken-russian.md', base)
        self.assertIn('references/translationese.md', base)
        for name in build_prompt.REELS_FOCUS.values():
            self.assertNotIn(name, base)
        prompt, selected = build_prompt.compile_prompt(
            'reels', 'create', book_informed=True, reels_focus=['hooks', 'filming', 'hooks'])
        self.assertEqual(selected.count('references/reels/hooks.md'), 1)
        self.assertIn('references/reels/filming.md', selected)
        self.assertNotIn('references/reels/series.md', selected)
        self.assertIn('references/book-informed-writing.md', selected)
        self.assertNotIn('references/', prompt)
        self.assertNotIn('## Выбор профиля', prompt)

    def test_focus_is_not_accepted_for_other_profiles_or_paths(self):
        for profile, focus in [('web-ui', ['hooks']), ('reels', ['../secrets']),
                               ('reels', 'hooks'), ('reels', [None])]:
            with self.assertRaises(ValueError):
                build_prompt.compile_prompt(profile, reels_focus=focus)

    def test_cli_exports_selected_sections_and_rejects_wrong_profile(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = build_prompt.main(['--profile', 'reels', '--operation', 'create',
                                      '--reels-focus', 'structure', '--reels-focus', 'filming', '--stats'])
        self.assertEqual(code, 0)
        documents = json.loads(output.getvalue())['documents']
        self.assertIn('references/reels/structure.md', documents)
        self.assertIn('references/reels/filming.md', documents)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build_prompt.main(['--profile', 'web-ui', '--reels-focus', 'hooks']), 1)


if __name__ == '__main__':
    unittest.main()
