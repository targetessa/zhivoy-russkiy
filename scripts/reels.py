#!/usr/bin/env python3
"""Read-only checks for the example Reels format; no assessment of facts or style."""
import argparse
import json
from pathlib import Path
import sys

from quality import InputError, read_json, signature
from video import validate as validate_video, word_count


def normalized(text):
    return " ".join(text.split())


def check(script):
    validate_video(script)
    recording = script.get("recording_text")
    if not isinstance(recording, str) or not recording.strip():
        raise InputError("Нужен непустой recording_text с полной озвучкой")
    limit = script.get("max_words")
    if type(limit) is not int or limit <= 0:
        raise InputError("max_words должен быть положительным целым числом")
    hooks = script.get("hooks")
    if (not isinstance(hooks, list) or len(hooks) != 3
            or any(not isinstance(hook, str) or not hook.strip() for hook in hooks)):
        raise InputError("Нужны три непустых строковых хука в hooks; первый используется в сценарии")
    if len({normalized(hook) for hook in hooks}) != 3:
        raise InputError("Хуки не должны дословно повторяться")

    # Counts require actual spoken words, not template variables or markup.
    for text in [recording, *hooks, *(block['speech'] for block in script['blocks'])]:
        tokens = signature(text)
        if (tokens['вставки'] or tokens['теги']
                or any(token != '%%' for token in tokens['printf'])):
            raise InputError("Подставьте произносимые значения и уберите теги из речи и хуков")

    errors = []
    blocks = script['blocks']
    speech = normalized(" ".join(block['speech'] for block in blocks))
    if speech != normalized(recording):
        errors.append("Текст для записи отличается от соединённой речи сцен")
    first = normalized(blocks[0]['speech'])
    hook = normalized(hooks[0])
    if first != hook and not first.startswith(hook + " "):
        errors.append("Первый хук не совпадает с началом первой сцены")

    previous_end = 0
    for block in blocks:
        if 'start' not in block or 'end' not in block:
            errors.append(block['id'] + ": нужны start и end")
            continue
        if abs(block['start'] - previous_end) > 1e-9:
            errors.append(block['id'] + ": в плане времени есть пропуск")
        previous_end = block['end']
    if abs(previous_end - script['duration_seconds']) > 1e-9:
        errors.append("План сцен не заканчивается на duration_seconds")
    words = word_count(recording)
    if words > limit:
        errors.append(f"В озвучке {words} слов при пределе {limit}")
    return {"ok": not errors, "words": words, "max_words": limit, "errors": errors,
            "timing": "planned; not recorded",
            "scope": "format, exact text agreement, word count and planned intervals only"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    verify = subs.add_parser('check')
    verify.add_argument('file', type=Path)
    args = parser.parse_args(argv)
    try:
        result = check(read_json(args.file))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 2
    except (InputError, ValueError, OSError, UnicodeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
