#!/usr/bin/env python3
"""manifest.json (measured narration) -> shotlist.json (absolute frame ranges, one entry per CUT).

Shot lengths are never typed by hand: they are whatever the TTS step measured. Each narration beat
is split into 2-3 Blender cuts so the film cuts every ~3-4 seconds, and every cut gets its own
caption so no caption ever straddles a cut.
"""
import argparse
import json

# per beat: the camera move of each cut, and the motion sources it carries
META = {
    '01-hook': dict(camera=['dolly down the storm', 'low angle, Earth hit', 'lateral side view'],
                    motion=['storm particles', 'sun flicker', 'parallax'],
                    device='scale dive'),
    '02-setup': dict(camera=['push-in on the naked planet', 'close on the limb glow'],
                     motion=['earth rotation', 'atmosphere pulse'],
                     device='x-ray'),
    '03-value': dict(camera=['26 degree orbit', 'close on the iron core', 'top-down through the shell'],
                     motion=['core spin', 'swirl', 'sparks orbit', 'light breathe'],
                     device='x-ray / cross-section'),
    '04-proof': dict(camera=['push-in on the dial'],
                     motion=['needle swing', 'field-line pulse'],
                     device='force visualisation'),
    '05-escalation': dict(camera=['wide side view', 'close on the day-side compression'],
                          motion=['particle storm', 'field compression', 'field pulse'],
                          device='force visualisation'),
    '06-twist': dict(camera=['rise over the horizon', 'looking up at the curtain', 'particles falling'],
                     motion=['aurora sway', 'aurora flicker', 'falling particles'],
                     device='force visualisation'),
    '07-resolution': dict(camera=['pull back', 'final hero push'],
                          motion=['field rotation', 'particle flow', 'earth'],
                          device='wide reveal'),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', default='src/manifest.json')
    ap.add_argument('--narration', default='narration.json')
    ap.add_argument('--out', default='shotlist.json')
    ap.add_argument('--width', type=int, default=720)
    ap.add_argument('--height', type=int, default=1280)
    args = ap.parse_args()

    man = json.load(open(args.manifest, encoding='utf-8'))
    try:                       # captions live in the script, not in the TTS manifest
        script = {s['id']: s for s in json.load(open(args.narration, encoding='utf-8'))['scenes']}
    except Exception:
        script = {}
    fps = man['fps']
    cuts, cursor = [], 0

    for scene in man['scenes']:
        sid = scene['id']
        n = int(scene['frames'])
        captions = (script.get(sid, {}).get('captions')
                    or scene.get('captions') or [scene.get('caption', '')])
        meta = META.get(sid, {})
        k = len(captions)

        # split the beat evenly, giving the remainder to the first cuts
        base, rem = divmod(n, k)
        for i in range(k):
            length = base + (1 if i < rem else 0)
            start = cursor
            cuts.append({
                'id': f'{sid}-{i + 1}',
                'beat': sid,
                'variant': i,
                'start': start,
                'end': start + length - 1,
                'frames': length,
                'blend': f'scenes/{sid}-{i + 1}.blend',
                'camera': (meta.get('camera') or ['push-in'])[i % len(meta.get('camera') or ['push-in'])],
                'motion': meta.get('motion', []),
                'device': meta.get('device', ''),
                'caption': captions[i],
                'samples': 48,
            })
            cursor += length

    out = {'fps': fps, 'width': args.width, 'height': args.height,
           'totalFrames': cursor, 'shots': cuts}
    json.dump(out, open(args.out, 'w', encoding='utf-8'), indent=2)

    secs = cursor / fps
    print(f'{len(cuts)} cuts, {cursor} frames = {secs:.2f}s')
    print(f'cut density: {len(cuts) / (secs / 60):.1f} shots/min  (target 15-22)')
    for s in cuts:
        print(f"  {s['id']:16s} {s['start']:5d}..{s['end']:5d}  {s['frames']:4d}f  "
              f"{s['frames'] / fps:5.2f}s  {s['camera']:34s} | {s['caption']}")


if __name__ == '__main__':
    main()
