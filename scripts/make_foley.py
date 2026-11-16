#!/usr/bin/env python3
"""Foley: one whoosh per cut, one low impact for the twist. Synthesised, not sampled."""
import os
import shutil
import subprocess
import sys

OUT = 'public/audio/foley'


def ffmpeg():
    exe = shutil.which('ffmpeg')
    if not exe:
        sys.exit('ffmpeg not found')
    return exe


def run(args):
    proc = subprocess.run(args, capture_output=True)
    if proc.returncode != 0:
        sys.exit(proc.stderr.decode('utf-8', 'ignore')[:400])


def main():
    os.makedirs(OUT, exist_ok=True)
    f = ffmpeg()

    # whoosh: pink noise, band-swept, fast in, slower out
    run([f, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
         '-i', 'anoisesrc=c=pink:r=22050:d=0.42:a=0.9',
         '-af', ('highpass=f=400,lowpass=f=5200,'
                 'afade=t=in:st=0:d=0.10,afade=t=out:st=0.16:d=0.26,'
                 'volume=-19dB'),
         '-ar', '22050', '-ac', '1', f'{OUT}/whoosh.wav'])

    # impact: low sine drop with a short noise transient
    run([f, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
         '-i', "aevalsrc='0.85*sin(2*PI*(72-34*t)*t)*exp(-3.2*t)':s=22050:d=1.1",
         '-af', 'lowpass=f=320,volume=-11dB',
         '-ar', '22050', '-ac', '1', f'{OUT}/impact.wav'])

    for name in ('whoosh.wav', 'impact.wav'):
        path = os.path.join(OUT, name)
        print(f'{path}  {os.path.getsize(path)} bytes')


if __name__ == '__main__':
    main()
