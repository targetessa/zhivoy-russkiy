import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("quality", ROOT / "scripts/quality.py")
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.before = {"scene": "bridge", "lines": [
            {"id": "a", "speaker": "vera", "text": "{player}, ключ у {player}: {count}.",
             "next": "b", "max_chars": 100},
            {"id": "b", "text": "<b>Ждать</b> %s %d\nГотово.", "next": None}]}
        self.after = copy.deepcopy(self.before)

    def test_demo_pair(self):
        self.assertEqual(q.compare(q.read_json(ROOT / "examples/scene.before.json"),
                                   q.read_json(ROOT / "examples/scene.after.json")), [])

    def test_rewrite_and_reorder_named_tokens(self):
        self.after["lines"][0]["text"] = "{count} — {player}, для {player}."
        self.assertEqual(q.compare(self.before, self.after), [])

    def test_lost_repeated_placeholder(self):
        self.after["lines"][0]["text"] = "{player}: {count}."
        self.assertTrue(any("вставки" in x for x in q.compare(self.before, self.after)))

    def test_branch_speaker_id_and_added_metadata(self):
        for field, value in [("next", "wrong"), ("speaker", "lida"), ("id", "new"), ("new", True)]:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.before)
                changed["lines"][0][field] = value
                self.assertTrue(q.compare(self.before, changed))

    def test_type_change_not_hidden_by_python_equality(self):
        self.before["flag"] = 1
        self.after["flag"] = True
        self.assertTrue(q.compare(self.before, self.after))

    def test_line_deletion_and_reordering(self):
        self.after["lines"].pop()
        self.assertTrue(q.compare(self.before, self.after))
        self.after = copy.deepcopy(self.before)
        self.after["lines"].reverse()
        self.assertTrue(q.compare(self.before, self.after))

    def test_limits_and_changed_limit(self):
        self.after["lines"][0]["text"] += "я" * 100
        self.after["lines"][0]["max_chars"] = 1000
        errors = q.compare(self.before, self.after)
        self.assertTrue(any("длина" in x for x in errors))
        self.assertTrue(any("структура" in x for x in errors))

    def test_unicode_limit_and_zero_limit(self):
        before = {"lines": [{"id": "ru", "text": "Ёж", "max_chars": 2}]}
        self.assertEqual(q.compare(before, before), [])
        after = copy.deepcopy(before)
        after["lines"][0]["text"] = "Ещё"
        self.assertTrue(q.compare(before, after))
        before["lines"][0].update(text="", max_chars=0)
        self.assertEqual(q.compare(before, before), [])

    def test_printf_order_and_tag_nesting(self):
        for text in ["<b>Ждать</b> %d %s\nГотово.", "</b>Ждать<b> %s %d\nГотово.",
                     "<b>Ждать</b> %s %d Готово."]:
            with self.subTest(text=text):
                self.after["lines"][1]["text"] = text
                self.assertTrue(q.compare(self.before, self.after))

    def test_literal_escapes_and_braces(self):
        old = q.signature(r"{{пример}} {name!r} {count:03d} %(name)s %2$s %% \n")
        new = q.signature(r"{{другой}} {count:03d} {name!r} %(name)s %2$s %% \n")
        self.assertEqual(old, new)
        self.assertNotEqual(q.signature(r"{{x}} \n"), q.signature("x\n"))

    def test_unsupported_icu_and_broken_braces(self):
        for text in ["{n, plural, one{ключ} other{ключи}}", "{broken", "лишняя }", "\x00"]:
            with self.subTest(text=text), self.assertRaises(q.InputError):
                q.signature(text)

    def test_duplicate_ids_invalid_limits_and_missing_text(self):
        for scene in [{"lines": [{"id": "a", "text": ""}, {"id": "a", "text": ""}]},
                      {"lines": [{"id": "a"}]},
                      {"lines": [{"id": "a", "text": "", "max_chars": True}]}]:
            with self.subTest(scene=scene), self.assertRaises(q.InputError):
                q.validate_scene(scene)

    def test_json_duplicate_keys_and_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            for content in ['{"lines": [], "lines": []}', '{"lines": [], "x": NaN}']:
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(q.InputError):
                    q.read_json(path)

    def test_cli_codes_and_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / "before.json", Path(folder) / "after.json"
            before.write_text(json.dumps(self.before), encoding="utf-8")
            self.after["lines"][0]["next"] = "bad"
            after.write_text(json.dumps(self.after), encoding="utf-8")
            saved = before.read_bytes(), after.read_bytes()
            args = [sys.executable, str(ROOT / "scripts/quality.py"), "compare", str(before), str(after)]
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)
            after.write_bytes(b"\xff")
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 2)
            self.assertEqual(before.read_bytes(), saved[0])

    def test_lint_is_contextual_and_not_a_banned_word_list(self):
        self.assertEqual(q.lint_text("Я думаю, это имеет смысл. Ты в порядке?"), [])
        result = q.lint_text("В конце дня осуществляется осмотр.")
        self.assertTrue(any(x["rule"] == "end-of-day" for x in result))


if __name__ == "__main__":
    unittest.main()
