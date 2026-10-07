#!/usr/bin/env python3
"""
Totalpipe - Unified CLI wrapper for Total-pipe v3.

This script provides a single entry point for the entire pipeline.
"""

import sys
from pathlib import Path

# Add deck_compiler to path
sys.path.insert(0, str(Path(__file__).parent / 'deck_compiler'))

from deck_compiler.unified_cli import main

if __name__ == '__main__':
    sys.exit(main())
