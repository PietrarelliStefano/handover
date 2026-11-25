// node --experimental-strip-types src/timeline.test.ts
import assert from "node:assert/strict";
import type { Plan } from "./plan.ts";
import { endingFactor, musicVolume, placeSegments, sfxFrames, speechIntervals, totalFrames } from "./timeline.ts";

const w = (t: string, a: number, b: number) => ({ t, start_ms: a, end_ms: b, critical: false });
const plan: Plan = {
  version: 2, shooting_id: "x", format: { w: 1440, h: 2560, fps: 25 }, template: "venezia-v1",
  segments: [
    { id: "s1", type: "aroll", clip: "A.MOV", rotation: 90, in_ms: 1000, out_ms: 3000, zoom: 1, words: [w("ciao", 1200, 1600)] },
    { id: "s2", type: "aroll", clip: "B.MOV", rotation: 90, in_ms: 0, out_ms: 4000, zoom: 1, words: [w("costa", 500, 900), w("€188.000", 1000, 1800)] },
  ],
  audio: {
    music: { track: "lib/musica/L-0001.mp3", license_id: "L-0001", gain_db: -20, duck: true, fade_in_ms: 500, fade_out_ms: 1500 },
    sfx: [{ kind: "whoosh", file: "lib/sfx/S-0001.wav", license_id: "S-0001", segment: "s2", offset_ms: -200, gain_db: -12 },
          { kind: "prezzo", file: "lib/sfx/S-0002.wav", license_id: "S-0002", segment: "s9", offset_ms: 0, gain_db: -12 }],
    voice_lufs: -14,
  },
  ending: { fade_out_ms: 1200 }, end_card: false,
};

const placed = placeSegments(plan);
assert.deepEqual(placed.map((p) => [p.from, p.frames]), [[0, 50], [50, 100]]);
const total = totalFrames(placed);
assert.equal(total, 150);
assert.deepEqual(sfxFrames(plan, placed).map((s) => s.frame), [45]);         // 5 fotogrammi prima del taglio; s9 scartato
const speech = speechIntervals(plan, placed);
assert.deepEqual(speech, [[5, 15], [63, 95]]);                               // "costa" e il prezzo uniti (pausa 100 ms)
const dB = (g: number) => 20 * Math.log10(g);
assert.ok(Math.abs(dB(musicVolume(plan, 70, total, speech)) - -20) < 0.01);  // sotto la voce: −20 dB
assert.ok(Math.abs(dB(musicVolume(plan, 30, total, speech)) - -8) < 0.01);   // lontano dalla voce: −8 dB
assert.equal(musicVolume(plan, 0, total, speech), 0);                        // fade-in
assert.equal(endingFactor(plan, 149, total) < 0.05, true);                   // quasi nero all'ultimo fotogramma
assert.equal(endingFactor(plan, 100, total), 1);                             // prima del fade
console.log("timeline.test.ts: ok");
