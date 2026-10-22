#!/usr/bin/env python3
"""Read-only checks for the documented dialogue JSON contract. Python 3.10+."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys


class InputError(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"Повторный ключ JSON: {key}")
        result[key] = value
    return result


def read_json(path):
    def invalid_constant(value):
        raise InputError(f"Недопустимая константа JSON: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      object_pairs_hook=unique_object, parse_constant=invalid_constant)


def validate_scene(scene):
    if not isinstance(scene, dict) or not isinstance(scene.get("lines"), list):
        raise InputError("Нужен объект с массивом lines")
    ids = set()
    for index, line in enumerate(scene["lines"]):
        if not isinstance(line, dict):
            raise InputError(f"lines[{index}]: нужен объект")
        ident = line.get("id")
        if not isinstance(ident, str) or not ident or ident in ids:
            raise InputError(f"lines[{index}]: отсутствующий или повторный id")
        ids.add(ident)
        if not isinstance(line.get("text"), str):
            raise InputError(f"{ident}: text должен быть строкой")
        limit = line.get("max_chars")
        if "max_chars" in line and (type(limit) is not int or limit < 0):
            raise InputError(f"{ident}: max_chars должен быть неотрицательным целым")


BRACE = re.compile(r"\{(?:[A-Za-z_][A-Za-z_0-9.]*|[0-9]+)(?:![rsa])?(?::[^{}\r\n]*)?\}")
PRINTF = re.compile(r"%%|%(?:[0-9]+\$|\([A-Za-z_][A-Za-z_0-9]*\))?[-+#0 ']*(?:[0-9]+|\*)?(?:\.(?:[0-9]+|\*))?[diuoxXfFeEgGcs]")
TAGS = re.compile(r"</?[A-Za-z][^<>\r\n]*>")


def signature(text):
    """Conservative token contract, deliberately not a game-language parser."""
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise InputError("Неподдержанный управляющий символ")
    tokens = []
    escaped = []
    index = 0
    while index < len(text):
        if text[index:index + 2] in ("{{", "}}"):
            escaped.append(text[index:index + 2])
            index += 2
        elif text[index] == "{":
            match = BRACE.match(text, index)
            if not match:
                raise InputError("Неподдержанная фигурная конструкция (возможно ICU)")
            tokens.append(match.group())
            index = match.end()
        elif text[index] == "}":
            raise InputError("Непарная фигурная скобка")
        else:
            index += 1
    return {
        "вставки": Counter(tokens),
        "литеральные скобки": Counter(escaped),
        "printf": PRINTF.findall(text),
        "теги": TAGS.findall(text),
        "переносы/табуляции": Counter(char for char in text if char in "\n\r\t"),
        "escape-последовательности": Counter(re.findall(r"\\[nrt]", text)),
    }


def compare(before, after):
    validate_scene(before)
    validate_scene(after)
    errors = []
    # JSON equality must distinguish booleans, integers and floats in metadata.
    # Key order is irrelevant; array order and JSON value types are not.
    def mask(scene):
        data = dict(scene)
        data["lines"] = [dict(line, text="") for line in scene["lines"]]
        return json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if mask(before) != mask(after):
        errors.append("Изменена структура или поля вне lines[i].text")
    if len(before["lines"]) != len(after["lines"]):
        return errors
    for old, new in zip(before["lines"], after["lines"]):
        ident = old["id"]
        try:
            left, right = signature(old["text"]), signature(new["text"])
        except InputError as exc:
            raise InputError(f"{ident}: {exc}") from exc
        for key in left:
            if left[key] != right[key]:
                errors.append(f"{ident}: изменены {key}")
        # Read the ORIGINAL constraint, so altering the limit cannot hide a failure.
        limit = old.get("max_chars")
        if limit is not None and len(new["text"]) > limit:
            errors.append(f"{ident}: длина {len(new['text'])} > {limit}")
    return errors


RULES = [
    ("office", r"\b(?:осуществ\w*|в целях|имеет место|надлежит)\b", "Проверьте: официальный регистр нужен голосу?"),
    ("nominal", r"\b(?:проведение|осуществление|произведение|наличие)\s+\w+", "Можно ли вернуть действие без потери смысла?"),
    ("end-of-day", r"\bв конце дня\b", "Буквальное время или переводная связка?"),
    ("day", r"\b(?:сделал|сделала|сделали) мой день\b", "Современный оборот уместен этому персонажу?"),
    ("option", r"\bне (?:опция|является опцией)\b", "Различите запрет и невозможность."),
    ("feel", r"\bделает меня чувствующ\w*", "Проверьте русское выражение чувства."),
    ("talk", r"\b(?:иметь|имели|имеем) разговор\b", "Речь о разговоре: нужна ли эта конструкция?"),
]


def lint_text(text):
    findings = []
    for ident, pattern, hint in RULES:
        for match in re.finditer(pattern, text, flags=re.I):
            findings.append({"rule": ident, "line": text.count("\n", 0, match.start()) + 1,
                             "match": match.group(), "hint": hint})
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("compare", help="Сравнить диалоговые JSON без изменения файлов")
    pair.add_argument("before")
    pair.add_argument("after")
    lint = commands.add_parser("lint", help="Подсказать места для редакторской проверки")
    lint.add_argument("file")
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            errors = compare(read_json(args.before), read_json(args.after))
            print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
            return 1 if errors else 0
        path = Path(args.file)
        if path.suffix.lower() == ".json":
            scene = read_json(path)
            validate_scene(scene)
            findings = [dict(item, id=line["id"]) for line in scene["lines"]
                        for item in lint_text(line["text"])]
        else:
            findings = lint_text(path.read_text(encoding="utf-8-sig"))
        print(json.dumps({"note": "Подсказки, не ошибки. Автозамен нет.", "findings": findings},
                         ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
