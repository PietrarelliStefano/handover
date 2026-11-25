// Tempi del reel in fotogrammi, calcolati dal piano (funzioni pure, testate in timeline.test.ts).
import { segmentFrames, toFrame } from "./plan.ts";
import type { ArollSegment, Plan } from "./plan.ts";

export const isAroll = (s: Plan["segments"][number]): s is ArollSegment => s.type === "aroll";

export type Placed = { seg: ArollSegment; from: number; frames: number };

export function placeSegments(plan: Plan): Placed[] {
  const fps = plan.format.fps;
  let from = 0;
  return plan.segments.filter(isAroll).map((seg) => {
    const frames = segmentFrames(seg, fps);
    const p = { seg, from, frames };
    from += frames;
    return p;
  });
}

export const totalFrames = (placed: Placed[]) => placed.reduce((n, p) => n + p.frames, 0);

/** Intervalli di parlato nel reel [da, a) in fotogrammi, uniti se la pausa è sotto `bridgeMs`. */
export function speechIntervals(plan: Plan, placed: Placed[], bridgeMs = 400): [number, number][] {
  const fps = plan.format.fps;
  const out: [number, number][] = [];
  for (const { seg, from, frames } of placed) {
    for (const w of seg.words) {
      const a = from + toFrame(w.start_ms - seg.in_ms, fps);
      const b = Math.min(from + frames, from + toFrame(w.end_ms - seg.in_ms, fps));
      const last = out[out.length - 1];
      if (last && a - last[1] <= toFrame(bridgeMs, fps)) last[1] = Math.max(last[1], b);
      else out.push([a, b]);
    }
  }
  return out;
}

/** Fotogramma assoluto di ogni SFX (gli SFX su segmenti inesistenti vengono scartati). */
export function sfxFrames(plan: Plan, placed: Placed[]): { frame: number; sfx: Plan["audio"]["sfx"][number] }[] {
  const fps = plan.format.fps;
  const start = new Map(placed.map((p) => [p.seg.id, p.from]));
  return plan.audio.sfx
    .filter((s) => start.has(s.segment))
    .map((s) => ({ frame: Math.max(0, (start.get(s.segment) as number) + toFrame(s.offset_ms, fps)), sfx: s }));
}

const ramp = (x: number) => Math.min(1, Math.max(0, x));

/** Volume della musica (lineare) al fotogramma f: ducking sotto la voce, fade-in, fade-out finale. */
export function musicVolume(plan: Plan, f: number, total: number, speech: [number, number][]): number {
  const m = plan.audio.music;
  if (!m) return 0;
  const fps = plan.format.fps;
  const rampF = Math.max(1, toFrame(250, fps)); // 0,25 s per scendere o risalire
  const duckDb = m.gain_db; // sotto la voce
  const openDb = m.gain_db + 12; // nelle pause e senza voce
  let near = Infinity; // distanza in fotogrammi dal parlato più vicino
  for (const [a, b] of speech) {
    if (f >= a && f < b) { near = 0; break; }
    near = Math.min(near, f < a ? a - f : f - b + 1);
  }
  const k = m.duck ? ramp(near / rampF) : 1; // 0 = sotto la voce, 1 = aperta
  const db = duckDb + (openDb - duckDb) * k;
  const fadeIn = ramp(f / Math.max(1, toFrame(m.fade_in_ms, fps)));
  const fadeOut = ramp((total - f) / Math.max(1, toFrame(m.fade_out_ms, fps)));
  return Math.pow(10, db / 20) * fadeIn * fadeOut;
}

/** Fattore del fade a nero (1 = pieno, 0 = nero) al fotogramma f. */
export function endingFactor(plan: Plan, f: number, total: number): number {
  const fadeF = toFrame(plan.ending?.fade_out_ms ?? 0, plan.format.fps);
  if (fadeF <= 0) return 1;
  return ramp((total - f) / fadeF);
}
