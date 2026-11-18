"""Minimal Deck IR scaffolding shared by the maintained examples."""
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[1]
SOURCE = 'fixture:layout-examples'


def block_leaf(ref):
    return {'id': f'block-{ref}', 'type': 'block', 'ref': ref}


def region(id, kind, children, **options):
    return {'id': id, 'type': kind, 'gap': 'compact', 'children': children, **options}


def page(id, title, takeaway, blocks, body, *, figures=(), graphics=()):
    return {
        'id': id,
        'semantic': {'title': title, 'takeaway': takeaway,
                     'purpose': 'Illustrate an editable layout pattern',
                     'evidence_refs': [SOURCE], 'caveats': [],
                     'speaker_notes': 'Constructed layout example. Replace the sample text and source references with approved project content.'},
        'composition': {
            'archetype': 'composite-research', 'blocks': blocks, 'figure_refs': list(figures),
            'graphics': list(graphics), 'layout_tree': {'version': '1.2', 'regions': {'body': body}},
        },
        'presentation': {},
    }


def deck(id, slides, assets=None):
    return {
        'schema_version': '2.0', 'deck_id': id,
        'theme': {'font_family': 'Arial', 'font_file': 'arial.ttf', 'bold_font_file': 'arialbd.ttf',
                  'accent': '#266E72', 'foreground': '#142735', 'background': '#FFFFFF'},
        'presentation': {
            'academic_design': {'style': 'research-seminar', 'title_treatment': 'thin-rule',
                                'density': 'balanced', 'figure_treatment': 'unframed',
                                'decoration_policy': 'minimal', 'header_variant': 'compact'},
            'text_capacity_policy': 'preserve-terms',
        },
        'assets': assets or {},
        'slides': slides,
    }
