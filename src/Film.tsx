import React from 'react';
import {AbsoluteFill, Audio, Img, Sequence, staticFile, useCurrentFrame} from 'remotion';
import shotlist from '../shotlist.json';

type Shot = {
  id: string;
  beat: string;
  start: number;
  end: number;
  frames: number;
  caption: string;
};

const SHOTS = shotlist.shots as unknown as Shot[];

/** One narration track per BEAT, spanning all of that beat's cuts. */
const BEATS = SHOTS.reduce<{beat: string; start: number; frames: number}[]>((acc, shot) => {
  const last = acc[acc.length - 1];
  if (last && last.beat === shot.beat) {
    last.frames = shot.end - last.start + 1;
  } else {
    acc.push({beat: shot.beat, start: shot.start, frames: shot.frames});
  }
  return acc;
}, []);

/** Frame-exact read of the Blender PNG sequence by ABSOLUTE index. */
const FrameSeq: React.FC<{start: number}> = ({start}) => {
  const frame = useCurrentFrame();
  const abs = start + frame;
  return (
    <AbsoluteFill>
      <Img src={staticFile(`out/frame_${String(abs).padStart(6, '0')}.png`)} />
    </AbsoluteFill>
  );
};

/** 1-3 word chunks, timed proportionally to character count, inside one scene only. */
const chunkCaption = (text: string, dur: number) => {
  const words = (text || '').trim().split(/\s+/).filter(Boolean);
  const groups: string[] = [];
  for (let i = 0; i < words.length; i += 2) {
    groups.push(words.slice(i, i + 2).join(' '));
  }
  const total = groups.reduce((a, g) => a + g.length, 0) || 1;
  let acc = 0;
  return groups.map((g) => {
    const from = Math.round((acc / total) * dur);
    acc += g.length;
    const to = Math.round((acc / total) * dur);
    return {text: g, from, to};
  });
};

const Captions: React.FC<{text: string; dur: number}> = ({text, dur}) => {
  const chunks = chunkCaption(text, dur);
  return (
    <>
      {chunks.map((c, i) => (
        <Sequence key={i} from={c.from} durationInFrames={Math.max(1, c.to - c.from)}>
          <AbsoluteFill
            style={{
              justifyContent: 'flex-end',
              alignItems: 'center',
              paddingBottom: '22%',
            }}
          >
            <div
              style={{
                fontFamily: 'Inter, Montserrat, Helvetica, Arial, sans-serif',
                fontWeight: 900,
                fontSize: 62,
                lineHeight: 1.08,
                letterSpacing: 0.4,
                color: '#ffffff',
                textAlign: 'center',
                maxWidth: '84%',
                textShadow: '0 4px 18px rgba(0,0,0,0.65), 0 1px 3px rgba(0,0,0,0.9)',
              }}
            >
              {c.text}
            </div>
          </AbsoluteFill>
        </Sequence>
      ))}
    </>
  );
};

export const Film: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: '#05070d'}}>
    {SHOTS.map((shot) => (
      <Sequence key={shot.id} from={shot.start} durationInFrames={shot.frames} name={shot.id}>
        <FrameSeq start={shot.start} />
        <Captions text={shot.caption} dur={shot.frames} />
      </Sequence>
    ))}

    {/* narration: one track per beat, running across its cuts */}
    {BEATS.map((b) => (
      <Sequence key={`a-${b.beat}`} from={b.start} durationInFrames={b.frames} name={`audio-${b.beat}`}>
        <Audio src={staticFile(`audio/${b.beat}.wav`)} />
      </Sequence>
    ))}

    {/* sound bridges: the next cut's whoosh starts 8 frames before its picture */}
    {SHOTS.slice(1).map((shot) => (
      <Sequence key={`w-${shot.id}`} from={shot.start - 8} durationInFrames={16}>
        <Audio src={staticFile('audio/foley/whoosh.wav')} volume={0.34} />
      </Sequence>
    ))}

    {/* one low impact where the twist lands */}
    {SHOTS.filter((s) => s.id === '06-twist').map((shot) => (
      <Sequence key="impact" from={shot.start} durationInFrames={33}>
        <Audio src={staticFile('audio/foley/impact.wav')} volume={0.5} />
      </Sequence>
    ))}
  </AbsoluteFill>
);
