#!/usr/bin/env python3
"""Report an optional caller deadline without changing or enforcing it."""
import argparse
import json
import math
import os
import time


def status(environment, now, reserve=None):
    raw = environment.get('LEAN_RUN_DEADLINE_UNIX')
    if raw is None:
        return {'mode': 'UNBOUNDED'}
    deadline = float(raw)
    duration = float(environment.get('LEAN_RUN_PHASE_SECONDS', '600'))
    if not math.isfinite(deadline) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Deadline must be finite and phase duration positive')
    reserve = min(180, max(30, duration / 4)) if reserve is None else reserve
    if not math.isfinite(reserve) or reserve <= 0:
        raise ValueError('Reserve must be positive and finite')
    remaining = max(0, math.floor(deadline - now))
    mode = 'DEADLINE' if remaining == 0 else 'VERIFY' if remaining <= reserve else 'WORK'
    return {'mode': mode, 'remaining_seconds': remaining, 'reserve_seconds': reserve}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reserve', type=float, help='Seconds reserved for verification and reporting')
    args = parser.parse_args()
    try:
        result = status(os.environ, time.time(), args.reserve)
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
