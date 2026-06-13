"""agent-friendly-md shared internal modules.

Single source of truth for the pieces every tool and validator must agree on:

- ``paths``     job-bundle directory layout (PLAN §4)
- ``jobstate``  the phase enum, STATE.json shape and helpers (PLAN §5/§6)
- ``gates``     the gate output protocol — exit codes, gate result files (PLAN §12)
- ``manifest``  the output manifest draft/final shape (PLAN §4/§10)

tools/ and validators/ import from here so the contract is defined once. The
project root is put on ``sys.path`` by ``scripts/run_python.py``; each tool also
self-bootstraps its path so it runs whether invoked through the wrapper or
directly.
"""

from . import subproc as _subproc

# Importing lib is the single chokepoint every tool and validator passes through
# (they all ``from lib import ...``). Forcing UTF-8 stdio here makes the DIRECT
# invocation path (``python3 tools/x.py``) survive a non-UTF-8 console too — the
# wrapper-only guard in scripts/run_python.py does not cover it. Idempotent.
_subproc.force_utf8_stdio()

__all__ = ["paths", "jobstate", "gates", "manifest", "subproc"]
