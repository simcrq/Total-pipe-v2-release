"""Deck-level list treatment: turn a page of loose prose blocks into one native list.

A page whose body is five separate blocks reads as five floating paragraphs: nothing tells the
reader that the statements are parallel, ordered, or a sequence, and every block re-negotiates its
own height. Merging them into one block with one paragraph per statement and declaring
``text_flow: distributed_arrow_list`` makes the compiler draw a real native list - arrow markers,
hanging indent, distributed item gaps - while every paragraph stays exactly one approved sentence.

This module is the pure transformation. Whether a merged page actually fits is a layout question,
so the CLI wrapper compiles the candidate deck and drops the pages that overflow or shrink.
"""
import copy

DISTRIBUTED_ARROW_LIST = 'distributed_arrow_list'
DEFAULT_LIST_GAP = 0.55
DEFAULT_BULLET = 'arrow'


def walk(node):
    """Yield every container and leaf in a region tree."""
    yield node
    for child in node.get('children', []):
        yield from walk(child)


def leaves(frame):
    return [node for node in walk(frame) if node.get('type') not in ('columns', 'stack')]


def block_order(frame, blocks):
    """Body blocks in the order the page reads them, then any block the tree does not reach."""
    by_id = {block['id']: block for block in blocks}
    refs = [leaf['ref'] for leaf in leaves(frame) if leaf.get('type') == 'block']
    ordered = [by_id[ref] for ref in refs if ref in by_id]
    for block in blocks:
        if block['id'] not in refs:
            ordered.append(block)
    return ordered


def merge_page(composition, page_id):
    """Return (blocks, frame) with one native list per page, or None if the page cannot be a list."""
    frame = composition['layout_tree']['regions']['body']
    blocks = composition.get('blocks', [])
    ordered = block_order(frame, blocks)
    if len(ordered) < 2:
        return None
    # Inline math keeps auto/plain flow, and a list run cannot carry an equation.
    if any(block.get('inline_math') or '$' in str(block.get('text') or '') for block in ordered):
        return None
    # A native list owns one marker run: mixed component types would lose their own styling.
    if len({block.get('component', 'body') for block in ordered}) > 1:
        return None

    head = copy.deepcopy(ordered[0])
    head.update({'id': f'{page_id}-list', 'component': 'body',
                 'text': '\n'.join(block['text'].strip() for block in ordered),
                 'text_flow': DISTRIBUTED_ARROW_LIST})
    head.pop('label', None)
    leaf = {'id': f'{page_id}-{head["id"]}', 'type': 'block', 'ref': head['id']}

    visuals = [node for node in leaves(frame) if node.get('type') != 'block']
    if not visuals:
        frame_out = {'id': f'{page_id}-body', 'type': 'stack', 'gap': 'standard', 'children': [leaf]}
    elif len(visuals) == 1 and visuals[0].get('type') == 'chart':
        frame_out = {'id': f'{page_id}-body', 'type': 'columns', 'gap': 'standard',
                     'weights': [1.15, 1],
                     'children': [{'id': f'{page_id}-chart', 'type': 'stack', 'gap': 'standard',
                                   'children': [visuals[0]]},
                                  {'id': f'{page_id}-text', 'type': 'stack', 'gap': 'standard',
                                   'children': [leaf]}]}
    else:
        # Panels keep a row of their own above the list, so the list always clears its 520 px
        # minimum width; stacking them vertically would eat the band.
        cover = (visuals[0] if len(visuals) == 1 else
                 {'id': f'{page_id}-visuals', 'type': 'columns', 'gap': 'standard',
                  'weights': [1] * len(visuals), 'children': visuals})
        frame_out = {'id': f'{page_id}-body', 'type': 'stack', 'gap': 'standard',
                     'children': [cover, {'id': f'{page_id}-text', 'type': 'stack',
                                          'gap': 'standard', 'children': [leaf]}]}
    return [head], frame_out


def candidates(ir):
    """Slide ids that can become lists, in deck order."""
    return [slide['id'] for slide in ir['slides']
            if merge_page(slide['composition'], slide['id'])]


def apply(ir, page_ids, bullet=DEFAULT_BULLET, gap=DEFAULT_LIST_GAP):
    """Return a copy of ``ir`` with the named pages merged into native lists."""
    wanted = set(page_ids)
    out = copy.deepcopy(ir)
    listing = set()
    for slide in out['slides']:
        if slide['id'] not in wanted:
            continue
        merged = merge_page(slide['composition'], slide['id'])
        if merged is None:
            continue
        blocks, frame = merged
        slide['composition']['blocks'] = blocks
        slide['composition']['layout_tree']['regions']['body'] = frame
        listing.add(blocks[0]['id'])
    if listing:
        presentation = out.setdefault('presentation', {})
        presentation['bullet_style'] = bullet
        presentation['list_gap'] = gap
        for slide in out['slides']:
            for node in walk(slide['composition']['layout_tree']['regions']['body']):
                kids = node.get('children', [])
                if (node.get('type') == 'stack' and len(kids) == 1
                        and kids[0].get('type') == 'block' and kids[0].get('ref') in listing
                        and 'weights' not in node):
                    # Distribute spreads the items down the band instead of leaving the list
                    # packed at the top of a tall region.
                    node['align'] = 'distribute'
    return out
