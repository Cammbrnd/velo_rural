import { AXES, GRILLE_RURAL_MIN, INDICATEURS } from "./indicators";
import { couverture, type Config } from "./data";
import {
  RAMPE, SANS_DONNEE, SEUILS_DEFAUT, libellesClasses, poidsParDefaut, profil, scoreAxe, scoreMode, seuilsRelatifs,
  type Ligne, type Mode, type Poids, type Seuils,
} from "./score";

export interface Etat {
  mode: Mode;
  rural: boolean;
  poids: Poids;
}
export interface Rappels {
  onChange: () => void; // modification du mode, du filtre ou des poids (recolorer la carte)
  onSelection: (code: string | null) => void;
}

const MODES: { id: Mode; label: string }[] = [
  { id: "global", label: "Priorité globale (usage × faisabilité × déficit)" },
  { id: "usage", label: "Potentiel d'usage" },
  { id: "faisabilite", label: "Faisabilité d'aménagement" },
  { id: "deficit", label: "Déficit d'équipement" },
];

const esc = (s: unknown) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
const fmt = (v: number | null) => (v === null ? "n.d." : String(Math.round(v)));

export function estRural(l: Ligne): boolean {
  const g = l.grille;
  return typeof g === "number" && g >= GRILLE_RURAL_MIN;
}

