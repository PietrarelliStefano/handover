// Raggruppamento delle parole in gruppi da 3–6 (§6.5) e parola attiva per il karaoke.
import type { Word } from "./plan";

export type Group = { words: Word[]; showFrom: number; showTo: number }; // ms, tempo della clip

export const MAX_WORDS = 6;
export const MAX_CHARS = 24; // circa due righe di Montserrat Black a 108 px in 1110 px di larghezza
export const BREAK_GAP_MS = 400;
export const HOLD_MS = 300;
export const BRIDGE_MS = 600;

export function groupWords(words: Word[]): Group[] {
  const groups: Word[][] = [];
  let cur: Word[] = [];
  const chars = (ws: Word[]) => ws.reduce((n, w) => n + w.t.length + 1, 0);
  words.forEach((w, i) => {
    if (cur.length && (cur.length >= MAX_WORDS || chars(cur) + w.t.length > MAX_CHARS)) {
      groups.push(cur);
      cur = [];
    }
    cur.push(w);
    const next = words[i + 1];
    const sentenceEnd = /[.?!…]$/.test(w.t);
    const comma = /[,;:]$/.test(w.t) && cur.length >= 3;
    const pause = next ? next.start_ms - w.end_ms > BREAK_GAP_MS : true;
    // fine frase, virgola dopo almeno 3 parole o pausa chiudono il gruppo; altrimenti fino a 6 parole o ~2 righe
    if (!next || sentenceEnd || comma || pause) {
      groups.push(cur);
      cur = [];
    }
  });
  if (cur.length) groups.push(cur);
  return groups.map((ws, i) => {
    const next = groups[i + 1];
    const end = ws[ws.length - 1].end_ms;
    const showTo = next && next[0].start_ms - end < BRIDGE_MS ? next[0].start_ms : end + HOLD_MS;
    return { words: ws, showFrom: ws[0].start_ms, showTo };
  });
}

// a schermo niente punteggiatura, tranne ? e ! (stile del template)
export const displayText = (t: string) => t.replace(/[.,;:…]+$/, "");

export function activeWordIndex(g: Group, ms: number): number {
  // parola pronunciata; nelle pause resta evidenziata l'ultima detta
  let idx = -1;
  g.words.forEach((w, i) => {
    if (ms >= w.start_ms) idx = i;
  });
  return idx;
}
