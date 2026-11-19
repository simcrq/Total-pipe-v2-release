"""Search the example metadata shared by the standalone catalog and IR prompts."""
import json
from pathlib import Path
import re


LIBRARY = Path(__file__).resolve().parents[1]/'examples/library'


def inventory():
    return json.loads((LIBRARY/'index.json').read_text(encoding='utf-8'))['entries']


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
