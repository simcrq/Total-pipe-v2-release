"""Small stable archetype catalog; semantic slots, not agent-authored bboxes."""
ARCHETYPES = {
    "cover-hero": {"blocks": 2, "figures": 1, "layout": "figure-right"},
    "metric-comparison": {"blocks": 4, "figures": 0, "layout": "columns"},
    "process-flow": {"blocks": 4, "figures": 1, "layout": "process"},
    "figure-parameters": {"blocks": 4, "figures": 1, "layout": "figure-left"},
    "hero-dual-evidence": {"blocks": 2, "figures": 2, "layout": "dual"},
    "evidence-hypothesis": {"blocks": 8, "figures": 0, "layout": "evidence"},
    "dual-demonstration": {"blocks": 2, "figures": 2, "layout": "dual"},
    "three-limitations": {"blocks": 3, "figures": 0, "layout": "columns"},
    "three-conclusions": {"blocks": 3, "figures": 0, "layout": "columns"},
}
COMPONENTS = {
    "body", "metric", "parameter", "process-step", "direct-evidence", "hypothesis",
    "limitation", "conclusion", "callout", "comparison", "definition", "observation",
    "method", "result", "question", "source", "caveat",
}
