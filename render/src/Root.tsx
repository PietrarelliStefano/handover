import React from "react";
import { CalculateMetadataFunction, Composition } from "remotion";
import { Plan, PLAN_VERSION } from "./plan";
import { Reel } from "./Reel";
import { placeSegments, totalFrames } from "./timeline";

const EMPTY: Plan = {
  version: PLAN_VERSION,
  shooting_id: "vuoto",
  format: { w: 1440, h: 2560, fps: 25 },
  template: "venezia-v1",
  segments: [],
  audio: { music: null, sfx: [], voice_lufs: -14 },
  ending: { fade_out_ms: 0 },
  end_card: false,
};

const metadata: CalculateMetadataFunction<Plan> = ({ props }) => {
  if (props.version !== PLAN_VERSION)
    throw new Error(`Piano versione ${props.version}: il render supporta la versione ${PLAN_VERSION}. Rigenera il piano.`);
  const frames = totalFrames(placeSegments(props));
  return { durationInFrames: Math.max(1, frames), fps: props.format.fps, width: props.format.w, height: props.format.h };
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
