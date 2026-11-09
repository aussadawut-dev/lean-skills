#!/usr/bin/env python3
"""Show a numbered, bounded region of a text file. Request regions, not whole files."""
import argparse
import hashlib
import re
from pathlib import Path


def parse_lines(value):
    match = re.fullmatch(r'(\d+)(?:-(\d*))?', value)
    if not match or int(match.group(1)) < 1 or (match.group(2) and int(match.group(2)) < int(match.group(1))):
        raise argparse.ArgumentTypeError('use START, START- or START-END with 1-based line numbers')
    return int(match.group(1)), int(match.group(2)) if match.group(2) else None


def render(path, data, start, end, max_chars):
    """Header, numbered lines within the character budget, and what remains."""
    lines = data.decode('utf-8', 'replace').splitlines()
    total = len(lines)
    out = [f'{path}: {total} lines, sha256 {hashlib.sha256(data).hexdigest()[:12]}']
    if start > total:
        out.append(f'[no lines at {start}-; the file ends at line {total}]')
        return '\n'.join(out) + '\n'
    last = total if end is None else min(end, total)
    width = len(str(last))
    used = 0
    shown = start - 1
    for number in range(start, last + 1):
        text = f'{number:>{width}}| {lines[number - 1]}\n'
        if used + len(text) > max_chars and number > start:
            break
        out.append(text[:-1] if len(text) <= max_chars else text[:max_chars - 1])
        used += len(text)
        shown = number
    if shown == total:
        tail = 'end of file'
    elif shown < last:
        tail = f'next: --lines {shown + 1}-{"" if end is None else last}'
    else:
        tail = f'continues at line {shown + 1}'
    out.append(f'[lines {start}-{shown} of {total}; {tail}]')
    return '\n'.join(out) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--lines', type=parse_lines, default=(1, None), help='START, START- or START-END (default: from line 1)')
    parser.add_argument('--max-chars', type=int, default=6000, help='Output budget for the numbered lines (default: 6000)')
    args = parser.parse_args()
    if args.max_chars < 200:
        parser.error('max-chars must be at least 200')
    try:
        data = args.path.read_bytes()
    except OSError as error:
        parser.error(str(error))
    print(render(args.path, data, *args.lines, args.max_chars), end='')


if __name__ == '__main__':
    main()
