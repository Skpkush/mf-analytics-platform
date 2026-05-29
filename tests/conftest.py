"""
pytest configuration — adds scripts/transformation to sys.path so
test files can import data_quality, clean_nav, and clean_transactions
without installing them as packages.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "transformation"))
