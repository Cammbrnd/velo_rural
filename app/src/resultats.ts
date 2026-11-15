import "./resultats.css";
import { AXES, GRILLE_RURAL_MIN, INDICATEURS } from "./indicators";
import { chargerConfig, chargerDonnees, couverture } from "./data";
import { RAMPE, SEUILS, classe, poidsParDefaut, profil, scoreAxe, scoreGlobal, scoreMode, valeur, type Ligne, type Mode } from "./score";

const esc = (s: unknown) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
const arr = (v: number | null) => (v === null ? "n.d." : String(Math.round(v)));
const MODES: { id: Mode; label: string }[] = [
  { id: "global", label: "Priorité globale" },
  ...AXES.map((a) => ({ id: a.id as Mode, label: a.label })),
];
const TEXTE_CLAIR = [false, false, false, true, true, true]; // texte blanc sur les 3 classes foncees

interface Ranger {
  l: Ligne; code: string; nom: string; dep: string;
  global: number | null; usage: number | null; faisabilite: number | null; deficit: number | null; mode: number | null;
}

async function main() {
  const racine = document.getElementById("page")!;
  const cfg = await chargerConfig();
  const { table } = await chargerDonnees(cfg);
  const grilleDispo = table.some((l) => typeof l.grille === "number");
  const p = poidsParDefaut();
  const etat = { mode: "global" as Mode, rural: grilleDispo, dep: "", q: "", tri: "mode" as keyof Ranger, sens: -1, limite: 100, ouvert: null as string | null };
  const cov = couverture(table, INDICATEURS.map((i) => i.id));

  racine.innerHTML = `
    <header>
      <div><h1>Potentiel vélo en milieu rural — résultats</h1>
        <p class="sous">Classement des communes selon l'usage potentiel, la faisabilité d'aménagement et le déficit d'équipement.</p></div>
      <a href="./index.html">Ouvrir la carte →</a>
    </header>
    ${cfg.demo ? `<div class="bandeau"><b>Données de démonstration (synthétiques).</b> Les lignes ne sont pas de vraies communes.</div>` : ""}
    <section class="controles" aria-label="Filtres et pondération">
      <label>Classer selon<select id="mode">${MODES.map((m) => `<option value="${m.id}">${esc(m.label)}</option>`).join("")}</select></label>
      <label>Recherche (nom ou code)<input type="text" id="q" placeholder="ex. Aurillac ou 15014" /></label>
      <label>Département(s)<input type="text" id="dep" placeholder="ex. 03, 15, 63" /></label>
      <label class="case"><input type="checkbox" id="rural" ${etat.rural ? "checked" : ""} ${grilleDispo ? "" : "disabled"} />Communes rurales (grille 5 à 7)${grilleDispo ? "" : " — indisponible"}</label>
      ${AXES.map((a) => `<label>Poids : ${esc(a.label)} <output id="o_${a.id}">${p.axes[a.id]}</output>
        <input type="range" id="p_${a.id}" data-axe="${a.id}" min="0" max="5" step="0.5" value="${p.axes[a.id]}" /></label>`).join("")}
    </section>
    <section class="kpis" id="kpis"></section>
    <h2>Répartition des scores</h2>
    <div class="carte" id="histo"></div>
    <h2>Classement</h2>
    <div id="tableau"></div>
    <div class="actions"><button id="plus">Afficher 100 de plus</button><button id="csv">Exporter le classement (CSV)</button></div>
    <h2>Couverture des indicateurs</h2>
    <div class="carte"><div class="barres">${INDICATEURS.map((i) => `<div class="barre"><span>${esc(i.label)}</span><b>${Math.round(cov[i.id] * 100)} %</b><i><u style="width:${cov[i.id] * 100}%"></u></i></div>`).join("")}</div>
      <p class="desc">Part des communes renseignées. Un indicateur absent est ignoré dans le score ; à 0 %, il n'est pas encore branché.</p></div>`;

  const $ = <T extends HTMLElement>(s: string) => racine.querySelector(s) as T;

  function lignes(): Ranger[] {
    const deps = new Set(etat.dep.split(/[\s,;]+/).filter(Boolean).map((d) => d.toUpperCase()));
    const q = etat.q.trim().toLowerCase();
    const out: Ranger[] = [];
    for (const l of table) {
      if (etat.rural && !(typeof l.grille === "number" && l.grille >= GRILLE_RURAL_MIN)) continue;
      const dep = String(l.dep ?? ""), nom = String(l.nom ?? ""), code = String(l.code ?? "");
      if (deps.size && !deps.has(dep.toUpperCase())) continue;
      if (q && !nom.toLowerCase().includes(q) && !code.includes(q)) continue;
      out.push({ l, code, nom, dep, global: scoreGlobal(l, p), usage: scoreAxe(l, "usage", p), faisabilite: scoreAxe(l, "faisabilite", p), deficit: scoreAxe(l, "deficit", p), mode: scoreMode(l, etat.mode, p) });
    }
    return out;
  }

  const mediane = (v: number[]) => { const s = [...v].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };
  const pastille = (v: number | null) => v === null ? `<span class="pastille" style="background:#d9d8d2">n.d.</span>`
    : `<span class="pastille" style="background:${RAMPE[classe(v)]};color:${TEXTE_CLAIR[classe(v)] ? "#fff" : "#0b0b0b"}">${Math.round(v)}</span>`;

  function rendre() {
    const tout = lignes();
    const notes = tout.map((r) => r.mode).filter((v): v is number => v !== null);
    const med = mediane(notes);
    $("#kpis").innerHTML = [
      [tout.length.toLocaleString("fr-FR"), "communes retenues"],
      [med === null ? "n.d." : String(Math.round(med)), "score médian"],
      [notes.filter((v) => v >= SEUILS[SEUILS.length - 1]).length.toLocaleString("fr-FR"), `communes à ${SEUILS[SEUILS.length - 1]} et plus`],
      [notes.length.toLocaleString("fr-FR"), "communes avec un score"],
    ].map(([v, l]) => `<div class="kpi"><b>${v}</b><span>${l}</span></div>`).join("");

    // histogramme par classes de 10 points, couleurs = rampe de la carte
    const bins = Array.from({ length: 10 }, () => 0);
    for (const v of notes) bins[Math.min(9, Math.floor(v / 10))]++;
    const max = Math.max(1, ...bins), W = 640, H = 150, bw = W / 10;
    $("#histo").innerHTML = `<svg viewBox="0 0 ${W + 20} ${H + 28}" width="100%" style="max-height:200px" role="img" aria-label="Histogramme des scores">
      ${bins.map((n, i) => { const h = (n / max) * H; return `<g><rect x="${10 + i * bw + 2}" y="${H - h}" width="${bw - 4}" height="${h}" rx="3" fill="${RAMPE[classe(i * 10 + 5)]}"><title>${i * 10}–${i * 10 + 10} : ${n.toLocaleString("fr-FR")} communes</title></rect>
        <text x="${10 + i * bw + bw / 2}" y="${H + 14}" text-anchor="middle">${i * 10}</text></g>`; }).join("")}
      <line x1="10" x2="${W + 10}" y1="${H}" y2="${H}" stroke="#c3c2b7" /></svg>`;

    const cle = etat.tri;
    const tri = [...tout].sort((a, b) => {
      const x = (typeof a[cle] === "number" ? a[cle] : null) as number | null, y = (typeof b[cle] === "number" ? b[cle] : null) as number | null;
      if (typeof a[cle] === "string") return etat.sens * String(a[cle]).localeCompare(String(b[cle]), "fr");
      if (x === null) return 1; if (y === null) return -1;
      return etat.sens * (x - y);
    });
    const vis = tri.slice(0, etat.limite);
    const th = (k: keyof Ranger, t: string) => `<th data-tri="${k}" ${etat.tri === k ? `aria-sort="${etat.sens > 0 ? "ascending" : "descending"}"` : ""}>${t}${etat.tri === k ? (etat.sens > 0 ? " ▲" : " ▼") : ""}</th>`;
    $("#tableau").innerHTML = `<table><thead><tr><th>#</th>${th("nom", "Commune")}${th("dep", "Dép.")}${th("mode", "Score")}${th("usage", "Usage")}${th("faisabilite", "Faisabilité")}${th("deficit", "Déficit")}<th>Lecture</th></tr></thead><tbody>
      ${vis.map((r, i) => `<tr data-code="${esc(r.code)}" tabindex="0"><td>${i + 1}</td><td>${esc(r.nom)}</td><td>${esc(r.dep)}</td><td>${pastille(r.mode)}</td><td>${arr(r.usage)}</td><td>${arr(r.faisabilite)}</td><td>${arr(r.deficit)}</td><td class="profil">${esc(profil(r.usage, r.faisabilite, r.deficit))}</td></tr>
        ${etat.ouvert === r.code ? `<tr class="detail"><td colspan="8"><div class="barres">${INDICATEURS.map((ind) => { const v = valeur(r.l, ind.id); return `<div class="barre"><span>${esc(ind.label)}</span><b>${arr(v)}</b><i><u style="width:${v ?? 0}%"></u></i></div>`; }).join("")}</div></td></tr>` : ""}`).join("")}
      </tbody></table>${tri.length === 0 ? `<p class="desc">Aucune commune ne correspond aux filtres.</p>` : ""}`;
    ($("#plus") as HTMLButtonElement).hidden = tri.length <= etat.limite;
  }

  function csv() {
    const tri = lignes().sort((a, b) => (b.mode ?? -1) - (a.mode ?? -1));
    const ent = ["rang", "code", "nom", "dep", "score", "usage", "faisabilite", "deficit", ...INDICATEURS.map((i) => i.id)];
    const val = (v: unknown) => (typeof v === "number" ? String(Math.round(v * 10) / 10) : "");
    const txt = (s: string) => `"${s.replace(/"/g, '""')}"`;
    const rows = tri.map((r, i) => [i + 1, txt(r.code), txt(r.nom), txt(r.dep), val(r.mode), val(r.usage), val(r.faisabilite), val(r.deficit), ...INDICATEURS.map((ind) => val(valeur(r.l, ind.id)))].join(";"));
    const blob = new Blob(["﻿" + [ent.join(";"), ...rows].join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `classement_velo_rural_${etat.mode}.csv`; a.click(); URL.revokeObjectURL(a.href);
  }

  let minuterie = 0;
  const differe = () => { window.clearTimeout(minuterie); minuterie = window.setTimeout(() => { etat.limite = 100; rendre(); }, 200); };
  $("#mode").addEventListener("change", (e) => { etat.mode = (e.target as HTMLSelectElement).value as Mode; etat.tri = "mode"; etat.sens = -1; etat.limite = 100; rendre(); });
  $("#rural").addEventListener("change", (e) => { etat.rural = (e.target as HTMLInputElement).checked; etat.limite = 100; rendre(); });
  $("#q").addEventListener("input", (e) => { etat.q = (e.target as HTMLInputElement).value; differe(); });
  $("#dep").addEventListener("input", (e) => { etat.dep = (e.target as HTMLInputElement).value; differe(); });
  racine.querySelectorAll<HTMLInputElement>("input[data-axe]").forEach((el) => el.addEventListener("input", () => {
    p.axes[el.dataset.axe as keyof typeof p.axes] = Number(el.value);
    $(`#o_${el.dataset.axe}`).textContent = el.value;
    differe();
  }));
  $("#tableau").addEventListener("click", (e) => {
    const th = (e.target as HTMLElement).closest("th[data-tri]") as HTMLElement | null;
    if (th) { const k = th.dataset.tri as keyof Ranger; etat.sens = etat.tri === k ? -etat.sens : (k === "nom" || k === "dep" ? 1 : -1); etat.tri = k; rendre(); return; }
    const tr = (e.target as HTMLElement).closest("tbody tr[data-code]") as HTMLElement | null;
    if (tr) { etat.ouvert = etat.ouvert === tr.dataset.code ? null : tr.dataset.code!; rendre(); }
  });
  $("#tableau").addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") ((e.target as HTMLElement).closest("tbody tr[data-code]") as HTMLElement | null)?.click(); });
  $("#plus").addEventListener("click", () => { etat.limite += 100; rendre(); });
  $("#csv").addEventListener("click", csv);
  rendre();
}

main().catch((e) => { document.getElementById("page")!.innerHTML = `<p class="bandeau">Erreur de chargement : ${esc(e.message)}</p>`; });
