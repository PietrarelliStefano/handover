import { loadFont } from "@remotion/fonts";
import React from "react";
import { AbsoluteFill, Audio, OffthreadVideo, Sequence, staticFile, useCurrentFrame } from "remotion";
import montserrat900 from "@fontsource/montserrat/files/montserrat-latin-900-normal.woff2";
import { dbToGain, mezzanineFor, Plan, toFrame } from "./plan";
import { Subtitles } from "./Subtitles";
import { endingFactor, musicVolume, placeSegments, sfxFrames, speechIntervals, totalFrames } from "./timeline";

loadFont({ family: "Montserrat", url: montserrat900, weight: "900" });

const FadeToBlack: React.FC<{ plan: Plan; total: number }> = ({ plan, total }) => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ backgroundColor: "black", opacity: 1 - endingFactor(plan, frame, total) }} />;
};

export const Reel: React.FC<Plan> = (plan) => {
  const fps = plan.format.fps;
  const placed = placeSegments(plan);
  const total = totalFrames(placed);
  const speech = speechIntervals(plan, placed);
  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {placed.map(({ seg, from, frames }) => (
        <Sequence key={seg.id} from={from} durationInFrames={frames} name={`${seg.id} ${seg.clip}`}>
          <AbsoluteFill style={{ transform: `scale(${seg.zoom})` }}>
            <OffthreadVideo
              src={staticFile(mezzanineFor(seg.clip))}
              trimBefore={toFrame(seg.in_ms, fps)}
              volume={(f) => endingFactor(plan, from + f, total)}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          </AbsoluteFill>
          <Subtitles words={seg.words} inMs={seg.in_ms} />
        </Sequence>
      ))}
      {plan.audio.music && (
        <Audio
          src={staticFile(plan.audio.music.track)}
          loop
          volume={(f) => musicVolume(plan, f, total, speech)}
        />
      )}
      {sfxFrames(plan, placed).map(({ frame, sfx }, i) => (
        <Sequence key={`sfx-${i}`} from={frame} name={`sfx ${sfx.kind}`}>
          <Audio src={staticFile(sfx.file)} volume={dbToGain(sfx.gain_db)} />
        </Sequence>
      ))}
      <FadeToBlack plan={plan} total={total} />
    </AbsoluteFill>
  );
};
