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
import video
from quality import InputError

class ProfileAndVideoTests(unittest.TestCase):
    def setUp(self):
        self.before = json.loads((ROOT / 'examples/video.before.json').read_text())
        self.after = json.loads((ROOT / 'examples/video.after.json').read_text())

    def test_demo_is_valid_and_compare_is_read_only(self):
        original = copy.deepcopy(self.before)
        self.assertEqual(video.compare(self.before, self.after), [])
        self.assertEqual(original, self.before)

    def test_changed_timing_role_order_and_metadata(self):
        for mutate in [lambda x: x.update(duration_seconds=36),
                       lambda x: x['blocks'].reverse(),
                       lambda x: x['blocks'][0].update(role='cta'),
                       lambda x: x['blocks'][1].update(visual='Новая съёмка'),
                       lambda x: x.update(cta='купить')]:
            new = copy.deepcopy(self.after)
            mutate(new)
            try:
                self.assertTrue(video.compare(self.before, new))
            except InputError:
                pass

    def test_lost_repeated_placeholder(self):
        self.before['blocks'][2]['speech'] = '{x} и {x}'
        self.after['blocks'][2]['speech'] = '{x}'
        self.assertTrue(video.compare(self.before, self.after))

    def test_timing_types_and_bounds(self):
        for value in [True, 0, -1, float('inf'), float('nan')]:
            s = copy.deepcopy(self.before)
            s['duration_seconds'] = value
            with self.assertRaises(InputError): video.validate(s)
        for start, end in [(9,8),(-1,8),(0,100),(True,8)]:
            s = copy.deepcopy(self.before)
            s['blocks'][0].update(start=start,end=end)
            with self.assertRaises(InputError): video.validate(s)

    def test_duplicate_ids_and_unsupported_syntax(self):
        s = copy.deepcopy(self.before)
        s['blocks'][1]['id'] = s['blocks'][0]['id']
        with self.assertRaises(InputError): video.validate(s)
        s = copy.deepcopy(self.before)
        s['blocks'][0]['speech'] = '{n, plural, one{раз} other{раза}}'
        with self.assertRaises(InputError): video.validate(s)

    def test_estimate_with_explicit_rate_and_pauses(self):
        d = video.estimate('Раз, два, три.',60,120,2)
        self.assertEqual((d['words'],d['min_seconds'],d['max_seconds']),(3,3.5,5))
        for bounds in [(0,120),(150,120),(True,120),(float('nan'),120)]:
            with self.assertRaises(InputError): video.estimate('текст',*bounds)
        self.assertEqual(video.word_count('Кто-то сказал: «северо-запад». Всего 3 пункта.'),6)

    def test_unresolved_speech_cannot_have_a_time_estimate(self):
        for text in ['Здравствуйте, {name}', 'Привет, %s', '<b>Текст</b>']:
            with self.assertRaises(InputError): video.estimate(text,120,150)

    def test_cli_certain_overflow_and_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'input.json'
            p.write_text(json.dumps({'duration_seconds':1,'blocks':[{'id':'x','role':'hook','speech':'Один два три четыре пять'}]}))
            original = p.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = video.main(['estimate',str(p),'--script','--min-wpm','60','--max-wpm','120'])
            self.assertEqual(code,2)
            self.assertTrue(json.loads(output.getvalue())['over_budget_certain'])
            self.assertEqual(original,p.read_bytes())

    def test_selected_prompt_does_not_load_other_profiles(self):
        text, sources = build_prompt.compile_prompt('short-video-script')
        self.assertEqual(sources,['SKILL.md','references/spoken-russian.md','references/short-video-script.md'])
        self.assertNotIn('# Художественная редактура',text)
        self.assertNotIn('references/',text)
        self.assertNotIn('## Выбор профиля',text)
        with self.assertRaises(ValueError): build_prompt.compile_prompt('../../secret')

    def test_diagnosis_and_all_routes(self):
        text,_ = build_prompt.compile_prompt('editorial-review','diagnose')
        self.assertIn('не переписывай материал',text)
        for profile in build_prompt.profiles():
            prompt, sources = build_prompt.compile_prompt(profile)
            self.assertTrue(prompt)
            self.assertLessEqual(len(sources),3)
        with self.assertRaises(ValueError): build_prompt.compile_prompt('spoken-russian','delete')

    def test_voice_operation_loads_voice_card(self):
        text, sources = build_prompt.compile_prompt('spoken-russian','voice')
        self.assertIn('references/voice.md',sources)
        self.assertIn('Наблюдаемая карточка',text)

    def test_extended_guidance_is_opt_in_for_export(self):
        simple, simple_sources = build_prompt.compile_prompt('literary-prose')
        expanded, expanded_sources = build_prompt.compile_prompt('literary-prose', extended=True)
        self.assertNotIn('references/syntax-and-composition.md', simple_sources)
        self.assertIn('references/syntax-and-composition.md', expanded_sources)
        self.assertGreater(len(expanded), len(simple))

if __name__ == '__main__': unittest.main()
