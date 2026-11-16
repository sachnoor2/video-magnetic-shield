import React from 'react';
import {Composition} from 'remotion';
import {Film} from './Film';
import manifest from './manifest.json';
import shotlist from '../shotlist.json';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Video"
    component={Film}
    durationInFrames={manifest.totalFrames}
    fps={shotlist.fps}
    width={shotlist.width}
    height={shotlist.height}
  />
);
