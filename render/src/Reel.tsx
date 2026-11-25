import { loadFont } from "@remotion/fonts";
import React from "react";
import { AbsoluteFill, OffthreadVideo, Series, staticFile } from "remotion";
import montserrat900 from "@fontsource/montserrat/files/montserrat-latin-900-normal.woff2";
import { ArollSegment, mezzanineFor, Plan, segmentFrames, toFrame } from "./plan";
import { Subtitles } from "./Subtitles";

loadFont({ family: "Montserrat", url: montserrat900, weight: "900" });

export const isAroll = (s: Plan["segments"][number]): s is ArollSegment => s.type === "aroll";

export const Reel: React.FC<Plan> = (plan) => {
  const fps = plan.format.fps;
  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <Series>
        {plan.segments.filter(isAroll).map((s) => (
          <Series.Sequence key={s.id} durationInFrames={segmentFrames(s, fps)} name={`${s.id} ${s.clip}`}>
            <AbsoluteFill style={{ transform: `scale(${s.zoom})` }}>
              <OffthreadVideo
                src={staticFile(mezzanineFor(s.clip))}
                trimBefore={toFrame(s.in_ms, fps)}
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
            </AbsoluteFill>
            <Subtitles words={s.words} inMs={s.in_ms} />
          </Series.Sequence>
        ))}
      </Series>
    </AbsoluteFill>
  );
};
