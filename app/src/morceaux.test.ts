import { afterEach, expect, test, vi } from "vitest";
import { SourceMorceaux } from "./morceaux";

const fichier = Uint8Array.from({ length: 25 }, (_, i) => i);
const appels: string[] = [];
vi.stubGlobal("fetch", async (u: string) => {
  appels.push(u);
  const i = Number(/(\d{4})\.bin/.exec(u)![1]);
  if (i === 1 && appels.filter((a) => a.includes("0001")).length === 1) return { ok: false, status: 503 }; // un echec transitoire
  return { ok: true, status: 200, arrayBuffer: async () => fichier.slice(i * 10, i * 10 + 10).buffer };
});
afterEach(() => (appels.length = 0));

test("lecture d'une plage a cheval sur plusieurs morceaux, avec reprise sur echec", async () => {
  const s = new SourceMorceaux("http://x/d", "?v=1", 25, 10);
  const r = await s.getBytes(8, 14);
  expect(Array.from(new Uint8Array(r.data))).toEqual(Array.from({ length: 14 }, (_, i) => 8 + i));
  expect(appels.every((a) => a.endsWith("?v=1"))).toBe(true);
});

test("plage depassant la fin du fichier : tronquee", async () => {
  const s = new SourceMorceaux("http://x/d2", "", 25, 10);
  expect((await s.getBytes(20, 100)).data.byteLength).toBe(5);
});
