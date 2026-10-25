"""
Font discovery and validation utilities.

Font paths in a Deck IR are a portability hazard: a deck authored on macOS names
``/System/Library/Fonts/Supplemental/Arial.ttf``, a deck authored on Windows names
``C:\\Windows\\Fonts\\arial.ttf``, and neither exists on the other machine. The theme keeps those
fields for compatibility, but the compiler resolves them through :func:`resolve_theme_fonts`, which
tries, in order: the path as given (absolute, or relative to the deck), the file name inside every
known font directory, the declared family, and finally any discovered sans-serif face. A substitution
is reported as a REVIEW issue instead of failing the build, because a deck is still deliverable in a
substituted metric-compatible face while a hard failure means nothing renders at all.

Both absolute-path sources are also honoured through ``TOTALPIPE_FONT_DIR`` (one or more directories,
separated by ``os.pathsep``), so a machine can point the pipeline at a font folder without editing any
deck.
"""

import os
import platform
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import ImageFont

FONT_DIRECTORY_VARIABLE = 'TOTALPIPE_FONT_DIR'
# Faces tried last, in order, when neither the declared file nor the declared family resolves.
# The list prefers a face that covers Latin and CJK, because these decks mix both.
FALLBACK_FAMILIES = ('Microsoft YaHei', 'Noto Sans CJK SC', 'Heiti TC', 'Arial Unicode MS', 'Arial', 'Liberation Sans',
                     'DejaVu Sans', 'Helvetica')


def font_search_dirs() -> List[Path]:
    """Every directory a bare font file name is looked up in, most specific first."""
    directories = []
    configured = os.environ.get(FONT_DIRECTORY_VARIABLE, '')
    for entry in configured.split(os.pathsep):
        if entry.strip():
            directories.append(Path(entry).expanduser())
    system = platform.system()
    if system == 'Windows':
        windir = Path(os.environ.get('WINDIR', 'C:/Windows'))
        directories += [windir/'Fonts', Path.home()/'AppData/Local/Microsoft/Windows/Fonts']
    elif system == 'Darwin':
        directories += [Path('/System/Library/Fonts'), Path('/System/Library/Fonts/Supplemental'),
                        Path('/Library/Fonts'), Path.home()/'Library/Fonts']
    else:
        directories += [Path('/usr/share/fonts'), Path('/usr/local/share/fonts'),
                        Path.home()/'.fonts', Path.home()/'.local/share/fonts']
    unique = []
    for directory in directories:
        if directory not in unique and directory.is_dir():
            unique.append(directory)
            if system not in ('Windows', 'Darwin'):
                # Linux distributions install families below truetype/ and opentype/,
                # including Noto CJK collections that are absent from the old flat scan.
                unique.extend(child for child in sorted(directory.rglob('*'))
                              if child.is_dir() and child not in unique)
    return unique


def _loadable(path: Path) -> bool:
    try:
        ImageFont.truetype(str(path), 12)
        return True
    except (OSError, ValueError):
        return False


def find_font_file(value, base_dir=None) -> Optional[str]:
    """Resolve one theme font value to an existing, loadable file, or None.

    Absolute paths are used as-is; relative ones are tried against the deck directory and then
    against every font directory by file name, which is what makes a deck authored on another
    machine compile here.
    """
    if not value:
        return None
    path = Path(value).expanduser()
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        if base_dir is not None:
            candidates.append(Path(base_dir)/path)
        candidates.append(path)
        candidates += [directory/path.name for directory in font_search_dirs()]
    for candidate in candidates:
        if candidate.is_file() and _loadable(candidate):
            return str(candidate.resolve())
    return None


def load_font_file(value, size):
    """Load a measured request font, resolving a portable filename if its old path moved."""
    try:
        return ImageFont.truetype(value, size)
    except OSError:
        resolved = find_font_file(Path(value).name)
        if resolved is None:
            raise
        return ImageFont.truetype(resolved, size)


