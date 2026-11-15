import { AXES, GRILLE_RURAL_MIN, INDICATEURS, type Axe } from "./indicators";

export type Mode = "global" | Axe;
export type Ligne = Record<string, unknown>;
export interface Poids {
  indicateurs: Record<string, number>;
  axes: Record<Axe, number>;
}
// Expression MapLibre (tableau JSON). Typage volontairement souple.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Expr = any;

export function poidsParDefaut(): Poids {
  return {
    indicateurs: Object.fromEntries(INDICATEURS.map((i) => [i.id, i.poids])),
    axes: Object.fromEntries(AXES.map((a) => [a.id, a.poids])) as Record<Axe, number>,
  };
}

export function valeur(l: Ligne, id: string): number | null {
  const v = l[id];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

// ---------- calcul cote JS (classement, fiche, infobulle) ----------

export function scoreAxe(l: Ligne, axe: Axe, p: Poids): number | null {
  let num = 0;
  let den = 0;
  for (const ind of INDICATEURS) {
    if (ind.axe !== axe) continue;
    const v = valeur(l, ind.id);
    const w = p.indicateurs[ind.id] ?? 0;
    if (v !== null && w > 0) {
      num += w * v;
      den += w;
    }
  }
  return den > 0 ? num / den : null;
}

export function scoreGlobal(l: Ligne, p: Poids): number | null {
  let num = 0;
  let den = 0;
  for (const a of AXES) {
    const s = scoreAxe(l, a.id, p);
    const w = p.axes[a.id] ?? 0;
    if (s !== null && w > 0) {
      num += w * s;
      den += w;
    }
  }
  return den > 0 ? num / den : null;
}

export function scoreMode(l: Ligne, mode: Mode, p: Poids): number | null {
  return mode === "global" ? scoreGlobal(l, p) : scoreAxe(l, mode, p);
}

// ---------- meme calcul, exprime en expression MapLibre (coloration GPU) ----------
// Convention : -1 = score indisponible.

// vrai si la propriete est un nombre (absente ou null => faux : un null GeoJSON ne devient jamais 0)
const present = (id: string): Expr => ["==", ["typeof", ["get", id]], "number"];

function exprAxe(axe: Axe, p: Poids): Expr {
  const actifs = INDICATEURS.filter((i) => i.axe === axe && (p.indicateurs[i.id] ?? 0) > 0);
  if (actifs.length === 0) return -1;
  const num = ["+", 0, ...actifs.map((i) => ["case", present(i.id), ["*", p.indicateurs[i.id], ["get", i.id]], 0])];
  const den = ["+", 0, ...actifs.map((i) => ["case", present(i.id), p.indicateurs[i.id], 0])];
  return ["case", [">", den, 0], ["/", num, den], -1];
}

export function exprScore(mode: Mode, p: Poids): Expr {
  if (mode !== "global") return exprAxe(mode, p);
  const actifs = AXES.filter((a) => (p.axes[a.id] ?? 0) > 0);
  if (actifs.length === 0) return -1;
  const bind = actifs.flatMap((a) => [a.id, exprAxe(a.id, p)]);
  const num = ["+", 0, ...actifs.map((a) => ["case", [">=", ["var", a.id], 0], ["*", p.axes[a.id], ["var", a.id]], 0])];
  const den = ["+", 0, ...actifs.map((a) => ["case", [">=", ["var", a.id], 0], p.axes[a.id], 0])];
  return ["let", ...bind, ["case", [">", den, 0], ["/", num, den], -1]];
}

// ---------- classes de couleur (rampe sequentielle bleue, 1 teinte clair -> fonce) ----------

export const SEUILS = [30, 40, 50, 60, 70];
export const RAMPE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#1c5cab", "#0d366b"];
export const SANS_DONNEE = "#d9d8d2";

export function exprCouleur(mode: Mode, p: Poids): Expr {
  const etapes: Expr[] = [SANS_DONNEE, 0, RAMPE[0]];
  SEUILS.forEach((s, k) => etapes.push(s, RAMPE[k + 1]));
  return ["step", exprScore(mode, p), ...etapes];
}

export function classe(score: number | null): number {
  if (score === null) return -1;
  let k = 0;
  for (const s of SEUILS) if (score >= s) k++;
  return k;
}

export function libellesClasses(): string[] {
  const bornes = [0, ...SEUILS];
  return bornes.map((b, k) => (k === 0 ? `< ${SEUILS[0]}` : k === bornes.length - 1 ? `≥ ${b}` : `${b} – ${bornes[k + 1]}`));
}

// ---------- lecture indicative du profil ----------
export const SEUIL_USAGE = 55;
export const SEUIL_FAISABILITE = 50;
export interface Seuils { usage: number; faisabilite: number; deficit: number }
export const SEUILS_DEFAUT: Seuils = { usage: SEUIL_USAGE, faisabilite: SEUIL_FAISABILITE, deficit: 50 };

function quantile(v: number[], q: number): number | null {
  if (!v.length) return null;
  const s = [...v].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
}

// Seuils relatifs a la distribution reelle (communes rurales si la grille existe) : "fort" / "facile" = tiers superieur,
// "deficitaire" = moitie superieure. Evite des seuils fixes mal calibres quand les poids ou les donnees changent.
export function seuilsRelatifs(table: Ligne[], p: Poids): Seuils {
  const rural = table.some((l) => typeof l.grille === "number")
    ? table.filter((l) => typeof l.grille === "number" && l.grille >= GRILLE_RURAL_MIN)
    : table;
  const q = (axe: Axe, f: number, defaut: number) =>
    quantile(rural.map((l) => scoreAxe(l, axe, p)).filter((v): v is number => v !== null), f) ?? defaut;
  return { usage: q("usage", 2 / 3, SEUIL_USAGE), faisabilite: q("faisabilite", 2 / 3, SEUIL_FAISABILITE), deficit: q("deficit", 0.5, 50) };
}

export function profil(u: number | null, f: number | null, d: number | null, s: Seuils = SEUILS_DEFAUT): string {
  if (u === null) return "Profil non évaluable (données d'usage manquantes).";
  const fort = u >= s.usage;
  const facile = f === null ? null : f >= s.faisabilite;
  const retard = d !== null && d >= s.deficit;
  if (fort && facile !== false) return retard ? "Priorité d'aménagement : forte demande, conditions favorables, réseau déficitaire." : "Forte demande et conditions favorables ; réseau déjà relativement équipé.";
  if (fort && facile === false) return "Forte demande mais aménagement difficile : privilégier solutions légères (VAE, itinéraires partagés).";
  if (facile) return "Demande modérée, conditions favorables : opportunité à moindre coût (loisir, cyclotourisme).";
  return "Priorité faible à ce stade.";
}
