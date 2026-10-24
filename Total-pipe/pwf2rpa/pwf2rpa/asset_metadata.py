"""Pass explicitly referenced PWF image facts to RPA without interpreting the paper."""
from urllib.parse import unquote

from .errors import Problem


def enrich_visuals(briefs, workflow):
    artifacts = workflow.get('artifacts')
    records = artifacts.get('figure_assets_metadata', []) if isinstance(artifacts, dict) else []
    index = {}
    for record in records if isinstance(records, list) else []:
        if isinstance(record, dict):
            for key in ('asset_id', 'path'):
                if isinstance(record.get(key), str):
                    index[record[key]] = record
    warnings = []
    for i, brief in enumerate(briefs):
        for j, visual in enumerate(brief.get('visuals', [])):
            # Exact portable identity only: basename matching could substitute another figure.
            record = next((index[unquote(visual[key])] for key in ('source_asset_id', 'asset_uri', 'uri')
                if isinstance(visual.get(key), str) and unquote(visual[key]) in index), None)
            if not record:
                continue
            fields = {key: record[key] for key in ('source_width_px', 'source_height_px',
                'visual_aspect_ratio', 'image_kind', 'image_format', 'crop_allowed') if key in record}
            fields['source_asset_id'] = record.get('asset_id', record.get('path'))
            for key, value in fields.items():
                if key not in visual:
                    visual[key] = value
                elif visual[key] != value:
                    warnings.append(Problem('ASSET_METADATA_CONFLICT', f'slide_briefs[{i}].visuals[{j}].{key}',
                        'Explicit visual metadata differs from the referenced PWF asset; inspect the source.',
                        actual=visual[key], expected=value, severity='warning'))
    return warnings
