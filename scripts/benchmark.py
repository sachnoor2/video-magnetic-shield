#!/usr/bin/env python3
"""Benchmark: render N frames of one scene at final settings, report the median seconds/frame.

The number this prints is the only thing allowed to size the shards.
"""
import argparse
import os
import statistics
import sys
import time

import bpy


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', required=True)
    ap.add_argument('--frames', type=int, default=12)
    args = ap.parse_args(argv)

    scene = args.scene
    if not os.path.exists(scene):
        import glob
        found = sorted(glob.glob(os.path.join(os.path.dirname(scene) or '.', '*.blend')))
        if not found:
            raise SystemExit(f'no .blend files next to {scene}')
        scene = found[len(found) // 2]
        print(f'  {args.scene} missing, benchmarking {scene} instead')
    bpy.ops.wm.open_mainfile(filepath=scene)
    sc = bpy.context.scene
    span = sc.frame_end - sc.frame_start
    n = max(2, args.frames)
    picks = [sc.frame_start + int(span * i / (n - 1)) for i in range(n)]

    times = []
    for f in picks:
        sc.frame_set(f)
        sc.render.filepath = f'/tmp/bench/frame_{f:06d}.png'
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        times.append(time.time() - t0)
        print(f'  frame {f}: {times[-1]:.2f}s')

    med = statistics.median(times)
    print(f'SPF={med:.3f}')
    print(f'MEDIAN_SPF={med:.3f}  (n={len(times)}, min={min(times):.2f}, max={max(times):.2f})')


main()
