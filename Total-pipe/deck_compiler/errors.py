"""
Structured error types with recovery guidance.

Priority 1 implementation for better error handling and AI usability.
"""

from typing import Optional


class RecoverableError(Exception):
    """Base class for errors that can be fixed and retried."""

    def __init__(
        self,
        message: str,
        suggested_fix: str,
        can_retry: bool = True,
        context: Optional[dict] = None
    ):
        super().__init__(message)
        self.message = message
        self.suggested_fix = suggested_fix
        self.can_retry = can_retry
        self.context = context or {}

    def to_dict(self):
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'suggested_fix': self.suggested_fix,
            'can_retry': self.can_retry,
            'context': self.context
        }


class AssetError(RecoverableError):
    """Asset file not found or invalid."""

    def __init__(
        self,
        asset_id: str,
        expected_path: str,
        deck_ir_location: Optional[str] = None
    ):
        suggestion = (
            f"Fix asset path for '{asset_id}':\n"
            f"1. Place file at: {expected_path}\n"
            f"2. Or update deck_ir.json to use absolute path\n"
            f"3. Ensure image is valid JPG/PNG format"
        )
        if deck_ir_location:
            suggestion += f"\n4. Location in deck_ir.json: {deck_ir_location}"

        super().__init__(
            message=f"Asset '{asset_id}' not found at: {expected_path}",
            suggested_fix=suggestion,
            can_retry=True,
            context={
                'asset_id': asset_id,
                'expected_path': expected_path,
                'deck_ir_location': deck_ir_location
            }
        )


class FontError(RecoverableError):
    """Font file not found or invalid."""

    def __init__(
        self,
        font_path: str,
        platform_suggestions: Optional[list] = None
    ):
        import platform
        os_name = platform.system()

        if platform_suggestions is None:
            platform_suggestions = []
            if os_name == 'Windows':
                platform_suggestions = [
                    'C:/Windows/Fonts/arial.ttf',
                    'C:/Windows/Fonts/calibri.ttf'
                ]
            elif os_name == 'Darwin':  # macOS
                platform_suggestions = [
                    '/System/Library/Fonts/Supplemental/Arial.ttf',
                    '/System/Library/Fonts/Helvetica.ttc'
                ]
            else:  # Linux
                platform_suggestions = [
                    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
                ]

        suggestion = (
            f"Font not found: {font_path}\n"
            f"Platform: {os_name}\n"
            f"Suggested fonts for your system:\n"
        )
        for font in platform_suggestions:
            suggestion += f"  - {font}\n"
        suggestion += "Or use 'totalpipe discover-fonts' to list available fonts"

        super().__init__(
            message=f"Font file unavailable: {font_path}",
            suggested_fix=suggestion,
            can_retry=True,
            context={
                'font_path': font_path,
                'platform': os_name,
                'suggestions': platform_suggestions
            }
        )


class CapacityError(RecoverableError):
    """Content exceeds layout capacity."""

    def __init__(
        self,
        slide_id: str,
        block_id: Optional[str],
        content_length: int,
        max_capacity: int,
        overflow_ratio: float
    ):
        suggestion = (
            f"Content too large for slide '{slide_id}'"
            f"{f' block {block_id}' if block_id else ''}:\n"
            f"Content: {content_length} chars, Capacity: {max_capacity} chars\n"
            f"Overflow: {overflow_ratio:.1%}\n\n"
            f"Solutions:\n"
            f"1. Enable overflow repair (automatically splits to continuation slides)\n"
            f"2. Reduce content density (remove non-essential details)\n"
            f"3. Split into multiple slides at Story/RPA stage\n"
            f"4. Use 'spacious' frame variant for more space"
        )

        super().__init__(
            message=f"SPLIT_REQUIRED: Content exceeds capacity by {overflow_ratio:.1%}",
            suggested_fix=suggestion,
            can_retry=True,
            context={
                'slide_id': slide_id,
                'block_id': block_id,
                'content_length': content_length,
                'max_capacity': max_capacity,
                'overflow_ratio': overflow_ratio
            }
        )


