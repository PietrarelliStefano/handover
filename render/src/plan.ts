// Piano di montaggio, versione 2 (docs/specifica-v1.md §7, rev. 8). Deve restare allineato alla specifica.

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

export type Music = {
  track: string; // relativo alla cartella di lavoro (public dir)
  license_id: string;
  gain_db: number; // livello sotto la voce
  duck: boolean;
  fade_in_ms: number;
  fade_out_ms: number;
};

export type Sfx = {
  kind: "whoosh" | "prezzo" | "card";
  file: string;
  license_id: string;
  segment: string;
  offset_ms: number; // dall'inizio del segmento, anche negativo
  gain_db: number;
};

export type Plan = {
  version: number;
  shooting_id: string;
  format: { w: number; h: number; fps: number };
  template: string;
  segments: Segment[];
  audio: { music: Music | null; sfx: Sfx[]; voice_lufs: number };
  ending: { fade_out_ms: number };
  end_card: boolean;
};

export const PLAN_VERSION = 2;

export const dbToGain = (db: number) => Math.pow(10, db / 20);

export const toFrame = (ms: number, fps: number) => Math.round((ms * fps) / 1000);

export const segmentFrames = (s: ArollSegment, fps: number) =>
  Math.max(1, toFrame(s.out_ms, fps) - toFrame(s.in_ms, fps));

export const mezzanineFor = (clip: string) => `mezzanine/${clip.replace(/\.[^.]+$/, "")}.mov`;
