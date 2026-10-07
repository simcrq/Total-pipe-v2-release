"""
Font discovery and validation utilities.

Priority 2 implementation for automatic font path resolution.
"""

import platform
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import ImageFont


def discover_fonts() -> Dict[str, Dict[str, str]]:
    """
    Discover available fonts on the current platform.

    Returns:
        Dictionary mapping font family names to their file paths:
        {
            'Arial': {
                'regular': '/path/to/arial.ttf',
                'bold': '/path/to/arialbd.ttf',
                'italic': '/path/to/ariali.ttf'
            }
        }
    """
    os_name = platform.system()
    fonts = {}

    if os_name == 'Windows':
        fonts = _discover_windows_fonts()
    elif os_name == 'Darwin':  # macOS
        fonts = _discover_macos_fonts()
    else:  # Linux and others
        fonts = _discover_linux_fonts()

    return fonts


def _discover_windows_fonts() -> Dict[str, Dict[str, str]]:
    """Discover fonts on Windows."""
    fonts = {}
    font_dir = Path('C:/Windows/Fonts')

    if not font_dir.exists():
        return fonts

    # Common fonts with known naming patterns
    font_patterns = {
        'Arial': {'regular': 'arial.ttf', 'bold': 'arialbd.ttf', 'italic': 'ariali.ttf'},
        'Calibri': {'regular': 'calibri.ttf', 'bold': 'calibrib.ttf', 'italic': 'calibrii.ttf'},
        'Times New Roman': {'regular': 'times.ttf', 'bold': 'timesbd.ttf', 'italic': 'timesi.ttf'},
        'Georgia': {'regular': 'georgia.ttf', 'bold': 'georgiab.ttf', 'italic': 'georgiai.ttf'},
        'Verdana': {'regular': 'verdana.ttf', 'bold': 'verdanab.ttf', 'italic': 'verdanai.ttf'},
    }

    for family, variants in font_patterns.items():
        family_fonts = {}
        for variant, filename in variants.items():
            font_path = font_dir / filename
            if font_path.exists():
                family_fonts[variant] = str(font_path)

        if 'regular' in family_fonts:  # At least regular variant must exist
            fonts[family] = family_fonts

    return fonts


def _discover_macos_fonts() -> Dict[str, Dict[str, str]]:
    """Discover fonts on macOS."""
    fonts = {}
    font_dirs = [
        Path('/System/Library/Fonts'),
        Path('/System/Library/Fonts/Supplemental'),
        Path('/Library/Fonts'),
        Path.home() / 'Library/Fonts'
    ]

    font_patterns = {
        'Arial': {
            'regular': 'Arial.ttf',
            'bold': 'Arial Bold.ttf',
            'italic': 'Arial Italic.ttf'
        },
        'Helvetica': {
            'regular': 'Helvetica.ttc',
            'bold': 'Helvetica.ttc',  # TTC contains multiple weights
        },
        'Times New Roman': {
            'regular': 'Times New Roman.ttf',
            'bold': 'Times New Roman Bold.ttf',
        },
    }

    for family, variants in font_patterns.items():
        family_fonts = {}
        for variant, filename in variants.items():
            for font_dir in font_dirs:
                font_path = font_dir / filename
                if font_path.exists():
                    family_fonts[variant] = str(font_path)
                    break

        if 'regular' in family_fonts:
            fonts[family] = family_fonts

    return fonts


def _discover_linux_fonts() -> Dict[str, Dict[str, str]]:
    """Discover fonts on Linux."""
    fonts = {}
    font_dirs = [
        Path('/usr/share/fonts/truetype'),
        Path('/usr/share/fonts/TTF'),
        Path('/usr/local/share/fonts'),
        Path.home() / '.fonts',
        Path.home() / '.local/share/fonts'
    ]

    # Common font families on Linux
    font_searches = {
        'Liberation Sans': [
            'liberation/LiberationSans-Regular.ttf',
            'liberation/LiberationSans-Bold.ttf',
        ],
        'DejaVu Sans': [
            'dejavu/DejaVuSans.ttf',
            'dejavu/DejaVuSans-Bold.ttf',
        ],
        'Ubuntu': [
            'ubuntu/Ubuntu-R.ttf',
            'ubuntu/Ubuntu-B.ttf',
        ],
    }

    for family, search_paths in font_searches.items():
        family_fonts = {}
        variants = ['regular', 'bold']

        for i, search_path in enumerate(search_paths):
            for font_dir in font_dirs:
                font_path = font_dir / search_path
                if font_path.exists():
                    variant = variants[i] if i < len(variants) else 'regular'
                    family_fonts[variant] = str(font_path)
                    break

        if 'regular' in family_fonts:
            fonts[family] = family_fonts

    return fonts


