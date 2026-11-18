"""Search, inspect or compile one local, maintained Deck IR example."""
import argparse
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

LIBRARY = Path(__file__).resolve().parent
COMPONENT = LIBRARY.parent.parent


def inventory():
    index = json.loads((LIBRARY/'index.json').read_text(encoding='utf-8'))
    return index['entries']


def search(query, entries, limit):
    query = query.casefold().strip()
    words = set(re.findall(r'[\w/-]+', query))
    matches = []
    for entry in entries:
        aliases = [entry['id'].casefold(), *(tag.casefold() for tag in entry['tags'])]
        exact = sum(alias in words or alias == query for alias in aliases)
        partial = sum(alias in query for alias in aliases if alias not in words)
        description = (entry['title'] + ' ' + entry['summary']).casefold()
        contextual = sum(word in description for word in words if len(word) >= 2)
        score = 8*exact + 3*partial + contextual
        if score:
            matches.append((score, entry))
    ranked = sorted(matches, key=lambda item: (-item[0], item[1]['id']))
    return [{
        'id': entry['id'], 'title': entry['title'], 'summary': entry['summary'],
        'script': str(LIBRARY/entry['script']),
    } for _, entry in ranked[:limit]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    find = sub.add_parser('search', help='Return a short ranked index in JSON')
    find.add_argument('query')
    find.add_argument('--limit', type=int, choices=range(1, 11), default=3)
    show = sub.add_parser('show', help='Print the canonical Deck IR of one example')
    show.add_argument('id')
    build = sub.add_parser('build', help='Build one editable sample using the standard compiler')
    build.add_argument('id')
    build.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    entries = inventory()
    if args.action == 'search':
        print(json.dumps(search(args.query, entries, args.limit), ensure_ascii=False, indent=2))
        return 0
    entry = next((item for item in entries if item['id'] == args.id), None)
    if entry is None:
        parser.error(f'unknown example ID {args.id!r}; use search')
    script = LIBRARY/entry['script']
    deck = runpy.run_path(str(script))['make_deck']()
    encoded = json.dumps(deck, ensure_ascii=False, indent=2) + '\n'
    if args.action == 'show':
        print(encoded, end='')
        return 0
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = output/f'{entry["id"]}.deck_ir.json'
    source.write_text(encoded, encoding='utf-8')
    return subprocess.run([sys.executable, '-m', 'deck_compiler', 'build', '--ir', str(source),
                           '--out', str(output), '--skip-native'], cwd=COMPONENT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
