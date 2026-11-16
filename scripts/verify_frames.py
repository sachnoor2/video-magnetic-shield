#!/usr/bin/env python3
"""Fail loudly on any gap in the frame sequence, before the encoder ever sees it."""
import argparse
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shotlist', default='shotlist.json')
    ap.add_argument('--dir', default='public/out')
    args = ap.parse_args()

    total = json.load(open(args.shotlist, encoding='utf-8'))['totalFrames']
    missing, found = [], 0
    for i in range(total):
        if os.path.exists(os.path.join(args.dir, f'frame_{i:06d}.png')):
            found += 1
        else:
            missing.append(i)

    extra = [f for f in os.listdir(args.dir)
             if f.startswith('frame_') and int(f[6:12]) >= total]
    print(f'expected {total} frames, found {found}, missing {len(missing)}, extra {len(extra)}')
    if missing:
        # report as ranges, not a wall of numbers
        ranges, run = [], [missing[0]]
        for m in missing[1:]:
            if m == run[-1] + 1:
                run.append(m)
            else:
                ranges.append((run[0], run[-1]))
                run = [m]
        ranges.append((run[0], run[-1]))
        print('MISSING RANGES: ' + ', '.join(f'{a}-{b}' for a, b in ranges))
        sys.exit(1)
    print('frame sequence complete and contiguous')


if __name__ == '__main__':
    main()
