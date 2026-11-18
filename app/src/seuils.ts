import "./resultats.css";
import { AXES, GRILLE_RURAL_MIN, INDICATEURS } from "./indicators";
import { SEUIL_FAISABILITE, SEUIL_USAGE, SEUILS } from "./score";

interface Item { nom: string; valeur: string; unite: string; role: string; fichier: string }
interface Section { titre: string; intro: string; items: Item[] }

const esc = (s: unknown) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));

const table = (lignes: string[][], entetes: string[]) => `
  <table class="seuils"><thead><tr>${entetes.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
  <tbody>${lignes.map((l) => `<tr>${l.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;

// seuils du score et de la carte : lus directement dans le code de l'application
function sectionScore(): string {
  const bornes = [0, ...SEUILS];
  const classes = bornes.map((b, k) => (k === 0 ? `< ${SEUILS[0]}` : k === bornes.length - 1 ? `≥ ${b}` : `${b} à ${bornes[k + 1]}`));
  return `
    <h2>Score et carte</h2>
    <p class="desc">Chaque indicateur est un rang percentile national (0 à 100, 100 = situation favorable). Un indicateur absent est ignoré dans la moyenne pondérée.</p>
    ${table(AXES.map((a) => [a.label, String(a.poids), a.description]), ["Axe", "Poids par défaut", "Rôle"])}
    ${table(INDICATEURS.map((i) => [i.label, AXES.find((a) => a.id === i.axe)!.label, String(i.poids), i.source]), ["Indicateur", "Axe", "Poids par défaut", "Source"])}
    ${table([
      ["Classes de couleur de la carte", classes.join(" · ")],
      ["Communes rurales", `grille de densité INSEE ≥ ${GRILLE_RURAL_MIN} (5 à 7)`],
      ["Profil : usage « fort »", `≥ ${SEUIL_USAGE} par défaut, ou tiers supérieur des communes rurales`],
      ["Profil : faisabilité « facile »", `≥ ${SEUIL_FAISABILITE} par défaut, ou tiers supérieur des communes rurales`],
      ["Profil : déficit « fort »", "≥ 50 par défaut, ou moitié supérieure des communes rurales"],
    ], ["Seuil", "Valeur"])}`;
}

function sectionPipeline(s: Section): string {
  return `
    <h2>${esc(s.titre)}</h2>
    <p class="desc">${esc(s.intro)}</p>
    ${table(s.items.map((i) => [i.nom, `${i.valeur}${i.unite ? " " + i.unite : ""}`, i.role, i.fichier]), ["Seuil", "Valeur", "Rôle", "Fichier"])}`;
}

async function main() {
  const racine = document.getElementById("page")!;
  let sections: Section[] = [];
  let erreur = "";
  try {
    const r = await fetch("./data/seuils.json", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    sections = await r.json();
  } catch (e) {
    erreur = `Les seuils du pipeline n'ont pas pu être chargés (${e instanceof Error ? e.message : e}).`;
  }
  racine.innerHTML = `
    <header>
      <div><h1>Seuils retenus</h1>
        <p class="sous">Tous les paramètres chiffrés du score et des tracés d'exemple. Ce sont des choix de conception, pas des normes : ils sont à discuter et à ajuster. Les valeurs sont lues dans le code à chaque déploiement.</p></div>
      <span><a href="./index.html">Carte →</a> · <a href="./resultats.html">Classement →</a></span>
    </header>
    ${sectionScore()}
    ${erreur ? `<div class="bandeau">${esc(erreur)}</div>` : sections.map(sectionPipeline).join("")}`;
}

main();
