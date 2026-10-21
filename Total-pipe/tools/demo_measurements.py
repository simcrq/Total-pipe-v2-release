"""Measure the same fixture with both bundled providers and write the numbers the demo deck plots.

The demo deck cites layout quality in its text and in one figure. Regenerating both from one
measurement file keeps the prose, the chart and the compiler from drifting apart.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from deck_compiler.layout_provider import (  # noqa: E402
    CompilerProvider, PackerProvider, compile_with_provider)
import test_packer_quality as fixture  # noqa: E402


def summarise(provider, ir_path):
    layout, issues = compile_with_provider(ir_path, provider)
    measured = fixture.measure(layout, ir_path)
    slack = measured['slack']
    return {
        'provider': provider.name,
        'pages': len(layout['slides']),
        'counts': layout['layout_provider']['counts'],
        'slack_mean': round(sum(slack) / len(slack), 2),
        'slack_max': round(max(slack), 2),
        'boxes': len(slack),
        'void_max': round(max(measured['void']), 3) if measured['void'] else None,
        'orphans': measured['orphans'],
        'min_font_pt': min(measured['fonts']),
        'fail': [issue['rule'] for issue in issues if issue['severity'] == 'FAIL'],
    }


def fixture_runs():
    runs = []
    with tempfile.TemporaryDirectory() as name:
        base = Path(name)
        fixture.build_fixture(base)
        path = base / 'deck_ir.json'
        path.write_text(json.dumps(fixture.build_fixture(base)), encoding='utf-8')
        for provider in (CompilerProvider(), PackerProvider()):
            runs.append(summarise(provider, path))
    return runs


def example_runs():
    path = ROOT / 'examples/research.deck_ir.json'
    return [summarise(provider, path) for provider in (CompilerProvider(), PackerProvider())]


def main():
    data = {'figure_fixture': fixture_runs(), 'research_example': example_runs()}
    target = ROOT / 'examples/demo_deck/measurements.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
