"""Report prerequisites and separate candidate capability from native final readiness."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from . import ROOT, COMPONENT
from .adapters import redact


def probe(argv, cwd=ROOT, timeout=20):
    try:
        result = subprocess.run([str(a) for a in argv], cwd=cwd, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=timeout,
                                env={**os.environ, 'OFFICECLI_NO_AUTO_RESIDENT': '1'})
        return result.returncode == 0, redact(result.stdout.strip() or result.stderr.strip())
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)


def doctor(deep=False, source_kind=None):
    checks = []
    def add(key, ok, detail, remedy, optional=False, skipped=False):
        checks.append({'id': key, 'status': 'SKIP' if skipped else 'PASS' if ok else 'WARNING' if optional else 'FAIL',
                       'detail': detail, 'remedy': '' if ok else remedy})
        return bool(ok)
    py = add('python.version', sys.version_info >= (3, 12), sys.version.split()[0], 'Use Python 3.12 or newer.')
    ok, detail = probe([sys.executable, '-c', 'import deck_compiler; from PIL import Image; import lxml, pdfplumber'], COMPONENT)
    compiler = add('python.import.deck_compiler', ok, detail or str(COMPONENT), 'Install Total-pipe requirements with this Python and use the Total-pipe cwd.')
    ok, detail = probe(['node', '--version'])
    match = re.search(r'v?(\d+)\.', detail)
    node = add('node.version', ok and bool(match) and int(match.group(1)) >= 22, detail, 'Install Node.js >=22 and add it to PATH.')
    ok, detail = probe(['node', ROOT/'research-ppt-assistant/server/cli.mjs', '--help'])
    rpa = add('node.rpa_cli', ok, detail[:120], 'Restore the RPA CLI and use a supported Node.js runtime.')
    office = shutil.which('officecli')
    present = add('officecli.present', bool(office), office or 'Not found', 'Install OfficeCLI >=1.0.152 and add it to PATH.')
    ok, detail = probe([office or 'officecli', '--version'])
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', detail)
    version = add('officecli.version', ok and bool(match) and tuple(map(int, match.groups())) >= (1, 0, 152), detail,
                  'Install OfficeCLI >=1.0.152.')
    runtime = True
    if deep and present and version:
        with tempfile.TemporaryDirectory(prefix='totalpipe-doctor-') as temporary:
            path = Path(temporary)/'probe.pptx'
            runtime, detail = probe([office, 'create', path, '--json'])
            if runtime:
                runtime, detail = probe([office, 'close', path, '--json'])
            runtime = runtime and path.is_file() and path.stat().st_size > 0
            if runtime:
                runtime, detail = probe([office, 'validate', path, '--json'])
                try:
                    from deck_compiler.officecli import schema_error_count
                    runtime = runtime and schema_error_count(json.loads(detail)) == 0
                    with zipfile.ZipFile(path) as package:
                        runtime = runtime and 'ppt/presentation.xml' in package.namelist()
                except (ValueError, zipfile.BadZipFile):
                    runtime = False
            add('officecli.runtime', runtime, detail, 'Inspect OfficeCLI permissions and its runtime installation.')
    else:
        add('officecli.runtime', False, 'Run doctor --deep to write and close a temporary PPTX.', 'Run deep diagnostics.', optional=True, skipped=True)
    mineru = shutil.which('mineru-open-api')
    auth = bool(mineru and os.environ.get('MINERU_TOKEN'))
    add('mineru.auth', auth, 'CLI and token configured; cloud credentials are not verified.' if auth else
        'OCR authentication not verified; cached CLI login may be available.' if mineru else 'MinerU CLI not found.',
        'Install and authenticate the official mineru-open-api CLI; keep credentials outside job files.', optional=source_kind != 'pdf')
    ok, detail = probe([sys.executable, COMPONENT/'agent/bridges/paperworkflow_bridge.py', '--op', 'version'])
    try:
        bridge = ok and json.loads(detail)['ok']
    except (ValueError, KeyError):
        bridge = False
    add('paperworkflow.bridge', bridge, detail[:200], 'Restore PaperWorkflow beside Total-pipe and install its dependencies.')
    try:
        from deck_compiler.fonts import resolve_theme_fonts, missing_glyphs
        font, _, _ = resolve_theme_fonts({'font_family': 'Noto Sans CJK SC', 'font_file': 'NotoSansCJK-Regular.ttc'}, ROOT, '中文科研')
        cjk = not missing_glyphs(font, '中文科研')
        detail = str(font)
    except (OSError, ValueError, ImportError) as error:
        cjk, detail = False, str(error)
    add('fonts.cjk', cjk, detail, 'Install compiler dependencies and a Chinese font, or set TOTALPIPE_FONT_DIR.', optional=True)
    pdf = importlib.util.find_spec('pdfplumber') is not None
    add('pdfplumber', pdf, 'Available' if pdf else 'Not installed', 'Install pdfplumber>=0.11.', optional=True)
    powerpoint = (sys.platform == 'darwin' and any(p.is_dir() for p in
        [Path('/Applications/Microsoft PowerPoint.app'), Path.home()/'Applications/Microsoft PowerPoint.app']))
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'PowerPoint.Application\CLSID'):
                powerpoint = True
        except OSError:
            pass
    add('powerpoint.native', powerpoint, 'Application detected; UI/export acceptance still required.' if powerpoint else
        'Native PowerPoint not detected.', 'Use Windows/macOS with Microsoft PowerPoint for formal final validation.', optional=True)
    needs = {'build'} if source_kind == 'deck_ir' else {'evidence', 'rpa', 'build'}
    capabilities = {'can_evidence_markdown': py and bridge, 'can_evidence_pdf': py and bridge and auth,
        'can_rpa': py and node and rpa, 'can_build_editable': py and compiler and present and version and runtime,
        'can_native_final': py and compiler and powerpoint and pdf,
        'runtime_verified': bool(deep and present and version and runtime),
        'authentication_verified': False,
        'blocked_stages': [name for name, ready in [('evidence', py and bridge and (source_kind != 'pdf' or auth)),
                           ('rpa', py and node and rpa), ('build', py and compiler and present and version and runtime)] if name in needs and not ready]}
    return {'status': 'FAIL' if any(c['status'] == 'FAIL' for c in checks) else 'WARNING' if any(c['status'] == 'WARNING' for c in checks) else 'PASS',
            'checks': checks, **capabilities}
