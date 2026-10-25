"""Thin, resumable access to the existing Total-pipe components."""
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1]
ROOT = COMPONENT.parent
VERSION = '1.0.1'
