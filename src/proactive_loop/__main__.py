"""``python -m proactive_loop`` entry point — identical to the ``pla`` console script."""
from __future__ import annotations

from .cli import main

raise SystemExit(main())