class StoryValidationError(RecoverableError):
    """Story validation failed."""

    def __init__(
        self,
        error_type: str,
        details: str,
        evidence_id: Optional[str] = None
    ):
        if error_type == 'unknown_evidence':
            suggestion = (
                f"Evidence ID '{evidence_id}' not found in workflow:\n"
                f"1. Check workflow.json evidence registry\n"
                f"2. Regenerate Story with correct evidence IDs\n"
                f"3. Ensure PaperWorkflow completed successfully"
            )
        elif error_type == 'missing_provenance':
            suggestion = (
                f"Story missing required provenance:\n"
                f"1. Story must be generated by subagent\n"
                f"2. Model must be user-selected (not default)\n"
                f"3. Reasoning effort must be 'high' or higher\n"
                f"4. Set 'selected_by_user': true in planner metadata"
            )
        else:
            suggestion = f"Fix Story validation error and regenerate: {details}"

        super().__init__(
            message=f"Story validation failed: {error_type}",
            suggested_fix=suggestion,
            can_retry=True,
            context={
                'error_type': error_type,
                'details': details,
                'evidence_id': evidence_id
            }
        )


class RPAValidationError(RecoverableError):
    """RPA validation failed."""

    def __init__(
        self,
        error_type: str,
        slide_num: Optional[int],
        details: str
    ):
        if error_type == 'KEY_POINTS_LOST':
            suggestion = (
                f"Key points missing in slide {slide_num}:\n"
                f"1. Compare deck_plan.json with normalized_content.json\n"
                f"2. Restore missing key_points from original Brief\n"
                f"3. Do NOT use compressed slot text from compact output\n"
                f"4. Rerun validate-deck with original content model"
            )
        elif error_type == 'SOURCE_TEXT_NOT_BOUND':
            suggestion = (
                f"Original text not fully bound in slide {slide_num}:\n"
                f"1. Body or key_points truncated in slot binding\n"
                f"2. This is a hard error - content cannot be silently cut\n"
                f"3. Revise RPA plan to fit content or add more slides\n"
                f"4. Do NOT change content to fit layout"
            )
        elif error_type == 'VISUAL_INTENT_NOT_BOUND':
            suggestion = (
                f"Visual intent group not fully bound in slide {slide_num}:\n"
                f"1. Design intent requires all 4 key_points in slots\n"
                f"2. Cannot auto-split hard process group\n"
                f"3. Return to Story/RPA to replan with more capacity\n"
                f"4. Or remove design intent for this slide"
            )
        else:
            suggestion = f"Fix RPA validation error and replan: {details}"

        super().__init__(
            message=f"RPA validation failed: {error_type}",
            suggested_fix=suggestion,
            can_retry=True,
            context={
                'error_type': error_type,
                'slide_num': slide_num,
                'details': details
            }
        )


class LayoutProviderError(RecoverableError):
    """Layout provider (v26) failed."""

    def __init__(
        self,
        provider_name: str,
        error_message: str
    ):
        suggestion = (
            f"Layout provider '{provider_name}' failed:\n"
            f"Error: {error_message}\n\n"
            f"Solutions:\n"
            f"1. Use deterministic compiler: --layout-provider deterministic\n"
            f"2. Check model checkpoint exists and is valid\n"
            f"3. Verify PyTorch installation: python -c 'import torch'\n"
            f"4. Check models/totalpipe_content_v26.pt SHA-256 hash"
        )

        super().__init__(
            message=f"Layout provider failed: {error_message}",
            suggested_fix=suggestion,
            can_retry=True,
            context={
                'provider': provider_name,
                'error': error_message
            }
        )


class OfficeCliError(RecoverableError):
    """OfficeCLI execution failed."""

    def __init__(
        self,
        command: str,
        exit_code: int,
        error_output: str
    ):
        suggestion = (
            f"OfficeCLI command failed:\n"
            f"Command: {command}\n"
            f"Exit code: {exit_code}\n\n"
            f"Solutions:\n"
            f"1. Verify OfficeCLI installed: officecli --version\n"
            f"2. Check version >= 1.0.152\n"
            f"3. Ensure file paths are absolute\n"
            f"4. Review error output for specific issues"
        )

        super().__init__(
            message=f"OfficeCLI failed with exit code {exit_code}",
            suggested_fix=suggestion,
            can_retry=False,
            context={
                'command': command,
                'exit_code': exit_code,
                'error_output': error_output
            }
        )


class ValidationError(RecoverableError):
    """General validation error."""

    def __init__(
        self,
        validation_type: str,
        message: str,
        suggested_fix: str,
        can_retry: bool = True
    ):
        super().__init__(
            message=f"{validation_type}: {message}",
            suggested_fix=suggested_fix,
            can_retry=can_retry,
            context={'validation_type': validation_type}
        )
