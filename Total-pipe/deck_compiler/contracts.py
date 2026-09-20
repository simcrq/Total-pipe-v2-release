"""Versioned public contracts. All geometry and text sizes use CSS px (96 dpi)."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class TextBoxContract:
    font_family: str
    font_size: float
    font_file: str
    font_weight: int = 400
    line_height: float = 1.25
    wrap: bool = False  # compiler inserts measured explicit line breaks
    autofit: str = "none"
    inset: dict = field(default_factory=lambda: dict(left=0, right=0, top=0, bottom=0))
    vertical_anchor: str = "top"
    max_lines: int = 8
    overflow_policy: str = "wrap_shrink_variant_split"
    font_floor: float = 24

    def __post_init__(self):
        if not self.font_family or not self.font_file:
            raise ValueError("TextBoxContract requires an explicit font family and file")
        if not all(math.isfinite(x) and x > 0 for x in
                   (self.font_size, self.font_floor, self.line_height)):
            raise ValueError("Invalid font metrics")
        if self.font_size < self.font_floor or self.max_lines < 1:
            raise ValueError("Invalid font floor / max lines")
        if self.autofit != "none" or self.wrap:
            raise ValueError("v2 emits premeasured explicit lines with autofit=none")
        if self.vertical_anchor not in ("top", "middle", "bottom"):
            raise ValueError("Invalid vertical anchor")
        if set(self.inset) != {"left", "right", "top", "bottom"} or any(
                not math.isfinite(v) or v < 0 for v in self.inset.values()):
            raise ValueError("Invalid insets")

    def to_dict(self):
        return asdict(self)


SEVERITIES = ("FAIL", "WARNING", "REVIEW", "INFO")


def issue(rule, severity, message, slide=None, shape=None, detector="semantic-preflight",
          confidence="HIGH", **source):
    if severity not in SEVERITIES:
        raise ValueError(severity)
    origin = {"detector": detector, **source}
    identity = digest([rule, slide, shape, origin, message])[:16]
    return {"id": identity, "rule": rule, "severity": severity, "slide": slide,
            "shape": shape, "message": message, "source": origin,
            "confidence": confidence, "diagnosis": diagnose(detector, confidence, source)}


def diagnose(detector, confidence, source):
    if detector in ("semantic-preflight",):
        return "content_capacity" if confidence == "HIGH" else "scientific_review"
    if confidence != "HIGH":
        return "infra_or_measurement_review"
    if source.get("renderer") in ("libreoffice", "keynote"):
        return "compatibility"
    if detector == "native-visual":
        return "design" if source.get("renderer") == "powerpoint" else "backend"
    return "layout_or_contract"


def report(items, artifact_sha256=None, ir_sha256=None, checks=None):
    counts = {s: sum(i["severity"] == s for i in items) for s in SEVERITIES}
    return {"schema_version": "2.0", "artifact_sha256": artifact_sha256,
            "ir_sha256": ir_sha256, "status": "FAIL" if counts["FAIL"] else
            "REVIEW" if counts["REVIEW"] else "PASS", "counts": counts,
            "checks": checks or {}, "items": items}
