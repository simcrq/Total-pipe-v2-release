"""Audience-facing text versus presenter-facing provenance.

The Deck IR has always carried both kinds of sentence in the same fields. A
caveat such as "D* assumes shot noise" bounds the scientific claim and belongs on
the page; "only the main PDF was available in this run" is honest provenance, but
it tells the room about the presenter's files instead of about the device. An
evidence id in a footer is the same mistake in miniature: a trace for the person
who checks the deck, printed where the audience reads results.

The compiler cannot invent this distinction per page, so it is classified once
here. Nothing is deleted: run-state text moves to the speaker notes and raises a
REVIEW, which keeps the provenance and still leaves the page readable.
"""
import re

#: PaperWorkflow evidence ids, e.g. EV0014. They are traceability keys, not slide copy.
EVIDENCE_ID = re.compile(r"\bEV\d{3,}\b")

#: Repository artefacts and file names. A deck may cite a paper, never a build path.
FILE_PATH = re.compile(
    r"(?<![\w/])[\w.-]+\.(?:py|json|pptx|pptm|md|pdf|csv|tsv|png|svg|xlsx)\b"
    r"|(?<![\w/])(?:builds|docs|tests|tools|examples|schemas)/"
)

#: Phrases that describe *this run's* inputs rather than the paper's own limits.
#: Deliberately narrow: "作者未提供误差棒" is a scientific critique and stays.
RUN_STATE = (
    "本次输入", "本次没有", "本次仅", "本次只拿", "本轮",
    "手头只有", "手头仅", "只拿到", "输入仅有", "仅有主文", "主文 PDF",
    "未取得", "未审阅", "没有 SI", "SI 未",
)

#: Caveat clauses are separated by ；/; -- the unit that can change destination.
CLAUSE_SPLIT = re.compile(r"[；;]")


def evidence_ids(text):
    return EVIDENCE_ID.findall(text or "")


def file_paths(text):
    return FILE_PATH.findall(text or "")


def run_state_markers(text):
    return [marker for marker in RUN_STATE if marker in (text or "")]


def is_run_state(text):
    """True when a caveat is about the material this build had, not about the claim."""
    return bool(run_state_markers(text))


def split_caveats(caveats):
    """Return (visible, moved) clause by clause; nothing is deleted.

    A caveat often mixes both kinds in one sentence -- "these results are quoted
    from the cited supplement; this run had no SI to check them against".  Moving
    the whole sentence would drop the scientific half, so the split happens at
    the clause boundary and each half goes where it belongs.
    """
    visible, moved = [], []
    for caveat in caveats or []:
        for clause in CLAUSE_SPLIT.split(caveat):
            clause = clause.strip()
            if clause:
                (moved if is_run_state(clause) else visible).append(clause)
    return visible, moved


def visible_caveats(slide):
    """The caveats a reader should see on this page."""
    return split_caveats((slide.get("semantic") or {}).get("caveats"))[0]


def join_caveats(caveats):
    """One caveat band: clauses separated by ；, without doubling sentence enders."""
    band = ""
    for clause in caveats or []:
        clause = clause.strip()
        if not clause:
            continue
        if not band:
            band = clause
        elif band[-1] in "。！？!?":
            band += clause
        else:
            band += "；" + clause
    return band


def hits(text):
    """Presenter-side provenance found in one string, as (kind, value) pairs."""
    found = []
    ids = sorted(set(evidence_ids(text)))
    if ids:
        found.append(("evidence id", ", ".join(ids)))
    paths = sorted(set(file_paths(text)))
    if paths:
        found.append(("repository path", ", ".join(paths[:3])))
    markers = run_state_markers(text)
    if markers:
        found.append(("run-state note", ", ".join(markers)))
    return found
