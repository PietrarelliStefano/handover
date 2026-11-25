import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { Word } from "./plan";
import { activeWordIndex, displayText, groupWords } from "./captionGroups";

// Stile misurato sul reel 11.14 (§6.5): Montserrat Black maiuscolo bianco, contorno nero ~5 px,
// parola pronunciata in un riquadro #003864 con angoli arrotondati; testo tra y 1838 e 2097,
// margine destro ≥ 210 px per i pulsanti di Instagram e TikTok.
export const BRAND_BOX = "#003864";
const LEFT = 120;
const RIGHT = 210;
const TOP = 1790;
const HEIGHT = 300;

export const Subtitles: React.FC<{ words: Word[]; inMs: number; color?: string }> = ({ words, inMs, color }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = inMs + (frame * 1000) / fps; // tempo della clip
  const group = groupWords(words).find((g) => ms >= g.showFrom && ms < g.showTo);
  if (!group) return null;
  const active = activeWordIndex(group, ms);
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: LEFT,
          width: 1440 - LEFT - RIGHT,
          top: TOP,
          height: HEIGHT,
          display: "flex",
          flexWrap: "wrap",
          alignContent: "center",
          justifyContent: "center",
          rowGap: 6,
          fontFamily: "Montserrat",
          fontWeight: 900,
          fontSize: 108,
          lineHeight: 1.12,
          textTransform: "uppercase",
          color: "white",
          textAlign: "center",
        }}
      >
        {group.words.map((w, i) => (
          <span
            key={`${w.start_ms}-${i}`}
            style={{
              margin: "0 10px",
              padding: "0 14px",
              borderRadius: 8,
              background: i === active ? color ?? BRAND_BOX : "transparent",
              WebkitTextStroke: "10px black",
              paintOrder: "stroke fill",
            }}
          >
            {displayText(w.t)}
          </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};
