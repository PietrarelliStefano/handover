// Piano di montaggio, versione 1 (docs/specifica-v1.md §7). Deve restare allineato alla specifica.

export type Word = { t: string; start_ms: number; end_ms: number; critical: boolean };

export type ArollSegment = {
  id: string;
  type: "aroll";
  clip: string; // nome del file originale; il render usa il mezzanine <stem>.mov
  rotation: number;
  in_ms: number;
  out_ms: number;
  zoom: number;
  words: Word[];
};

export type Segment = ArollSegment | { id: string; type: "broll" | "generated"; [k: string]: unknown };

export type Plan = {
  version: number;
  shooting_id: string;
  format: { w: number; h: number; fps: number };
  template: string;
  segments: Segment[];
  audio: { music: unknown; voice_lufs: number };
  end_card: boolean;
};

export const toFrame = (ms: number, fps: number) => Math.round((ms * fps) / 1000);

export const segmentFrames = (s: ArollSegment, fps: number) =>
  Math.max(1, toFrame(s.out_ms, fps) - toFrame(s.in_ms, fps));

export const mezzanineFor = (clip: string) => `mezzanine/${clip.replace(/\.[^.]+$/, "")}.mov`;
