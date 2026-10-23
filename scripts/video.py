#!/usr/bin/env python3
"""Read-only checks for the demo script contract and conditional speech estimates."""
import argparse
import json
import math
from pathlib import Path
import re
import sys
from quality import InputError, read_json, signature


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def word_count(text):
    # A documented planning unit: Unicode words, with internal hyphens/apostrophes.
    return len(re.findall(r"[^\W_]+(?:[-’'][^\W_]+)*", text, re.UNICODE))


def estimate(text, min_wpm, max_wpm, pause_seconds=0):
    if not positive(min_wpm) or not positive(max_wpm) or min_wpm > max_wpm:
        raise InputError("Нужен положительный диапазон темпа min <= max")
    if type(pause_seconds) not in (int, float) or not math.isfinite(pause_seconds) or pause_seconds < 0:
        raise InputError("Паузы должны быть конечным неотрицательным числом")
    contract = signature(text)
    if contract["вставки"] or any(token != "%%" for token in contract["printf"]):
        raise InputError("Перед оценкой времени подставьте реальные значения переменных")
    if contract["теги"]:
        raise InputError("Перед оценкой времени подготовьте произносимый текст без тегов")
    words = word_count(text)
    return {"words": words, "min_seconds": words / max_wpm * 60 + pause_seconds,
            "max_seconds": words / min_wpm * 60 + pause_seconds,
            "min_wpm": min_wpm, "max_wpm": max_wpm, "pause_seconds": pause_seconds,
            "method": "word-count estimate; not recorded timing"}


def validate(script):
    if not isinstance(script, dict) or not positive(script.get("duration_seconds")):
        raise InputError("Нужен объект с положительным duration_seconds")
    blocks = script.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise InputError("Нужен непустой массив blocks")
    ids = set()
    previous_end = 0
    for block in blocks:
        if not isinstance(block, dict):
            raise InputError("Блок должен быть объектом")
        ident = block.get("id")
        if not isinstance(ident, str) or not ident.strip() or ident in ids:
            raise InputError("Нужны уникальные непустые id блоков")
        ids.add(ident)
        if not isinstance(block.get("speech"), str) or not isinstance(block.get("role"), str) or not block["role"].strip():
            raise InputError("Нужны строковые role и speech")
        if ("start" in block) != ("end" in block):
            raise InputError("start и end задаются вместе")
        if "start" in block:
            start, end = block["start"], block["end"]
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end)
                    or not (previous_end <= start < end <= script["duration_seconds"])):
                raise InputError("Неверный порядок или границы таймкодов")
            previous_end = end
        signature(block["speech"])


def compare(before, after):
    validate(before)
    validate(after)
    def frozen(script):
        copy = dict(script)
        copy["blocks"] = [dict(block, speech="") for block in script["blocks"]]
        return json.dumps(copy, ensure_ascii=False, sort_keys=True, allow_nan=False)
    errors = []
    if frozen(before) != frozen(after):
        errors.append("Изменены поля вне blocks[i].speech: структура, порядок или метаданные")
    for old, new in zip(before["blocks"], after["blocks"]):
        left, right = signature(old["speech"]), signature(new["speech"])
        for key in left:
            if left[key] != right[key]:
                errors.append(old["id"] + ": изменены " + key)
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    check = subs.add_parser("compare")
    check.add_argument("before", type=Path)
    check.add_argument("after", type=Path)
    timing = subs.add_parser("estimate")
    timing.add_argument("file", type=Path, help="UTF-8 speech text, or --script JSON")
    timing.add_argument("--script", action="store_true")
    timing.add_argument("--min-wpm", required=True, type=float)
    timing.add_argument("--max-wpm", required=True, type=float)
    timing.add_argument("--pause-seconds", type=float, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            errors = compare(read_json(args.before), read_json(args.after))
            print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
            return 2 if errors else 0
        script = read_json(args.file) if args.script else None
        if script is not None:
            validate(script)
            text = " ".join(block["speech"] for block in script["blocks"])
        else:
            text = args.file.read_text(encoding="utf-8-sig")
        result = estimate(text, args.min_wpm, args.max_wpm, args.pause_seconds)
        if script is not None:
            result["budget_seconds"] = script["duration_seconds"]
            result["over_budget_certain"] = result["min_seconds"] > script["duration_seconds"]
            result["over_budget_possible"] = result["max_seconds"] > script["duration_seconds"]
            result["blocks"] = []
            for block in script["blocks"]:
                item = estimate(block["speech"], args.min_wpm, args.max_wpm)
                item["id"] = block["id"]
                if "start" in block:
                    item["budget_seconds"] = block["end"] - block["start"]
                    item["over_budget_certain"] = item["min_seconds"] > item["budget_seconds"]
                    item["over_budget_possible"] = item["max_seconds"] > item["budget_seconds"]
                result["blocks"].append(item)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get("over_budget_certain") or any(b.get("over_budget_certain") for b in result.get("blocks", [])) else 0
    except (InputError, ValueError, OSError, UnicodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
