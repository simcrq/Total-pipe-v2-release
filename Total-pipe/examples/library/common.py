"""Minimal Deck IR scaffolding shared by the maintained examples."""
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[1]
SOURCE = 'fixture:layout-examples'


def block_leaf(ref):
    return {'id': f'block-{ref}', 'type': 'block', 'ref': ref}


def region(id, kind, children, **options):
    return {'id': id, 'type': kind, 'gap': 'compact', 'children': children, **options}


def chip_panel(id, title, body):
    return {'id': id, 'type': 'panel', 'title': title, 'padding': 'compact', 'gap': 'compact',
            'frame': {'title_band': 'chip', 'title_fill': '#266E72', 'title_color': '#FFFFFF'},
            'body': body}


def comparison_table(id, rows, column_weights):
    return {'id': id, 'origin': 'generated', 'header_rows': 1,
            'row_count': len(rows), 'column_count': len(rows[0]), 'column_weights': column_weights,
            'cells': [{'id': f'cell-{row}-{column}', 'row': row, 'column': column,
                       'text': value, 'align': 'left' if column == 0 else 'center'}
                      for row, values in enumerate(rows) for column, value in enumerate(values)]}


def page(id, title, takeaway, blocks, body, *, figures=(), graphics=(), tables=(), charts=(),
         evidence_refs=(SOURCE,), presentation=None):
    composition = {
        'archetype': 'composite-research', 'blocks': blocks, 'figure_refs': list(figures),
        'graphics': list(graphics), 'layout_tree': {'version': '1.2', 'regions': {'body': body}},
    }
    if tables:
        composition['tables'] = list(tables)
    if charts:
        composition['charts'] = list(charts)
    return {
        'id': id,
        'semantic': {'title': title, 'takeaway': takeaway,
                     'purpose': 'Illustrate an editable layout pattern',
                     'evidence_refs': list(evidence_refs), 'caveats': [],
                     'speaker_notes': 'Layout example. Replace the sample text and source references with approved project content.'},
        'composition': composition,
        'presentation': dict(presentation) if presentation else {},
    }


def deck(id, slides, assets=None, *, presentation=None, theme=None):
    base_theme = {'font_family': 'Arial', 'font_file': 'arial.ttf', 'bold_font_file': 'arialbd.ttf',
                  'accent': '#266E72', 'foreground': '#142735', 'background': '#FFFFFF'}
    if theme:
        base_theme.update(theme)
    base_pres = {
        'academic_design': {'style': 'research-seminar', 'title_treatment': 'thin-rule',
                            'density': 'balanced', 'figure_treatment': 'unframed',
                            'decoration_policy': 'minimal', 'header_variant': 'compact'},
        'text_capacity_policy': 'preserve-terms',
    }
    if presentation:
        for key, value in presentation.items():
            if key == 'academic_design' and isinstance(value, dict):
                base_pres['academic_design'] = {**base_pres['academic_design'], **value}
            else:
                base_pres[key] = value
    return {
        'schema_version': '2.0', 'deck_id': id,
        'theme': base_theme,
        'presentation': base_pres,
        'assets': assets or {},
        'slides': slides,
    }
