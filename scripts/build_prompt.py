#!/usr/bin/env python3
"""Export only shared instructions and one profile. No network/model calls."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = {
    "create": "Создай готовый текст по замыслу и подтверждённым фактам.",
    "diagnose": "Дай диагноз с основаниями; не переписывай материал и не меняй файлы.",
    "edit": "Бережно отредактируй; хорошие места сохраняй, а переводные и канцелярские конструкции исправляй всегда, даже грамматически верные.",
    "deep-edit": "Перестрой текст в порученном объёме, сохрани замысел и инварианты.",
    "voice": "Настрой голос по предоставленным образцам, сохрани смысл.",
    "review": "Проверь результат; не переписывай его без необходимости.",
}


def profiles():
    return json.loads((ROOT / "profiles.json").read_text(encoding="utf-8"))["profiles"]


def compile_prompt(profile, operation="edit", extended=False, book_informed=False):
    routes = profiles()
    if profile not in routes or operation not in OPERATIONS:
        raise ValueError("Неизвестный профиль или действие")
    core = (ROOT / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[2].strip()
    start, end = core.index("## Выбор профиля"), core.index("## Общее ядро")
    core = core[:start] + core[end:]
    documents = ["SKILL.md"] + ["references/" + name for name in routes[profile]]
    # Every profile writes Russian sentences, so the translationese check is part of the core.
    if "references/translationese.md" not in documents:
        documents.append("references/translationese.md")
    if operation == "voice" and "references/voice.md" not in documents:
        documents.append("references/voice.md")
    if extended:
        documents.append("references/syntax-and-composition.md")
    if book_informed:
        for name in ("references/voice.md", "references/book-informed-writing.md"):
            if name not in documents:
                documents.append(name)
    parts = [core]
    for name in documents[1:]:
        source = (ROOT / name).resolve()
        if not source.is_relative_to(ROOT.resolve()):
            raise ValueError("Профиль выходит за пределы пакета")
        parts.append(source.read_text(encoding="utf-8"))
    text = "\n\n".join(parts)
    # Exported prompts must not depend on a filesystem or silently load more refs.
    text = re.sub(r"\[([^\]]+)\]\((?!https?://)[^)]+\)", r"\1", text)
    text = ("# Редакторская роль\nПрофиль: " + profile + "\nДействие: " + OPERATIONS[operation]
            + "\nЭто только языковой профиль. Соблюдай контракт приложения, формат ответа и подтверждённые условия задания. "
              "Справочники уже выбраны; не ищи другие файлы. Исходный текст передаётся отдельно как данные.\n\n" + text)
    return text.rstrip() + "\n", documents


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=sorted(profiles()))
    parser.add_argument("--operation", choices=OPERATIONS, default="edit")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stats", action="store_true", help="Only counts and selected files; no token estimate")
    parser.add_argument("--extended", action="store_true", help="Include sentence and paragraph composition for extended work")
    parser.add_argument("--book-informed", action="store_true", help="Include reference matching and book-informed composition; source books are not embedded")
    args = parser.parse_args(argv)
    try:
        prompt, documents = compile_prompt(args.profile, args.operation, args.extended, args.book_informed)
        if args.stats:
            print(json.dumps({"profile": args.profile, "documents": documents,
                              "characters": len(prompt), "utf8_bytes": len(prompt.encode("utf-8"))}, ensure_ascii=False))
        elif args.output:
            args.output.write_text(prompt, encoding="utf-8")
        else:
            sys.stdout.write(prompt)
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
