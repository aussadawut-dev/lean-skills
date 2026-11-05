#!/usr/bin/env python3
"""Run an existing check, retaining its full log with a bounded JSON excerpt."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def stop(process):
    """Stop the check; POSIX also terminates its isolated process group."""
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        if os.name != 'posix':
            process.kill()
    finally:
        if os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()


def excerpt(path, limit, success):
    size = path.stat().st_size
    with path.open('rb') as stream:
        if success:
            stream.seek(max(0, size - limit * 4))
            value = '\n'.join(stream.read().decode('utf-8', 'replace').splitlines()[-8:])
            return value[-limit:], size > len(value.encode('utf-8'))
        if size <= limit:
            return stream.read().decode('utf-8', 'replace')[:limit], False
        marker = '\n[... full output retained in log ...]\n'
        room = max(0, limit - len(marker))
        head_size = room // 3
        head = stream.read(head_size).decode('utf-8', 'replace')
        stream.seek(max(0, size - (room - head_size)))
        tail = stream.read().decode('utf-8', 'replace')
        return (head + marker + tail)[:limit], True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, help='New log path; existing files are never overwritten')
    parser.add_argument('--timeout', type=float, help='Optional seconds; no timeout by default')
    parser.add_argument('--max-chars', type=int, default=2400, help='Excerpt character limit (default: 2400)')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or args.max_chars < 80 or (args.timeout is not None and args.timeout <= 0):
        parser.error('Provide a command, max-chars >= 80, and a positive timeout if specified')
    try:
        if args.log:
            path = args.log.resolve()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        else:
            fd, name = tempfile.mkstemp(prefix='lean-check-', suffix='.log')
            path = Path(name)
    except OSError as error:
        parser.error(str(error))
    started = time.monotonic()
    timed_out = False
    process = None
    launch_error = None
    interrupted = None

    def on_signal(number, _frame):
        nonlocal interrupted
        if interrupted is None:
            interrupted = number

    signals = [signal.SIGINT, signal.SIGTERM]
    if os.name == 'posix':
        signals.append(signal.SIGHUP)
    previous_handlers = {number: signal.signal(number, on_signal) for number in signals}
    with os.fdopen(fd, 'wb') as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=os.name == 'posix')
            deadline = None if args.timeout is None else time.monotonic() + args.timeout
            while True:
                if interrupted is not None:
                    stop(process)
                    code = 128 + interrupted
                    break
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    timed_out = True
                    stop(process)
                    code = 124
                    break
                try:
                    code = process.wait(timeout=min(0.1, remaining) if remaining is not None else 0.1)
                    if interrupted is not None:
                        stop(process)
                        code = 128 + interrupted
                    break
                except subprocess.TimeoutExpired:
                    continue
        except KeyboardInterrupt:
            if process is not None:
                stop(process)
            code = 130
        except OSError as error:
            launch_error = str(error)
            code = 127
        finally:
            for number, handler in previous_handlers.items():
                signal.signal(number, handler)
    if code < 0:
        code = 128 - code
    preview, truncated = excerpt(path, args.max_chars, code == 0)
    result = {'exit_code': code, 'timed_out': timed_out,
              'elapsed_seconds': round(time.monotonic() - started, 3),
              'log': str(path), 'log_bytes': path.stat().st_size,
              'excerpt_truncated': truncated, 'output_excerpt': preview}
    if launch_error:
        result['launch_error'] = launch_error
    if interrupted is not None:
        result['interrupted_signal'] = interrupted
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
