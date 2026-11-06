"""Deterministic guards for supplement content in a Deck IR.

The compiler can see the IR but not the PaperWorkflow evidence text.  This module
lives in the agent layer, where ``normalized_content.json`` is available, and
answers one question: did a supplement block quietly reuse a paper number, a long
verbatim passage or a paper figure?  It never judges scientific quality.
"""
from __future__ import annotations

import re


# Numbers with a unit, or a decimal/large integer, are specific enough to be
# recognised as a paper measurement.  Bare small integers (step 1, 2, 3) are not.
_UNIT = (r"%|‰|nm|µm|um|mm|cm|km|m|ms|s|min|h|kg|mg|µg|ug|ng|mL|ml|L|kJ|J|kW|W|mW|"
         r"keV|MeV|eV|mV|kV|mA|A|kHz|MHz|GHz|Hz|dB|Ω|ohm|kPa|MPa|GPa|Pa|"
         r"mol|mmol|wt%|at%|ppm|ppb|°C|℃|K")
_NUMBER = re.compile(
    rf"(?<![A-Za-z0-9_.])(?:\d+(?:\.\d+)?(?:\s*[×x]\s*10\s*\^?\s*[-+]?\d+)?|"
    rf"\d+(?:\.\d+)?\s*\^\s*[-+]?\d+|\d+\.\d+)"
    rf"\s*(?:{_UNIT})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_DECIMAL = re.compile(r"(?<![A-Za-z0-9_.])\d+\.\d+(?![A-Za-z0-9_.])")
_CJK = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD = re.compile(r"[a-z0-9]+")


def _text(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def _evidence_texts(normalized):
    result = []
    for entry in normalized.get("evidence", []) or []:
        if not isinstance(entry, dict):
            continue
        text = _text(entry.get("text") or entry.get("evidence_text") or entry.get("claim"))
        if text:
            result.append((entry.get("evidence_id") or entry.get("id") or "EV?", text))
    return result


def _number_tokens(text):
    # Compare common canonical inline-math notation with the source measurement,
    # including IR already normalized by a previous submission.
    text = re.sub(r"\\(?:mathrm|text)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\^\{([-+]?\d+)\}", r"^\1", text)
    for old, new in ((r"\Omega", "Ω"), (r"\%", "%"), (r"\times", "×"),
                     (r"\,", " "), (r"\;", " "), (r"\!", ""), ("$", "")):
        text = text.replace(old, new)
    return {token.casefold().replace(" ", "") for token in
            _NUMBER.findall(text) + _DECIMAL.findall(text)}


def _cjk_overlap(needle, haystack, size=12):
    compact = "".join(char for char in needle.casefold() if _CJK.match(char))
    if len(compact) < size:
        return ""
    source = "".join(char for char in haystack.casefold() if _CJK.match(char))
    for index in range(0, len(compact) - size + 1):
        fragment = compact[index:index + size]
        if fragment in source:
            return fragment
    return ""


def _latin_overlap(needle, haystack, words=8):
    left = _LATIN_WORD.findall(needle.casefold())
    right = _LATIN_WORD.findall(haystack.casefold())
    if len(left) < words:
        return ""
    for index in range(0, len(left) - words + 1):
        fragment = " ".join(left[index:index + words])
        if fragment in " ".join(right):
            return fragment
    return ""


def _scan(text, speaker, slide_id, evidence, evidence_numbers):
    if not text:
        return []
    messages = []
    for token in sorted(_number_tokens(text)):
        if token in evidence_numbers:
            messages.append(
                f"slide {slide_id} {speaker}: supplement reuses the paper value "
                f"{token!r}; cite the paper block and its evidence, or remove the value")
    for evidence_id, source in evidence:
        fragment = _cjk_overlap(text, source) or _latin_overlap(text, source)
        if fragment:
            messages.append(
                f"slide {slide_id} {speaker}: supplement repeats {evidence_id} "
                f"verbatim ({fragment[:40]!r}); use a paper block or paraphrase")
            break
    return messages


def leak_messages(ir, normalized):
    """Return FAIL-level messages for supplement content that reuses paper material."""
    if not isinstance(ir, dict) or not isinstance(normalized, dict):
        return []
    evidence = _evidence_texts(normalized)
    if not evidence:
        return []
    evidence_numbers = {token for _, text in evidence for token in _number_tokens(text)}
    messages = []
    for slide in ir.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        comp = slide.get("composition") if isinstance(slide.get("composition"), dict) else {}
        blocks = [block for block in comp.get("blocks", []) or [] if isinstance(block, dict)]
        supplements = [block for block in blocks if block.get("basis") == "supplement"]
        if not supplements:
            continue
        sem = slide.get("semantic") if isinstance(slide.get("semantic"), dict) else {}
        slide_id = slide.get("id") or "?"
        for block in supplements:
            speaker = f"block {block.get('id') or '?'}"
            messages.extend(_scan(_text(block.get("text")), speaker, slide_id,
                                  evidence, evidence_numbers))
            messages.extend(_scan(_text(block.get("label")), speaker + " label", slide_id,
                                  evidence, evidence_numbers))
        # A page made only of supplement blocks owns its title and takeaway too.
        # A mixed page may keep a paper claim in the title, so only block text is
        # checked there.
        if len(supplements) == len(blocks):
            for key in ("title", "takeaway"):
                messages.extend(_scan(_text(sem.get(key)), f"semantic.{key}", slide_id,
                                      evidence, evidence_numbers))
    return messages
