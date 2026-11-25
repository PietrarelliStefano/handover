// node --experimental-strip-types src/captionGroups.test.ts
import assert from "node:assert/strict";
import { activeWordIndex, displayText, groupWords } from "./captionGroups.ts";

const W = (text: string, t0 = 0, step = 300) =>
  text.split(" ").map((t, i) => ({ t, start_ms: t0 + i * step, end_ms: t0 + i * step + 250, critical: false }));

const g1 = groupWords(W("Ehi scusa ma tu sei un agente immobiliare?"));
assert.deepEqual(g1.map((g) => g.words.map((w) => w.t).join(" ")), ["Ehi scusa ma tu sei un", "agente immobiliare?"]);

const g2 = groupWords([...W("Sei un agente?"), ...W("Sì posso esserti utile", 1200)]);
assert.deepEqual(g2.map((g) => g.words.length), [3, 4]);           // la domanda chiude il gruppo
assert.equal(g2[0].showTo, 1200);                                    // pausa breve: resta a schermo fino al gruppo dopo

const long = groupWords(W("€188.000 per vivere in questi tre locali in classe A"));
assert.ok(long.every((g) => g.words.reduce((n, w) => n + w.t.length + 1, 0) <= 26));

assert.equal(activeWordIndex(g2[1], 1550), 1);
assert.equal(activeWordIndex(g2[1], 1100), -1);
const g3 = groupWords([...W("Sei un agente?"), ...W("Sì", 2000)]);
assert.equal(g3[0].showTo, 850 + 300);                               // pausa lunga: sparisce dopo 300 ms
const g4 = groupWords(W("Il prezzo €188.000. Contattami, io sono Simone Venezia."));
assert.deepEqual(g4.map((g) => g.words.map((w) => displayText(w.t)).join(" ")),
                 ["Il prezzo €188.000", "Contattami io sono", "Simone Venezia"]);  // oltre ~2 righe si va a capo
console.log("captionGroups.test.ts: ok");