def get_default_font() -> Tuple[str, str]:
    """
    Get the default font for the current platform.

    Returns:
        Tuple of (regular_font_path, bold_font_path)
    """
    fonts = discover_fonts()

    # Priority order for default font
    preferred_families = ['Arial', 'Calibri', 'Liberation Sans', 'DejaVu Sans', 'Helvetica']

    for family in preferred_families:
        if family in fonts:
            family_fonts = fonts[family]
            regular = family_fonts.get('regular')
            bold = family_fonts.get('bold', regular)  # Fallback to regular if no bold
            if regular:
                return regular, bold

    # If no preferred font found, return first available
    if fonts:
        family = next(iter(fonts))
        family_fonts = fonts[family]
        regular = family_fonts.get('regular')
        bold = family_fonts.get('bold', regular)
        return regular, bold

    # Last resort: return paths that will fail with helpful error
    return 'FONT_NOT_FOUND', 'FONT_NOT_FOUND'


def validate_font_path(font_path: str) -> str:
    """
    Validate a font path and return a helpful error message if invalid.

    Args:
        font_path: Path to font file

    Returns:
        Suggested fix message
    """
    path = Path(font_path)

    if not path.exists():
        os_name = platform.system()
        fonts = discover_fonts()

        if fonts:
            suggestions = []
            for family, variants in list(fonts.items())[:3]:  # Top 3 available
                regular = variants.get('regular')
                if regular:
                    suggestions.append(f"{family}: {regular}")

            return (
                f"Font not found: {font_path}\n"
                f"Available fonts on {os_name}:\n" +
                "\n".join(f"  - {s}" for s in suggestions) +
                "\n\nOr run: totalpipe discover-fonts"
            )
        else:
            return (
                f"Font not found: {font_path}\n"
                f"No fonts discovered on {os_name}.\n"
                f"Install common fonts or specify absolute path to existing font file."
            )

    # Path exists, try to load it
    try:
        ImageFont.truetype(str(path), 12)
        return "Font file exists and is valid"
    except Exception as e:
        return (
            f"Font file exists but cannot be loaded: {font_path}\n"
            f"Error: {e}\n"
            f"Ensure file is a valid TrueType or OpenType font."
        )


def resolve_font_for_platform(
    font_family: Optional[str] = None,
    font_path: Optional[str] = None
) -> Tuple[str, str]:
    """
    Resolve font paths for current platform.

    Args:
        font_family: Font family name (e.g., "Arial")
        font_path: Explicit font path (takes precedence)

    Returns:
        Tuple of (regular_font_path, bold_font_path)
    """
    # If explicit path provided and exists, use it
    if font_path:
        path = Path(font_path)
        if path.exists():
            # Try to find bold variant
            bold_path = path.parent / path.name.replace('.ttf', 'bd.ttf').replace('.TTF', 'BD.TTF')
            if not bold_path.exists():
                bold_path = path.parent / path.name.replace('.ttf', '-Bold.ttf')
            if not bold_path.exists():
                bold_path = path  # Fallback to regular

            return str(path), str(bold_path)

    # If font family specified, try to find it
    if font_family:
        fonts = discover_fonts()
        if font_family in fonts:
            family_fonts = fonts[font_family]
            regular = family_fonts.get('regular')
            bold = family_fonts.get('bold', regular)
            if regular:
                return regular, bold

    # Fall back to default
    return get_default_font()


def list_available_fonts() -> List[str]:
    """
    List all available font families on the current platform.

    Returns:
        List of font family names
    """
    fonts = discover_fonts()
    return sorted(fonts.keys())


def get_font_info(font_path: str) -> Dict[str, any]:
    """
    Get information about a font file.

    Args:
        font_path: Path to font file

    Returns:
        Dictionary with font information:
        {
            'exists': bool,
            'valid': bool,
            'path': str,
            'size': int,  # File size in bytes
            'error': str  # If invalid
        }
    """
    path = Path(font_path)

    info = {
        'exists': path.exists(),
        'path': str(path),
        'valid': False,
        'size': 0,
        'error': None
    }

    if not path.exists():
        info['error'] = 'File not found'
        return info

    info['size'] = path.stat().st_size

    try:
        font = ImageFont.truetype(str(path), 12)
        info['valid'] = True
        # Try to get font name
        try:
            info['family_name'] = font.getname()[0]
        except:
            pass
    except Exception as e:
        info['error'] = str(e)

    return info


# Quick access function for CLI
def main():
    """CLI entry point for font discovery."""
    import sys
    import json

    if len(sys.argv) > 1 and sys.argv[1] == '--json':
        fonts = discover_fonts()
        print(json.dumps(fonts, indent=2))
    else:
        fonts = discover_fonts()
        if fonts:
            print("Available fonts:")
            for family, variants in fonts.items():
                print(f"\n{family}:")
                for variant, path in variants.items():
                    print(f"  {variant}: {path}")
        else:
            print("No fonts discovered on this platform.")
            print("You may need to install common fonts or specify paths manually.")

        print(f"\nDefault font:")
        regular, bold = get_default_font()
        print(f"  Regular: {regular}")
        print(f"  Bold: {bold}")


if __name__ == '__main__':
    main()
