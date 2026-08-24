import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {RecapOverlay} from './RecapOverlay';

const Root: React.FC = () => (
  <Composition
    id="RecapOverlay"
    component={RecapOverlay}
    durationInFrames={1474}
    fps={25}
    width={1920}
    height={1080}
  />
);

registerRoot(Root);
