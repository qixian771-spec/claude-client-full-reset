#!/usr/bin/env python3
"""Native read-only smoke checks for CI runners. Never writes outside a temp dir.

Exercises platform code against the real OS (registry, environment, folders)
instead of fixtures. Any exception fails the run; findings counts are printed
but not judged, because runner images may contain arbitrary software.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import common  # noqa: E402
import verify_reset  # noqa: E402


def paths():
    platform = common.require_supported()
    core = platform.core()
    print(f'[paths] platform={platform.label}; backup candidates={len(core)}; '
          f'existing={sum(common.exists(path) for path, _ in core)}')
    for name, root in platform.browsers():
        print(f'[paths] browser {name}: root exists={common.exists(root)}')
    findings = verify_reset.collect(no_browser=True)
    print('[paths] read-only findings: ' + ', '.join(f'{k}={len(v)}' for k, v in findings.items()))


STAGES = {'paths': paths}


def main():
    common.utf8_stdio()
    selected = sys.argv[1:] or list(STAGES)
    unknown = [name for name in selected if name not in STAGES]
    if unknown:
        raise SystemExit(f'unknown stage: {unknown}')
    for name in selected:
        STAGES[name]()
    print('SMOKE PASS: ' + ', '.join(selected))


if __name__ == '__main__':
    main()
