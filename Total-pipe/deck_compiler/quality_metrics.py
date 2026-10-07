"""
Visual quality metrics and presentation analysis.

Priority 1 & 2 implementation: Comprehensive quality scoring for presentations.

This module analyzes generated presentations across multiple dimensions:
- Readability (font sizes, line density, contrast)
- Consistency (spacing, typography, color usage)
- Completeness (content coverage, evidence citations)
- Visual balance (whitespace, figure sizing, alignment)
- Accessibility (color contrast, minimum font sizes)
- Scientific rigor (figure quality, panel labels, citations)
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from PIL import Image, ImageFont, ImageDraw
import math


@dataclass
class QualityIssue:
    """A specific quality issue found in the presentation."""
    category: str  # readability, consistency, completeness, balance, accessibility, scientific
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    slide: Optional[int]
    shape: Optional[str]
    message: str
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    suggested_fix: Optional[str] = None


@dataclass
class QualityScore:
    """Score for a quality dimension."""
    category: str
    score: float  # 0-100
    weight: float  # Importance weight
    issues: List[QualityIssue] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityReport:
    """Complete quality analysis report."""
    overall_score: float  # 0-100 weighted average
    scores: Dict[str, QualityScore]  # category -> score
    slide_count: int
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    pass_threshold: float = 70.0  # Minimum score to pass

    def passes(self) -> bool:
        """Check if presentation meets quality threshold."""
        return self.overall_score >= self.pass_threshold and self.critical_issues == 0

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'overall_score': round(self.overall_score, 1),
            'passes': self.passes(),
            'scores': {
                cat: {
                    'score': round(score.score, 1),
                    'weight': score.weight,
                    'issue_count': len(score.issues),
                    'details': score.details
                }
                for cat, score in self.scores.items()
            },
            'slide_count': self.slide_count,
            'total_issues': self.total_issues,
            'critical_issues': self.critical_issues,
            'high_issues': self.high_issues,
            'medium_issues': self.medium_issues,
            'low_issues': self.low_issues,
            'pass_threshold': self.pass_threshold
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def to_summary(self) -> str:
        """Generate human-readable summary."""
        lines = []
        lines.append("=" * 60)
        lines.append("PRESENTATION QUALITY REPORT")
        lines.append("=" * 60)
        lines.append("")

        # Overall
        status = "[PASS]" if self.passes() else "[FAIL]"
        lines.append(f"Overall Score: {self.overall_score:.1f}/100 {status}")
        lines.append(f"Slides: {self.slide_count}")
        lines.append("")

        # Issue summary
        lines.append(f"Issues: {self.total_issues} total")
        if self.critical_issues > 0:
            lines.append(f"  [CRITICAL] {self.critical_issues}")
        if self.high_issues > 0:
            lines.append(f"  [HIGH] {self.high_issues}")
        if self.medium_issues > 0:
            lines.append(f"  [MEDIUM] {self.medium_issues}")
        if self.low_issues > 0:
            lines.append(f"  [LOW] {self.low_issues}")
        lines.append("")

        # Category scores
        lines.append("Category Scores:")
        for cat, score_obj in sorted(self.scores.items(), key=lambda x: x[1].score):
            icon = "[OK]" if score_obj.score >= 80 else "[WARN]" if score_obj.score >= 60 else "[FAIL]"
            lines.append(f"  {icon} {cat.title():15} {score_obj.score:5.1f}/100  ({len(score_obj.issues)} issues)")
        lines.append("")

        # Critical/High issues detail
        critical_and_high = []
        for score_obj in self.scores.values():
            critical_and_high.extend([i for i in score_obj.issues if i.severity in ['CRITICAL', 'HIGH']])

        if critical_and_high:
            lines.append("Critical & High Priority Issues:")
            for issue in critical_and_high[:10]:  # Top 10
                slide_info = f"Slide {issue.slide}" if issue.slide else "Overall"
                lines.append(f"  {issue.severity:8} [{slide_info}] {issue.message}")
                if issue.suggested_fix:
                    lines.append(f"           -> Fix: {issue.suggested_fix}")
            if len(critical_and_high) > 10:
                lines.append(f"  ... and {len(critical_and_high) - 10} more")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


def analyze_quality(build_dir: Path, detailed: bool = False) -> QualityReport:
    """
    Analyze presentation quality.

    Args:
        build_dir: Build directory containing qa_report.json, layout.json, etc.
        detailed: Include detailed per-slide analysis

    Returns:
        QualityReport with scores and issues
    """
    # Load build artifacts
    qa_path = build_dir / 'qa_report.json'
    layout_path = build_dir / 'layout.json'
    deck_ir_path = build_dir / 'deck_ir.json'

    if not qa_path.exists():
        raise FileNotFoundError(f"QA report not found: {qa_path}")

    qa_report = json.loads(qa_path.read_text(encoding='utf-8'))
    layout = json.loads(layout_path.read_text(encoding='utf-8')) if layout_path.exists() else None
    deck_ir = json.loads(deck_ir_path.read_text(encoding='utf-8')) if deck_ir_path.exists() else None

    # Analyze each dimension
    scores = {}

    scores['readability'] = analyze_readability(qa_report, layout, deck_ir, detailed)
    scores['consistency'] = analyze_consistency(qa_report, layout, deck_ir, detailed)
    scores['completeness'] = analyze_completeness(qa_report, layout, deck_ir, detailed)
    scores['balance'] = analyze_balance(qa_report, layout, deck_ir, detailed)
    scores['accessibility'] = analyze_accessibility(qa_report, layout, deck_ir, detailed)
    scores['scientific'] = analyze_scientific_rigor(qa_report, layout, deck_ir, detailed)

    # Calculate overall score (weighted average)
    total_weight = sum(s.weight for s in scores.values())
    overall_score = sum(s.score * s.weight for s in scores.values()) / total_weight if total_weight > 0 else 0

    # Count issues by severity
    all_issues = []
    for score in scores.values():
        all_issues.extend(score.issues)

    critical = sum(1 for i in all_issues if i.severity == 'CRITICAL')
    high = sum(1 for i in all_issues if i.severity == 'HIGH')
    medium = sum(1 for i in all_issues if i.severity == 'MEDIUM')
    low = sum(1 for i in all_issues if i.severity == 'LOW')

    slide_count = len(deck_ir.get('slides', [])) if deck_ir else 0

    return QualityReport(
        overall_score=overall_score,
        scores=scores,
        slide_count=slide_count,
        total_issues=len(all_issues),
        critical_issues=critical,
        high_issues=high,
        medium_issues=medium,
        low_issues=low
    )


def analyze_readability(qa_report: Dict, layout: Optional[Dict], deck_ir: Optional[Dict], detailed: bool) -> QualityScore:
    """Analyze readability: font sizes, line density, text length."""
    issues = []
    details = {}

    if not layout or not deck_ir:
        return QualityScore(category='readability', score=0, weight=0.25, issues=[], details={'error': 'Missing data'})

    # Extract font sizes across all slides
    font_sizes = []
    line_counts = []
    text_densities = []

    for slide_layout in layout.get('slides', []):
        for element in slide_layout.get('elements', []):
            if element.get('kind') == 'text':
                contract = element.get('contract', {})
                font_size = contract.get('font_size', 0)
                if font_size > 0:
                    font_sizes.append(font_size)

                # Check if text is too small
                if font_size < 18:
                    issues.append(QualityIssue(
                        category='readability',
                        severity='HIGH',
                        slide=slide_layout.get('slide_number'),
                        shape=element.get('name'),
                        message=f"Font size {font_size}pt is too small (minimum 18pt for body text)",
                        metric_value=font_size,
                        threshold=18.0,
                        suggested_fix="Increase font size or reduce content to fit larger text"
                    ))
                elif font_size < 20:
                    issues.append(QualityIssue(
                        category='readability',
                        severity='MEDIUM',
                        slide=slide_layout.get('slide_number'),
                        shape=element.get('name'),
                        message=f"Font size {font_size}pt is small (recommended 20pt+ for body text)",
                        metric_value=font_size,
                        threshold=20.0
                    ))

                # Check line count
                text = contract.get('text', '')
                lines = text.count('\n') + 1
                line_counts.append(lines)

                if lines > 10:
                    issues.append(QualityIssue(
                        category='readability',
                        severity='MEDIUM',
                        slide=slide_layout.get('slide_number'),
                        shape=element.get('name'),
                        message=f"{lines} lines of text exceeds recommended maximum (10 lines)",
                        metric_value=lines,
                        threshold=10,
                        suggested_fix="Split content across multiple slides"
                    ))

                # Check text density (chars per area)
                bbox = element.get('bbox', [0, 0, 0, 0])
                area = bbox[2] * bbox[3] if len(bbox) >= 4 else 1
                density = len(text) / area if area > 0 else 0
                text_densities.append(density)

                if density > 0.5:  # High density threshold
                    issues.append(QualityIssue(
                        category='readability',
                        severity='LOW',
                        slide=slide_layout.get('slide_number'),
                        shape=element.get('name'),
                        message=f"High text density (may appear cramped)",
                        metric_value=density,
                        threshold=0.5
                    ))

    # Calculate metrics
    details['min_font_size'] = min(font_sizes) if font_sizes else 0
    details['avg_font_size'] = sum(font_sizes) / len(font_sizes) if font_sizes else 0
    details['max_line_count'] = max(line_counts) if line_counts else 0
    details['avg_line_count'] = sum(line_counts) / len(line_counts) if line_counts else 0

    # Score based on issues and metrics
    score = 100
    score -= len([i for i in issues if i.severity == 'CRITICAL']) * 25
    score -= len([i for i in issues if i.severity == 'HIGH']) * 15
    score -= len([i for i in issues if i.severity == 'MEDIUM']) * 8
    score -= len([i for i in issues if i.severity == 'LOW']) * 3

    # Bonus for good average font size
    if details['avg_font_size'] >= 22:
        score += 10
    elif details['avg_font_size'] >= 20:
        score += 5

    score = max(0, min(100, score))

    return QualityScore(category='readability', score=score, weight=0.25, issues=issues, details=details)


def analyze_consistency(qa_report: Dict, layout: Optional[Dict], deck_ir: Optional[Dict], detailed: bool) -> QualityScore:
    """Analyze consistency: spacing, typography, color usage."""
    issues = []
    details = {}

    if not layout:
        return QualityScore(category='consistency', score=0, weight=0.20, issues=[], details={'error': 'Missing data'})

    # Collect spacing values
    vertical_gaps = []
    horizontal_gaps = []
    font_sizes_by_role = {}

    slides = layout.get('slides', [])
    for slide_layout in slides:
        elements = slide_layout.get('elements', [])

        # Calculate gaps between elements
        sorted_by_y = sorted([e for e in elements if e.get('bbox')], key=lambda e: e['bbox'][1])
        for i in range(len(sorted_by_y) - 1):
            e1, e2 = sorted_by_y[i], sorted_by_y[i + 1]
            b1, b2 = e1['bbox'], e2['bbox']
            gap = b2[1] - (b1[1] + b1[3])  # y2 - (y1 + h1)
            if gap > 0:
                vertical_gaps.append(gap)

        # Collect font sizes by role
        for element in elements:
            if element.get('kind') == 'text':
                role = element.get('role', 'unknown')
                font_size = element.get('contract', {}).get('font_size', 0)
                if font_size > 0:
                    if role not in font_sizes_by_role:
                        font_sizes_by_role[role] = []
                    font_sizes_by_role[role].append(font_size)

    # Check vertical spacing consistency
    if len(vertical_gaps) > 5:
        gap_std = math.sqrt(sum((g - sum(vertical_gaps) / len(vertical_gaps)) ** 2 for g in vertical_gaps) / len(vertical_gaps))
        details['vertical_gap_std'] = round(gap_std, 2)
        details['vertical_gap_avg'] = round(sum(vertical_gaps) / len(vertical_gaps), 2)

        if gap_std > 20:  # High variation
            issues.append(QualityIssue(
                category='consistency',
                severity='MEDIUM',
                slide=None,
                shape=None,
                message=f"Inconsistent vertical spacing (std dev: {gap_std:.1f}px)",
                metric_value=gap_std,
                threshold=20.0,
                suggested_fix="Use consistent spacing between elements (e.g., 24px)"
            ))

    # Check font size consistency per role
    for role, sizes in font_sizes_by_role.items():
        if len(set(sizes)) > 2:  # More than 2 different sizes for same role
            issues.append(QualityIssue(
                category='consistency',
                severity='MEDIUM',
                slide=None,
                shape=None,
                message=f"Inconsistent font sizes for {role}: {sorted(set(sizes))}pt",
                suggested_fix=f"Use consistent font size for all {role} elements"
            ))

    details['font_sizes_by_role'] = {
        role: {'min': min(sizes), 'max': max(sizes), 'unique': len(set(sizes))}
        for role, sizes in font_sizes_by_role.items()
    }

    # Score
    score = 100
    score -= len([i for i in issues if i.severity == 'CRITICAL']) * 25
    score -= len([i for i in issues if i.severity == 'HIGH']) * 15
    score -= len([i for i in issues if i.severity == 'MEDIUM']) * 8
    score -= len([i for i in issues if i.severity == 'LOW']) * 3
    score = max(0, min(100, score))

    return QualityScore(category='consistency', score=score, weight=0.20, issues=issues, details=details)


def analyze_completeness(qa_report: Dict, layout: Optional[Dict], deck_ir: Optional[Dict], detailed: bool) -> QualityScore:
    """Analyze completeness: content coverage, evidence citations."""
    issues = []
    details = {}

    if not deck_ir:
        return QualityScore(category='completeness', score=0, weight=0.15, issues=[], details={'error': 'Missing data'})

    slides = deck_ir.get('slides', [])
    total_evidence_refs = 0
    slides_with_evidence = 0
    slides_with_caveats = 0
    slides_with_speaker_notes = 0

    for i, slide in enumerate(slides, 1):
        semantic = slide.get('semantic', {})

        # Check evidence refs
        evidence_refs = semantic.get('evidence_refs', [])
        total_evidence_refs += len(evidence_refs)
        if evidence_refs:
            slides_with_evidence += 1
        else:
            issues.append(QualityIssue(
                category='completeness',
                severity='MEDIUM',
                slide=i,
                shape=None,
                message="No evidence citations on this slide",
                suggested_fix="Add evidence_refs to support claims"
            ))

        # Check for caveats
        caveats = semantic.get('caveats', [])
        if caveats:
            slides_with_caveats += 1

        # Check speaker notes
        notes = semantic.get('speaker_notes', '')
        if notes and len(notes) > 10:
            slides_with_speaker_notes += 1

        # Check for empty takeaways
        takeaway = semantic.get('takeaway', '')
        if not takeaway or len(takeaway) < 10:
            issues.append(QualityIssue(
                category='completeness',
                severity='HIGH',
                slide=i,
                shape=None,
                message="Missing or very short takeaway",
                suggested_fix="Add clear one-sentence takeaway for this slide"
            ))

    details['total_slides'] = len(slides)
    details['total_evidence_refs'] = total_evidence_refs
    details['slides_with_evidence'] = slides_with_evidence
    details['slides_with_caveats'] = slides_with_caveats
    details['slides_with_speaker_notes'] = slides_with_speaker_notes
    details['evidence_coverage'] = round(slides_with_evidence / len(slides) * 100, 1) if slides else 0

    # Score based on evidence coverage
    score = 100
    score -= len([i for i in issues if i.severity == 'CRITICAL']) * 25
    score -= len([i for i in issues if i.severity == 'HIGH']) * 15
    score -= len([i for i in issues if i.severity == 'MEDIUM']) * 8
    score -= len([i for i in issues if i.severity == 'LOW']) * 3

    # Bonus for good evidence coverage
    if details['evidence_coverage'] >= 80:
        score += 10
    elif details['evidence_coverage'] >= 60:
        score += 5

    score = max(0, min(100, score))

    return QualityScore(category='completeness', score=score, weight=0.15, issues=issues, details=details)


def analyze_balance(qa_report: Dict, layout: Optional[Dict], deck_ir: Optional[Dict], detailed: bool) -> QualityScore:
    """Analyze visual balance: whitespace, figure sizing, alignment."""
    issues = []
    details = {}

    if not layout:
        return QualityScore(category='balance', score=0, weight=0.15, issues=[], details={'error': 'Missing data'})

    # Analyze whitespace and coverage per slide
    slide_coverages = []

    for slide_layout in layout.get('slides', []):
        slide_num = slide_layout.get('slide_number')
        elements = slide_layout.get('elements', [])

        # Calculate total area covered by elements
        total_area = 0
        slide_width = 960  # Standard width
        slide_height = 720  # Standard height

        for element in elements:
            bbox = element.get('bbox', [0, 0, 0, 0])
            if len(bbox) >= 4:
                area = bbox[2] * bbox[3]
                total_area += area

        coverage = total_area / (slide_width * slide_height) if (slide_width * slide_height) > 0 else 0
        slide_coverages.append(coverage)

        # Check if too dense
        if coverage > 0.8:
            issues.append(QualityIssue(
                category='balance',
                severity='MEDIUM',
                slide=slide_num,
                shape=None,
                message=f"Slide is very dense ({coverage * 100:.0f}% coverage)",
                metric_value=coverage,
                threshold=0.8,
                suggested_fix="Reduce content or increase slide size"
            ))

        # Check if too sparse
        elif coverage < 0.3:
            issues.append(QualityIssue(
                category='balance',
                severity='LOW',
                slide=slide_num,
                shape=None,
                message=f"Slide appears sparse ({coverage * 100:.0f}% coverage)",
                metric_value=coverage,
                threshold=0.3
            ))

    details['avg_coverage'] = round(sum(slide_coverages) / len(slide_coverages) * 100, 1) if slide_coverages else 0
    details['min_coverage'] = round(min(slide_coverages) * 100, 1) if slide_coverages else 0
    details['max_coverage'] = round(max(slide_coverages) * 100, 1) if slide_coverages else 0

    # Score
    score = 100
    score -= len([i for i in issues if i.severity == 'CRITICAL']) * 25
    score -= len([i for i in issues if i.severity == 'HIGH']) * 15
    score -= len([i for i in issues if i.severity == 'MEDIUM']) * 8
    score -= len([i for i in issues if i.severity == 'LOW']) * 3

    # Bonus for good average coverage (40-70% is ideal)
    avg_cov = details['avg_coverage'] / 100
    if 0.4 <= avg_cov <= 0.7:
        score += 10
    elif 0.3 <= avg_cov <= 0.8:
        score += 5

    score = max(0, min(100, score))

    return QualityScore(category='balance', score=score, weight=0.15, issues=issues, details=details)


def analyze_accessibility(qa_report: Dict, layout: Optional[Dict], deck_ir: Optional[Dict], detailed: bool) -> QualityScore:
    """Analyze accessibility: color contrast, minimum font sizes."""
    issues = []
    details = {}

    if not deck_ir:
        return QualityScore(category='accessibility', score=0, weight=0.10, issues=[], details={'error': 'Missing data'})

    # Check color contrast
    theme = deck_ir.get('theme', {})
    foreground = theme.get('foreground', '#000000')
    background = theme.get('background', '#FFFFFF')

    contrast_ratio = calculate_contrast_ratio(foreground, background)
    details['contrast_ratio'] = round(contrast_ratio, 2)

    # WCAG AA requires 4.5:1 for normal text, 3:1 for large text (18pt+)
    if contrast_ratio < 4.5:
        issues.append(QualityIssue(
            category='accessibility',
            severity='HIGH',
            slide=None,
            shape=None,
            message=f"Insufficient color contrast: {contrast_ratio:.1f}:1 (WCAG AA requires 4.5:1)",
            metric_value=contrast_ratio,
            threshold=4.5,
            suggested_fix="Increase contrast between foreground and background colors"
        ))
    elif contrast_ratio < 7.0:
        # AAA standard is 7:1
        issues.append(QualityIssue(
            category='accessibility',
            severity='LOW',
            slide=None,
            shape=None,
            message=f"Color contrast {contrast_ratio:.1f}:1 meets AA but not AAA standard (7:1)",
            metric_value=contrast_ratio,
            threshold=7.0
        ))

    # Check minimum font sizes (already checked in readability, just count here)
    if layout:
        small_fonts = 0
        for slide_layout in layout.get('slides', []):
            for element in slide_layout.get('elements', []):
                if element.get('kind') == 'text':
                    font_size = element.get('contract', {}).get('font_size', 0)
                    if font_size < 18:
                        small_fonts += 1

        details['text_elements_below_18pt'] = small_fonts

        if small_fonts > 0:
            issues.append(QualityIssue(
                category='accessibility',
                severity='HIGH',
                slide=None,
                shape=None,
                message=f"{small_fonts} text elements below 18pt (accessibility minimum)",
                suggested_fix="Increase font sizes to at least 18pt for accessibility"
            ))

    # Score
    score = 100
    score -= len([i for i in issues if i.severity == 'CRITICAL']) * 25
    score -= len([i for i in issues if i.severity == 'HIGH']) * 15
    score -= len([i for i in issues if i.severity == 'MEDIUM']) * 8
    score -= len([i for i in issues if i.severity == 'LOW']) * 3

    # Bonus for good contrast
    if contrast_ratio >= 7.0:
        score += 10
    elif contrast_ratio >= 4.5:
        score += 5

    score = max(0, min(100, score))

    return QualityScore(category='accessibility', score=score, weight=0.10, issues=issues, details=details)


def analyze_scientific_rigor(qa_report: Dict, layout: Optional[Dict], deck_ir: Optional[Dict], detailed: bool) -> QualityScore:
    """Analyze scientific rigor: figure quality, panel labels, citations."""
    issues = []
    details = {}

    if not deck_ir:
        return QualityScore(category='scientific', score=0, weight=0.15, issues=[], details={'error': 'Missing data'})

    # Check figure quality from QA report
    qa_items = qa_report.get('items', [])

    scientific_fails = [i for i in qa_items if i.get('rule') in [
        'SCIENTIFIC_PANEL_REVIEW',
        'FIGURE_CAPTION_MISMATCH',
        'FIGURE_SOURCE_MISMATCH',
        'FIGURE_TOO_SMALL'
    ]]

    for item in scientific_fails:
        severity_map = {
            'FAIL': 'CRITICAL',
            'WARNING': 'HIGH',
            'REVIEW': 'MEDIUM',
            'INFO': 'LOW'
        }
        severity = severity_map.get(item.get('severity', 'INFO'), 'LOW')

        issues.append(QualityIssue(
            category='scientific',
            severity=severity,
            slide=item.get('slide'),
            shape=item.get('shape'),
            message=item.get('message', ''),
            suggested_fix="Verify scientific figure quality and panel labels in PowerPoint"
        ))

    details['scientific_review_items'] = len(scientific_fails)

    # Check figure-caption consistency
    slides = deck_ir.get('slides', [])
    figure_count = 0
    caption_count = 0

    for slide in slides:
        figure_refs = slide.get('composition', {}).get('figure_refs', [])
        figure_count += len(figure_refs)

        for fig_ref in figure_refs:
            if fig_ref.get('caption'):
                caption_count += 1
            else:
                issues.append(QualityIssue(
                    category='scientific',
                    severity='MEDIUM',
                    slide=slide.get('id'),
                    shape=fig_ref.get('asset_id'),
                    message="Figure missing caption",
                    suggested_fix="Add descriptive caption with figure reference (e.g., Fig.1a)"
                ))

    details['figure_count'] = figure_count
    details['figures_with_captions'] = caption_count
    details['caption_coverage'] = round(caption_count / figure_count * 100, 1) if figure_count > 0 else 100

    # Score
    score = 100
    score -= len([i for i in issues if i.severity == 'CRITICAL']) * 25
    score -= len([i for i in issues if i.severity == 'HIGH']) * 15
    score -= len([i for i in issues if i.severity == 'MEDIUM']) * 8
    score -= len([i for i in issues if i.severity == 'LOW']) * 3

    # Bonus for complete captions
    if details['caption_coverage'] >= 90:
        score += 10
    elif details['caption_coverage'] >= 70:
        score += 5

    score = max(0, min(100, score))

    return QualityScore(category='scientific', score=score, weight=0.15, issues=issues, details=details)


def calculate_contrast_ratio(color1: str, color2: str) -> float:
    """
    Calculate WCAG contrast ratio between two colors.

    Args:
        color1: Hex color (e.g., "#142735")
        color2: Hex color (e.g., "#FFFFFF")

    Returns:
        Contrast ratio (e.g., 4.5)
    """
    def hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def relative_luminance(rgb):
        """Calculate relative luminance per WCAG formula."""
        r, g, b = [c / 255.0 for c in rgb]
        r = r / 12.92 if r <= 0.03928 else ((r + 0.055) / 1.055) ** 2.4
        g = g / 12.92 if g <= 0.03928 else ((g + 0.055) / 1.055) ** 2.4
        b = b / 12.92 if b <= 0.03928 else ((b + 0.055) / 1.055) ** 2.4
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    rgb1 = hex_to_rgb(color1)
    rgb2 = hex_to_rgb(color2)

    l1 = relative_luminance(rgb1)
    l2 = relative_luminance(rgb2)

    lighter = max(l1, l2)
    darker = min(l1, l2)

    return (lighter + 0.05) / (darker + 0.05)