def missing_glyphs(font_path, text) -> set:
    """Characters in ``text`` that the face cannot draw.

    Comparing a character's mask with the mask of a code point no font defines is the same heuristic
    the compiler already uses; it is conservative (a font may draw a notdef box the same way) but it
    catches the real case here: Latin-only Arial asked to set Chinese headings.
    """
    try:
        face = ImageFont.truetype(str(font_path), 24)
    except (OSError, ValueError):
        return set(text)
    reference = None
    missing = set()
    for character in sorted(set(text)):
        if character.isspace():
            continue
        try:
            mask = bytes(face.getmask(character))
        except Exception:
            missing.add(character)
            continue
        if reference is None:
            try:
                reference = bytes(face.getmask('\U0010FFFF'))
            except Exception:
                reference = b''
        if reference and mask == reference:
            missing.add(character)
    return missing


# PowerPoint's list styles are (glyph, face) pairs: round, square and open-square markers live in
# ordinary text faces, while diamond, check and arrow come from a symbol face. Deck defaults may
# be overridden by individual prose blocks and the single takeaway marker.
BULLET_STYLES = {
    'bullet': '\u2022',       # •
    'square': '\u25aa',       # ▪
    'open_square': '\u25a1',  # □
    'diamond': '\u25c6',      # ◆
    'arrow': '\u2192',        # →
    'check': '\u2713',        # ✓
    'dash': '\u2013',         # –
    'large_square': '\u25a0', # ■ (Unicode fallback for a full native square)
    'large_diamond': '\u25c6',# ◆ (Unicode fallback for a full native diamond)
    'arrowhead': '\u27a2',    # ➢
}
NATIVE_BULLET_FACES = {
    'large_square': ('Wingdings', 'Wingdings.ttf', '\uf06e'),
    'large_diamond': ('Wingdings', 'Wingdings.ttf', '\uf075'),
    'arrowhead': ('Wingdings', 'Wingdings.ttf', '\uf0d8'),
}
# (family, candidate file names) for the faces PowerPoint itself uses for these markers.
BULLET_SYMBOL_FACES = (
    ('Segoe UI Symbol', ('seguisym.ttf',)),
    ('Arial Unicode MS', ('arialuni.ttf', 'Arial Unicode MS.ttf')),
    ('DejaVu Sans', ('DejaVuSans.ttf', 'dejavu/DejaVuSans.ttf')),
    ('Apple Symbols', ('Apple Symbols.ttf',)),
    ('Cambria Math', ('cambria.ttc', 'Cambria Math.ttf')),
)


def resolve_bullet(style, family, font_file):
    """Return ``(glyph, face)`` for a bullet style, choosing a face that can actually draw it.

    The declared text face wins when it covers the glyph; otherwise a symbol face is searched for,
    and if none is installed the marker degrades to the round bullet every text face has. ``face``
    is what the writer puts in ``a:buFont``, so the stored style survives on another machine as
    long as either face is installed.
    """
    if style in NATIVE_BULLET_FACES:
        face, name, glyph = NATIVE_BULLET_FACES[style]
        path = find_font_file(name)
        if path:
            try:
                symbol = ImageFont.truetype(path, 24, encoding='symb')
                if bytes(symbol.getmask(glyph)) != bytes(symbol.getmask(chr(0x10FFFF))):
                    return glyph, face
            except (OSError, ValueError):
                pass
    glyph = BULLET_STYLES.get(style) or BULLET_STYLES['square']
    if font_file and glyph not in missing_glyphs(font_file, glyph):
        return glyph, family
    for face, names in BULLET_SYMBOL_FACES:
        for name in names:
            path = find_font_file(name)
            if path and glyph not in missing_glyphs(path, glyph):
                return glyph, face
    return BULLET_STYLES['bullet'], family


def bullet_metrics(style, family, font_file, size):
    """Measure the chosen native glyph at the prose size, without bullet-size scaling."""
    glyph, face = resolve_bullet(style, family, font_file)
    path = font_file
    encoding = ''
    if face == 'Wingdings' and style in NATIVE_BULLET_FACES:
        path = find_font_file(NATIVE_BULLET_FACES[style][1])
        encoding = 'symb'
    elif face != family:
        for candidate_face, names in BULLET_SYMBOL_FACES:
            if candidate_face != face:
                continue
            for name in names:
                candidate = find_font_file(name)
                if candidate and glyph not in missing_glyphs(candidate, glyph):
                    path = candidate
                    break
            else:
                continue
            break
    font = ImageFont.truetype(path, int(size), encoding=encoding)
    left, top, right, bottom = font.getbbox(glyph, anchor='ls')
    return {'style': style, 'char': glyph, 'face': face, 'size_from_text': True,
            'native_font_fallback': style in NATIVE_BULLET_FACES and face != NATIVE_BULLET_FACES[style][0],
            'gutter': round(max(42., right-left+12.), 2),
            'ascent': max(0, -top)+2, 'descent': max(0, bottom)+2,
            'line_height_px': max(size*1.25, bottom-top+4)}


