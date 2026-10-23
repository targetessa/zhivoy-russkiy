#!/usr/bin/env python3
"""Check package references, routes, evaluation inputs and technical examples offline."""
import json
from pathlib import Path
import re
import sys
from build_prompt import compile_prompt, profiles
from quality import InputError, compare, read_json
from video import compare as compare_video
ROOT = Path(__file__).resolve().parents[1]


def check():
    errors = []
    for path in sorted(ROOT.rglob('*.md')):
        if '.git' in path.parts:
            continue
        text = path.read_text(encoding='utf-8')
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
                continue
            target = target.split('#')[0]
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(ROOT.resolve()) or not resolved.is_file():
                errors.append(f'{path.relative_to(ROOT)}: broken local link: {target}')
    for profile in profiles():
        compile_prompt(profile)
        compile_prompt(profile, 'voice')
    fragments = read_json(ROOT / 'evals/fragments.json')['cases']
    ids = [case['id'] for case in fragments]
    if len(ids) < 30 or len(ids) != len(set(ids)):
        errors.append('Need at least 30 uniquely identified fragments')
    for case in fragments:
        if case['profile'] not in profiles() or not all(case.get(key) for key in ['request','input','must','must_not']):
            errors.append(f"Invalid evaluation case: {case.get('id')}")
    for profile in profiles():
        if not any(c['profile'] == profile and c.get('good_source') is True for c in fragments):
            errors.append(f'No good-source control for {profile}')
    regressions = read_json(ROOT / 'evals/cases.json')['cases']
    if len({case['id'] for case in regressions}) != len(regressions):
        errors.append('Duplicate regression IDs')
    errors += compare(read_json(ROOT/'examples/scene.before.json'),read_json(ROOT/'examples/scene.after.json'))
    errors += compare_video(read_json(ROOT/'examples/video.before.json'),read_json(ROOT/'examples/video.after.json'))
    return {'ok': not errors, 'profiles':len(profiles()),'fragments':len(fragments),
            'regression_cases':len(regressions),'errors':errors}


if __name__ == '__main__':
    try:
        result=check()
        print(json.dumps(result,ensure_ascii=False,indent=2))
        raise SystemExit(0 if result['ok'] else 2)
    except (OSError, ValueError, KeyError, InputError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
