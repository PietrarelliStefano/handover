import React from "react";
import { CalculateMetadataFunction, Composition } from "remotion";
import { Plan, segmentFrames } from "./plan";
import { isAroll, Reel } from "./Reel";

const EMPTY: Plan = {
  version: 1,
  shooting_id: "vuoto",
  format: { w: 1440, h: 2560, fps: 25 },
  template: "venezia-v1",
  segments: [],
  audio: { music: null, voice_lufs: -14 },
  end_card: false,
};

const metadata: CalculateMetadataFunction<Plan> = ({ props }) => {
  if (props.version !== 1) throw new Error(`Piano versione ${props.version}: il render supporta la versione 1`);
  const fps = props.format.fps;
  const frames = props.segments.filter(isAroll).reduce((n, s) => n + segmentFrames(s, fps), 0);
  return { durationInFrames: Math.max(1, frames), fps, width: props.format.w, height: props.format.h };
};

export const Root: React.FC = () => (
  <Composition
    id="Reel"
    component={Reel}
    defaultProps={EMPTY}
    calculateMetadata={metadata}
    durationInFrames={1}
    fps={25}
    width={1440}
    height={2560}
  />
);
