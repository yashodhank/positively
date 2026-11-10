"""Positively: automated positive-framing enforcement for prose and comments.

Detects and reverses negative compliance/escalation/blocker language into positive
framing, and flags code that blocks a feature, research, or delivery path.

CLI entry points:
  positively check [paths...]     scan for violations
  positively apply [paths...]     auto-rewrite framing
"""

__version__ = "0.4.0"

from . import engine, patterns, config  # noqa: F401
