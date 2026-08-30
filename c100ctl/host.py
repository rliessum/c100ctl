"""Runtime host checks.

Returned as bool (not Literal) so type checkers do not fold `sys.platform`
and mark the other OS's branches unreachable.
"""

from __future__ import annotations

import sys


def is_macos() -> bool:
    return sys.platform == "darwin"
