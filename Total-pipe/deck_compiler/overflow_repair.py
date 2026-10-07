"""Automatic overflow repair: split slides with severe text overflow.

This module detects text overflow warnings from OfficeCLI and automatically
splits content across additional slides when overflow exceeds threshold.
"""
import copy
import math
import re
from collections import defaultdict
from typing import Dict, List, Tuple, Any


def parse_overflow_message(message: str) -> Tuple[float, float]:
    """Parse OfficeCLI overflow message to extract needed and usable heights.

    Example: "text overflow: 3 lines at 15.0pt need 56pt, usable 47pt. suggest.height=2cm"
    Returns: (needed_pt, usable_pt)
    """
    match = re.search(r'need (\d+(?:\.\d+)?)pt, usable (\d+(?:\.\d+)?)pt', message)
    if match:
        return float(match.group(1)), float(match.group(2))
    return 0.0, 0.0


def extract_shape_id(xpath: str) -> str:
    """Extract shape ID from OfficeCLI XPath.

    Example: "/slide[1]/shape[@id=100008]" -> "100008"
    """
    match = re.search(r'@id=(\d+)', xpath)
    if match:
        return match.group(1)
    return ""


def find_block_by_element_id(slide: Dict, element_id: str) -> Dict:
    """Find the IR block corresponding to a layout element ID.

    Element IDs in layout.json come from block IDs in deck_ir.json.
    Some have suffixes like ":label" or are figure captions.
    """
    blocks = slide['composition']['blocks']

    # Try exact match first
    for block in blocks:
        if block['id'] == element_id:
            return block

    # Try without suffix (e.g., "method:label" -> "method")
    base_id = element_id.split(':')[0]
    for block in blocks:
        if block['id'] == base_id:
            return block

    return None


def split_text_to_chunks(text: str, target_chunks: int) -> List[str]:
    """Split text into N roughly equal chunks, preserving paragraph boundaries.

    Args:
        text: The text to split (may contain \n for paragraphs)
        target_chunks: Number of chunks desired

    Returns:
        List of text chunks
    """
    if target_chunks <= 1:
        return [text]

    paragraphs = [p for p in text.split('\n') if p.strip()]
    if not paragraphs:
        return [text]

    # Try to split paragraphs evenly
    if len(paragraphs) >= target_chunks:
        paras_per_chunk = len(paragraphs) // target_chunks
        chunks = []
        for i in range(target_chunks):
            start = i * paras_per_chunk
            end = start + paras_per_chunk if i < target_chunks - 1 else len(paragraphs)
            chunks.append('\n'.join(paragraphs[start:end]))
        return chunks

    # Fewer paragraphs than chunks: split by character count
    char_count = len(text)
    chars_per_chunk = char_count // target_chunks
    chunks = []
    current = ""

    for paragraph in paragraphs:
        if len(current) + len(paragraph) < chars_per_chunk * 1.2:
            current += ("\n" if current else "") + paragraph
        else:
            if current:
                chunks.append(current)
            current = paragraph

    if current:
        chunks.append(current)

    # If we ended up with fewer chunks, pad with empty strings
    while len(chunks) < target_chunks:
        chunks.append("")

    return chunks[:target_chunks]


