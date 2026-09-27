from dataclasses import dataclass
from pathlib import Path

# Validated free-generation model. Pinned completion retains its own defaults.
DEFAULT_CHECKPOINT = str(Path(__file__).resolve().parents[1] / 'checkpoints' / 'generalization_balanced_v24.pt')

LABELS = ["PAD", "TITLE", "BODY", "IMAGE", "CHART", "CAPTION", "FOOTER"]
LABEL_TO_ID = {name: i for i, name in enumerate(LABELS)}
ID_TO_LABEL = {i: name for i, name in enumerate(LABELS)}

@dataclass
class DemoConfig:
    """Model and data shape.

    The width/depth here is the main lever on *generalisation*, not capacity for
    its own sake. At 128 wide and 4 layers the model could hold the shapes it was
    templated on but not compose them: adding two templates cost other pages, and
    training a second (layout-completion) mode destroyed the first. Checkpoints
    store their own config, so an older one still loads at the size it was trained
    at.
    """

    num_bins: int = 64
    max_elements: int = 8
    timesteps: int = 20
    d_model: int = 256
    nhead: int = 8
    num_layers: int = 6
    dim_feedforward: int = 1024
    dropout: float = 0.05