def coverage_is_fatal(missing, text_sample):
    """Whether a face's gaps justify replacing the whole deck's typeface.

    Three exotic glyphs (``10⁻⁶``, ``cm⁻²``, ``WSe₂``) used to flip an entire Chinese deck from a
    sans face to SimSun, because any gap at all triggered substitution. A gap is fatal only when it
    is a script mismatch: the face cannot draw a large share of the text, or it misses many distinct
    characters. Otherwise the declared face stays and the few gaps are reported once, which is what
    PowerPoint does anyway with per-character fallback.
    """
    if not missing:
        return False
    visible = [character for character in text_sample if not character.isspace()]
    if not visible:
        return False
    cjk = sum(1 for character in visible if '\u3400' <= character <= '\u9fff')
    cjk_missing = sum(1 for character in missing if '\u3400' <= character <= '\u9fff')
    if cjk >= len(visible) * .2 and cjk_missing:
        return True
    return len(missing) > 8 or len(missing) >= len(visible) * .02


def resolve_theme_fonts(theme, base_dir=None, text_sample=''):
    """Resolve the two theme fonts. Returns ``(regular, bold, notes)``; notes drive REVIEW issues."""
    notes = []
    regular = find_font_file(theme.get('font_file'), base_dir)
    bold = find_font_file(theme.get('bold_font_file'), base_dir)
    discovered = discover_fonts()
    # Coverage outranks the declared face only when the gap is a script mismatch; a handful of
    # symbols stay with the declared face and are reported once (see coverage_is_fatal).
    declared_gap = missing_glyphs(regular, text_sample) if (regular and text_sample) else set(text_sample)
    if text_sample and (regular is None or coverage_is_fatal(declared_gap, text_sample)):
        declared = theme.get('font_family')
        preference = [declared] + [n for n in FALLBACK_FAMILIES if n != declared] + list(discovered)
        best = None
        for rank, name in enumerate(dict.fromkeys(preference)):
            candidate = discovered.get(name)
            if not candidate or not candidate.get('regular'):
                continue
            missing = missing_glyphs(candidate['regular'], text_sample)
            score = (len(missing), rank)
            if best is None or score < best[0]:
                best = (score, name, candidate, missing)
        if best is not None:
            _, name, candidate, missing = best
            declared_missing = missing_glyphs(regular, text_sample) if regular else set(text_sample)
            if len(missing) < len(declared_missing):
                notes.append({'rule': 'FONT_SUBSTITUTED', 'severity': 'REVIEW',
                              'message': f"theme font {Path(regular).name if regular else theme.get('font_file')!r} "
                                         f"cannot draw {len(declared_missing)} character(s) of this deck; "
                                         f"used {name} instead ({len(missing)} still unsupported)",
                              'detail': {'reason': 'glyph_coverage',
                                         'declared': theme.get('font_file'),
                                         'used_regular': candidate['regular'],
                                         'used_bold': candidate.get('bold', candidate['regular']),
                                         'family': name,
                                         'unsupported_characters': ''.join(sorted(missing))[:40],
                                         'declared_unsupported_sample': ''.join(sorted(declared_missing))[:40]}})
                return candidate['regular'], candidate.get('bold', candidate['regular']), notes
    if regular and declared_gap:
        # Keep the declared face and say which characters PowerPoint will have to borrow.
        notes.append({'rule': 'FONT_GLYPH_FALLBACK', 'severity': 'REVIEW',
                      'message': f"theme font {Path(regular).name} cannot draw "
                                 f"{len(declared_gap)} character(s) ({''.join(sorted(declared_gap))[:20]}); "
                                 "kept it and left those glyphs to PowerPoint's fallback",
                      'detail': {'reason': 'partial_coverage', 'declared': theme.get('font_file'),
                                 'family': theme.get('font_family'),
                                 'unsupported_characters': ''.join(sorted(declared_gap))[:40]}})
    if regular and bold:
        return regular, bold, notes
    family = theme.get('font_family') or ''
    chosen = None
    if family in discovered:
        chosen = discovered[family]
    else:
        for name in FALLBACK_FAMILIES:
            if name in discovered:
                chosen = discovered[name]
                break
        if chosen is None and discovered:
            chosen = discovered[next(iter(discovered))]
    if chosen is None:
        missing = theme.get('font_file') if not regular else theme.get('bold_font_file')
        raise FileNotFoundError(
            f'font {missing!r} was not found and no font is installed. '
            f'Install a TrueType font or set {FONT_DIRECTORY_VARIABLE} to a directory of fonts.')
    substitution = {'missing_regular': theme.get('font_file') if not regular else None,
                    'missing_bold': theme.get('bold_font_file') if not bold else None,
                    'used_regular': chosen.get('regular'),
                    'used_bold': chosen.get('bold', chosen.get('regular')),
                    'declared_family': family,
                    'search_directories': [str(directory) for directory in font_search_dirs()]}
    notes.append({'rule': 'FONT_SUBSTITUTED', 'severity': 'REVIEW',
                  'message': f"theme font {substitution['missing_regular'] or substitution['missing_bold']!r} "
                             f"is not installed; used {Path(substitution['used_regular']).name} instead",
                  'detail': substitution})
    return (regular or chosen.get('regular'), bold or chosen.get('bold', chosen.get('regular')), notes)


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


