"""PaperWorkflow v4 -> Research PPT Assistant content-model bridge.

Typical use::

    from pwf2rpa import Workflow, convert, load_story, write_output

    workflow = Workflow.from_path("workflow.json")
    workflow.validate()
    payload, warnings = convert(workflow, story=load_story("story_plan.json"))
    write_output(payload, "rpa_input.json")

Or from the shell::

    python3 pwf_to_rpa.py workflow.json --story story_plan.json --out rpa_input.json

The package is standard-library only and deterministic: identical inputs
produce byte-identical output.
"""

from .briefs import build_briefs
from .capacity import CATEGORIES, LAYOUT_LIBRARY_VERSION
from .convert import convert, load_specs, write_output
from .errors import AdapterError, BriefError, Problem, StoryError, WorkflowError
from .fallback import fallback_specs
from .fit import PageShape, category_ids, evaluate, is_known_category
from .story import build_story_prompt, load_story, story_to_specs, validate_story
from .workflow import Evidence, Workflow

__version__ = "1.1.0"

__all__ = [
    "AdapterError",
    "BriefError",
    "CATEGORIES",
    "Evidence",
    "LAYOUT_LIBRARY_VERSION",
    "PageShape",
    "Problem",
    "StoryError",
    "Workflow",
    "WorkflowError",
    "__version__",
    "build_briefs",
    "build_story_prompt",
    "category_ids",
    "convert",
    "evaluate",
    "fallback_specs",
    "is_known_category",
    "load_specs",
    "load_story",
    "story_to_specs",
    "validate_story",
    "write_output",
]