def repair_overflow(ir: Dict, layout: Dict, qa_report: Dict,
                   overflow_threshold: float = 0.25) -> Tuple[Dict, bool]:
    """Detect severe text overflow and split slides to accommodate content.

    Args:
        ir: The canonical deck_ir.json
        layout: The compiled layout.json
        qa_report: The qa_report.json with OFFICECLI_FORMAT warnings
        overflow_threshold: Split when (needed-usable)/usable exceeds this (default 25%)

    Returns:
        (repaired_ir, was_modified)
    """
    # Find overflow warnings
    overflows = [
        item for item in qa_report.get('items', [])
        if item.get('severity') == 'WARNING'
        and item.get('rule') == 'OFFICECLI_FORMAT'
        and 'text overflow' in item.get('message', '')
    ]

    if not overflows:
        return ir, False

    # Group by slide number
    slides_to_repair = defaultdict(list)
    for overflow in overflows:
        slide_num = overflow.get('slide')
        if not slide_num or not isinstance(slide_num, int):
            continue

        shape_xpath = overflow.get('shape', '')
        needed, usable = parse_overflow_message(overflow['message'])

        if usable > 0:
            overflow_ratio = (needed - usable) / usable
            if overflow_ratio > overflow_threshold:
                slides_to_repair[slide_num].append({
                    'shape_xpath': shape_xpath,
                    'shape_id': extract_shape_id(shape_xpath),
                    'needed': needed,
                    'usable': usable,
                    'overflow_ratio': overflow_ratio,
                    'message': overflow['message']
                })

    if not slides_to_repair:
        return ir, False

    # Create repaired IR
    new_ir = copy.deepcopy(ir)
    new_slides = []
    slides_added = 0

    for original_idx, original_slide in enumerate(ir['slides'], 1):
        if original_idx not in slides_to_repair:
            # No overflow, keep as-is
            new_slides.append(copy.deepcopy(original_slide))
            continue

        # This slide has severe overflow
        overflow_items = slides_to_repair[original_idx]

        # Find the worst overflow for this slide
        worst = max(overflow_items, key=lambda x: x['overflow_ratio'])

        # Map shape ID back to element in layout
        layout_slide = layout['slides'][original_idx - 1]
        element = None
        for elem in layout_slide.get('elements', []):
            if str(elem.get('id', '')).endswith(worst['shape_id']) or \
               worst['shape_id'] in str(elem.get('id', '')):
                element = elem
                break

        if not element or element['kind'] != 'text':
            # Can't identify the overflowing element, keep original
            new_slides.append(copy.deepcopy(original_slide))
            continue

        # Find corresponding block in IR
        element_id = element['id']
        block = find_block_by_element_id(original_slide, element_id)

        if not block or 'text' not in block:
            # Can't find block or it has no text, keep original
            new_slides.append(copy.deepcopy(original_slide))
            continue

        # Calculate how many slides we need
        chunks_needed = math.ceil(1.0 + worst['overflow_ratio'])
        chunks_needed = min(chunks_needed, 4)  # Cap at 4 slides per original

        # Split the overflowing text
        original_text = block['text']
        text_chunks = split_text_to_chunks(original_text, chunks_needed)

        # Create slides for each chunk
        for chunk_idx, chunk_text in enumerate(text_chunks):
            if not chunk_text.strip():
                continue  # Skip empty chunks

            new_slide = copy.deepcopy(original_slide)

            if chunk_idx > 0:
                # This is a continuation slide
                new_slide['id'] = f"{original_slide['id']}-cont{chunk_idx}"

                # Update title to indicate continuation
                original_title = original_slide['semantic']['title']
                new_slide['semantic']['title'] = f"{original_title} ({chunk_idx + 1}/{chunks_needed})"

                # Add note about continuation
                notes = new_slide['semantic'].get('speaker_notes', '')
                new_slide['semantic']['speaker_notes'] = (
                    f"[Continuation {chunk_idx + 1}/{chunks_needed}] " + notes
                )

            # Update the overflowing block with this chunk
            target_block = find_block_by_element_id(new_slide, element_id)
            if target_block:
                target_block['text'] = chunk_text

            new_slides.append(new_slide)

            if chunk_idx > 0:
                slides_added += 1

    if slides_added == 0:
        return ir, False

    # Update IR with new slides
    new_ir['slides'] = new_slides

    return new_ir, True


def overflow_summary(qa_report: Dict) -> Dict[str, Any]:
    """Generate summary statistics about overflow issues.

    Returns:
        Dictionary with overflow statistics
    """
    overflows = [
        item for item in qa_report.get('items', [])
        if item.get('severity') == 'WARNING'
        and item.get('rule') == 'OFFICECLI_FORMAT'
        and 'text overflow' in item.get('message', '')
    ]

    if not overflows:
        return {
            'total_overflows': 0,
            'slides_affected': 0,
            'avg_overflow_ratio': 0.0,
            'max_overflow_ratio': 0.0,
        }

    overflow_ratios = []
    slides_affected = set()

    for overflow in overflows:
        slide_num = overflow.get('slide')
        if slide_num:
            slides_affected.add(slide_num)

        needed, usable = parse_overflow_message(overflow['message'])
        if usable > 0:
            ratio = (needed - usable) / usable
            overflow_ratios.append(ratio)

    return {
        'total_overflows': len(overflows),
        'slides_affected': len(slides_affected),
        'avg_overflow_ratio': sum(overflow_ratios) / len(overflow_ratios) if overflow_ratios else 0.0,
        'max_overflow_ratio': max(overflow_ratios) if overflow_ratios else 0.0,
        'severe_overflows': sum(1 for r in overflow_ratios if r > 0.25),
    }