export function monterPanneau(root: HTMLElement, cfg: Config, table: Ligne[], etat: Etat, rappels: Rappels) {
  const cov = couverture(table, INDICATEURS.map((i) => i.id));
  const index = new Map<string, Ligne>(table.map((l) => [String(l.code), l]));
  let selection: string | null = null;
  const grilleDispo = table.some((l) => typeof l.grille === "number");
  if (!grilleDispo) etat.rural = false;

  const curseur = (id: string, label: string, valeur: number, extra = "", desc = "") => `
    <div class="curseur">
      <label class="nom" for="p_${id}"><span>${esc(label)}</span>${extra}</label>
      <input type="range" id="p_${id}" data-id="${id}" min="0" max="5" step="0.5" value="${valeur}" />
      <output id="o_${id}">${valeur}</output>
      ${desc ? `<p class="desc" style="grid-column:1/-1;margin:0">${esc(desc)}</p>` : ""}
    </div>`;

  root.innerHTML = `
    <h1>Potentiel vélo en milieu rural</h1>
    <p class="sous">Croise usage potentiel, faisabilité d'aménagement et déficit d'équipement, à l'échelle communale. <a href="./resultats.html">Voir le classement →</a></p>
    ${cfg.demo ? `<div class="bandeau"><b>Données de démonstration (synthétiques).</b> Les cellules affichées ne sont pas des communes réelles ; elles servent à tester l'interface.</div>` : ""}

    <h2>Affichage</h2>
    <label for="mode">Carte colorée selon</label>
    <select id="mode">${MODES.map((m) => `<option value="${m.id}">${esc(m.label)}</option>`).join("")}</select>
    <label class="case"><input type="checkbox" id="rural" ${etat.rural ? "checked" : ""} ${grilleDispo ? "" : "disabled"} /> Communes rurales uniquement (grille de densité INSEE 5 à 7)${grilleDispo ? "" : " — indisponible : grille absente des données"}</label>
    <div class="legende" id="legende" aria-label="Légende"></div>

    <div id="exemples-bloc" hidden>
      <h2>Exemples d'aménagement</h2>
      <p class="desc">Pour quelques EPCI répartis sur le territoire : les 3 axes depuis le pôle qui concentrent le plus de demande (population × score), calculés sur le réseau OSM en évitant routes fréquentées et dénivelé. Indicatif, à valider sur le terrain.</p>
      <label class="case"><input type="checkbox" id="exemples-voir" checked /> Afficher les tracés</label>
      <select id="exemples-choix" aria-label="Aller à un EPCI"><option value="">Aller à un EPCI…</option></select>
      <ul class="legende-ex">
        <li><i style="background:#1a9850"></i> Aménagement existant (voie verte, piste)</li>
        <li><i style="background:#f2a900"></i> Route calme : itinéraire partagé à signaler</li>
        <li><i style="background:#d7191c"></i> Tronçon à sécuriser (route plus fréquentée)</li>
      </ul>
    </div>

    <h2>Pondération</h2>
    <p class="desc">Poids de 0 (ignoré) à 5. Les indicateurs absents des données sont ignorés ; la couverture indique la part de communes renseignées.</p>
    <div id="poids-axes">${AXES.map((a) => curseur("axe_" + a.id, a.label, etat.poids.axes[a.id], "", a.description)).join("")}</div>
    ${AXES.map((a) => `
      <details>
        <summary>Indicateurs — ${esc(a.label)}</summary>
        ${INDICATEURS.filter((i) => i.axe === a.id).map((i) =>
          curseur(i.id, i.label, etat.poids.indicateurs[i.id], `<small>${Math.round((cov[i.id] ?? 0) * 100)} % renseigné</small>`, `${i.description} — ${i.source}`)).join("")}
      </details>`).join("")}
    <p><button id="reset" type="button">Réinitialiser les poids</button></p>

    <h2>Fiche commune</h2>
    <div id="fiche"><p class="desc">Cliquez sur la carte ou sur une ligne du classement.</p></div>

    <h2>Classement (20 premières)</h2>
    <div id="classement"></div>
  `;

  const $ = <T extends HTMLElement>(sel: string) => root.querySelector(sel) as T;
  $<HTMLSelectElement>("#mode").value = etat.mode;

  // ---- legende ----
  const classes = libellesClasses();
  $("#legende").innerHTML =
    RAMPE.map((c, k) => `<span><i style="background:${c}"></i>${esc(classes[k])}</span>`).join("") +
    `<span><i style="background:${SANS_DONNEE}"></i>sans donnée</span>`;

  // ---- fiche ----
  let cleSeuils = "";
  let seuils: Seuils = SEUILS_DEFAUT;
  const seuilsCourants = () => {
    const k = JSON.stringify(etat.poids);
    if (k !== cleSeuils) { seuils = seuilsRelatifs(table, etat.poids); cleSeuils = k; }
    return seuils;
  };
  function fiche() {
    const el = $("#fiche");
    const l = selection ? index.get(selection) : undefined;
    if (!l) {
      el.innerHTML = `<p class="desc">Cliquez sur la carte ou sur une ligne du classement.</p>`;
      return;
    }
    const u = scoreAxe(l, "usage", etat.poids);
    const f = scoreAxe(l, "faisabilite", etat.poids);
    const d = scoreAxe(l, "deficit", etat.poids);
    const g = scoreMode(l, "global", etat.poids);
    const barre = (label: string, v: number | null) => `
      <div class="barre"><span>${esc(label)}</span>
        <span class="rail">${v === null ? "" : `<b style="width:${Math.max(0, Math.min(100, v))}%"></b>`}</span>
        <span class="val ${v === null ? "nd" : ""}">${fmt(v)}</span></div>`;
    el.innerHTML = `<div class="fiche">
      <h3>${esc(l.nom)}</h3>
      <div class="desc">Code ${esc(l.code)}${l.dep ? " · dép. " + esc(l.dep) : ""}${typeof l.grille === "number" ? " · grille densité " + l.grille : ""}</div>
      <p class="profil">${esc(profil(u, f, d, seuilsCourants()))}</p>
      ${barre("Priorité globale", g)}${barre("Usage", u)}${barre("Faisabilité", f)}${barre("Déficit", d)}
      <h2 style="margin-top:12px">Indicateurs</h2>
      ${INDICATEURS.map((i) => barre(i.label, typeof l[i.id] === "number" ? (l[i.id] as number) : null)).join("")}
    </div>`;
  }

  // ---- classement ----
  function classement() {
    const lignes = table
      .filter((l) => !etat.rural || estRural(l))
      .map((l) => ({ l, s: scoreMode(l, etat.mode, etat.poids) }))
      .filter((x) => x.s !== null)
      .sort((a, b) => (b.s as number) - (a.s as number))
      .slice(0, 20);
    $("#classement").innerHTML = lignes.length === 0
      ? `<p class="desc">Aucune commune évaluable avec ces réglages.</p>`
      : `<table><thead><tr><th>#</th><th>Commune</th><th class="num">Score</th></tr></thead><tbody>${lignes
          .map((x, k) => `<tr class="cliquable" data-code="${esc(x.l.code)}" tabindex="0"><td>${k + 1}</td><td>${esc(x.l.nom)}</td><td class="num">${fmt(x.s)}</td></tr>`)
          .join("")}</tbody></table>`;
  }

  let minuterie = 0;
  const rafraichirLourd = () => {
    window.clearTimeout(minuterie);
    minuterie = window.setTimeout(() => { classement(); fiche(); }, 150);
  };

  // ---- evenements ----
  $<HTMLSelectElement>("#mode").addEventListener("change", (e) => {
    etat.mode = (e.target as HTMLSelectElement).value as Mode;
    rappels.onChange();
    rafraichirLourd();
  });
  $<HTMLInputElement>("#rural").addEventListener("change", (e) => {
    etat.rural = (e.target as HTMLInputElement).checked;
    rappels.onChange();
    rafraichirLourd();
  });
  root.addEventListener("input", (e) => {
    const t = e.target as HTMLInputElement;
    if (t.type !== "range") return;
    const id = t.dataset.id!;
    const v = Number(t.value);
    if (id.startsWith("axe_")) etat.poids.axes[id.slice(4) as keyof Poids["axes"]] = v;
    else etat.poids.indicateurs[id] = v;
    $(`#o_${id}`).textContent = String(v);
    rappels.onChange();
    rafraichirLourd();
  });
  $("#reset").addEventListener("click", () => {
    const p = poidsParDefaut();
    etat.poids.axes = p.axes;
    etat.poids.indicateurs = p.indicateurs;
    root.querySelectorAll<HTMLInputElement>("input[type=range]").forEach((r) => {
      const id = r.dataset.id!;
      const v = id.startsWith("axe_") ? p.axes[id.slice(4) as keyof Poids["axes"]] : p.indicateurs[id];
      r.value = String(v);
      $(`#o_${id}`).textContent = String(v);
    });
    rappels.onChange();
    rafraichirLourd();
  });
  const choisir = (e: Event) => {
    const tr = (e.target as HTMLElement).closest("tr[data-code]") as HTMLElement | null;
    if (tr) rappels.onSelection(tr.dataset.code!);
  };
  $("#classement").addEventListener("click", choisir);
  $("#classement").addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") choisir(e); });

  classement();

  return {
    selectionner(code: string | null) {
      selection = code;
      fiche();
    },
    ligne: (code: string) => index.get(code),
  };
}
