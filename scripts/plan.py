#!/usr/bin/env python3
"""shotlist.json + measured seconds/frame -> shards.json (the matrix the render job runs).

shard size = budget minutes * 60 / measured seconds per frame, cut on shot boundaries where it can
be, inside a shot where it cannot. A shard never spans two .blend files.
"""
import argparse
import json
import math


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shotlist', default='shotlist.json')
    ap.add_argument('--bench', default='bench.txt')
    ap.add_argument('--budget-min', type=float, default=20.0)
    ap.add_argument('--out', default='shards.json')
    args = ap.parse_args()

    spf = None
    for line in open(args.bench, encoding='utf-8'):
        if line.startswith('SPF='):
            spf = float(line.strip().split('=')[1])
    if not spf:
        raise SystemExit('no SPF= line in bench output')

    per_shard = max(10, int(args.budget_min * 60 / spf))
    shots = json.load(open(args.shotlist, encoding='utf-8'))['shots']

    shards, idx = [], 0
    for shot in shots:
        start, end = shot['start'], shot['end']
        while start <= end:
            stop = min(end, start + per_shard - 1)
            shards.append({'name': f's{idx:02d}', 'blend': shot['blend'],
                           'shot': shot['id'], 'start': start, 'end': stop,
                           'frames': stop - start + 1,
                           'est_min': round((stop - start + 1) * spf / 60, 1)})
            idx += 1
            start = stop + 1

    json.dump(shards, open(args.out, 'w', encoding='utf-8'), indent=2)
    print(f'measured {spf:.2f}s/frame -> {per_shard} frames per shard -> {len(shards)} shards')
    total = 0
    for s in shards:
        total += s['est_min']
        print(f"  {s['name']}  {s['shot']:14s} {s['start']:5d}..{s['end']:5d}  "
              f"{s['frames']:4d}f  ~{s['est_min']:.1f} min")
    print(f'total estimated CPU: {total:.0f} min across {len(shards)} jobs '
          f'(wall clock ~{max(s["est_min"] for s in shards):.0f} min if all run in parallel)')


if __name__ == '__main__':
    main()