FONT_FILES = {
    'Heiti TC': {'regular': ('STHeiti Light.ttc',), 'bold': ('STHeiti Medium.ttc',)},
    'Arial Unicode MS': {'regular': ('Arial Unicode.ttf',)},
    'Arial': {'regular': ('arial.ttf',), 'bold': ('arialbd.ttf',), 'italic': ('ariali.ttf',)},
    'Calibri': {'regular': ('calibri.ttf',), 'bold': ('calibrib.ttf',)},
    'Times New Roman': {'regular': ('times.ttf', 'Times New Roman.ttf'),
                        'bold': ('timesbd.ttf', 'Times New Roman Bold.ttf')},
    'Georgia': {'regular': ('georgia.ttf',), 'bold': ('georgiab.ttf',)},
    'Verdana': {'regular': ('verdana.ttf',), 'bold': ('verdanab.ttf',)},
    'Microsoft YaHei': {'regular': ('msyh.ttc', 'msyh.ttf'), 'bold': ('msyhbd.ttc', 'msyhbd.ttf')},
    'SimSun': {'regular': ('simsun.ttc',), 'bold': ('simsunb.ttf',)},
    'SimHei': {'regular': ('simhei.ttf',)},
    'Noto Sans CJK SC': {'regular': ('NotoSansCJK-Regular.ttc', 'NotoSansSC-Regular.otf'),
                         'bold': ('NotoSansCJK-Bold.ttc', 'NotoSansSC-Bold.otf')},
    'Liberation Sans': {'regular': ('LiberationSans-Regular.ttf', 'liberation/LiberationSans-Regular.ttf'),
                        'bold': ('LiberationSans-Bold.ttf', 'liberation/LiberationSans-Bold.ttf')},
    'DejaVu Sans': {'regular': ('DejaVuSans.ttf', 'dejavu/DejaVuSans.ttf'),
                    'bold': ('DejaVuSans-Bold.ttf', 'dejavu/DejaVuSans-Bold.ttf')},
    'Helvetica': {'regular': ('Helvetica.ttc',)},
}


def _discover_platform_fonts() -> Dict[str, Dict[str, str]]:
    """Map known family names to installed files, searching every font directory."""
    directories = font_search_dirs()
    fonts = {}
    for family, variants in FONT_FILES.items():
        family_fonts = {}
        for variant, names in variants.items():
            for name in names:
                found = None
                for directory in directories:
                    candidate = directory/name
                    if candidate.is_file():
                        found = str(candidate)
                        break
                if found:
                    family_fonts[variant] = found
                    break
        if 'regular' in family_fonts:
            fonts[family] = family_fonts
    return fonts


def _discover_windows_fonts() -> Dict[str, Dict[str, str]]:
    return _discover_platform_fonts()


def _discover_macos_fonts() -> Dict[str, Dict[str, str]]:
    """Discover fonts on macOS."""
    fonts = _discover_platform_fonts()
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
    fonts = _discover_platform_fonts()
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
        if family in fonts:
            continue
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
