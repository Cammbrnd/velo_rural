import { describe, expect, it } from "vitest";
import { expression, latest } from "@maplibre/maplibre-gl-style-spec";
import { INDICATEURS } from "./indicators";
import { exprCouleur, exprScore, poidsParDefaut, scoreMode, type Ligne, type Mode } from "./score";

function evaluer(expr: unknown, props: Ligne, spec: object): unknown {
  const r = expression.createPropertyExpression(expr as never, "paint", spec as never);
  if (r.result !== "success") throw new Error(JSON.stringify(r.value));
  const feature = { type: "Polygon", properties: props } as never;
  return (r.value as never as { evaluate: (g: object, f: unknown) => unknown }).evaluate({ zoom: 5 }, feature);
}
const specNombre = latest["paint_fill-extrusion"]["fill-extrusion-height"];
const specCouleur = latest.paint_fill["fill-color"];

function ligneAleatoire(seed: number): Ligne {
  let s = seed;
  const rnd = () => ((s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296);
  const l: Ligne = {};
  for (const i of INDICATEURS) if (rnd() > 0.25) l[i.id] = Math.round(rnd() * 100);
  return l;
}

describe("score JS == expression MapLibre", () => {
  const modes: Mode[] = ["global", "usage", "faisabilite", "deficit"];
  const p = poidsParDefaut();
  p.indicateurs["i_relief"] = 0; // indicateur desactive
  p.axes.deficit = 1.5;
  for (const mode of modes) {
    it(`mode ${mode}`, () => {
      for (let k = 1; k <= 60; k++) {
        const l = ligneAleatoire(k);
        const js = scoreMode(l, mode, p);
        const ex = evaluer(exprScore(mode, p), l, specNombre) as number;
        if (js === null) expect(ex).toBe(-1);
        else expect(ex).toBeCloseTo(js, 6);
      }
    });
  }
  it("l'expression de couleur est valide et donne un gris sans donnee", () => {
    const c = evaluer(exprCouleur("global", p), {}, specCouleur) as { r: number };
    expect(c).toBeTruthy();
    const ok = evaluer(exprCouleur("global", p), { i_gisement: 90, i_deficit_lineaire: 80 }, specCouleur) as { b: number };
    expect(ok.b).toBeGreaterThan(0);
  });
  it("une valeur null est ignoree (pas convertie en 0)", () => {
    const l: Ligne = { i_gisement: null, i_emploi_local: 80 };
    const js = scoreMode(l, "usage", p);
    const ex = evaluer(exprScore("usage", p), l, specNombre) as number;
    expect(js).toBe(80);
    expect(ex).toBeCloseTo(80, 6);
  });
  it("tous poids a zero => indisponible", () => {
    const z = poidsParDefaut();
    for (const k of Object.keys(z.axes)) z.axes[k as keyof typeof z.axes] = 0;
    expect(scoreMode({ i_gisement: 50 }, "global", z)).toBeNull();
    expect(evaluer(exprScore("global", z), { i_gisement: 50 }, specNombre)).toBe(-1);
  });
});
