// Genere un jeu de DEMONSTRATION synthetique (grille 0.2 deg sur la forme approximative de la France).
// Ce ne sont PAS des donnees reelles : uniquement pour tester l'interface.
import { writeFileSync } from "node:fs";

const FRANCE = [[-4.8,48.4],[-1.5,48.7],[-1.2,49.7],[1.5,50.1],[2.5,51.0],[4.2,50.0],[6.2,49.5],[8.2,48.9],[7.6,47.6],[6.9,47.0],[6.1,46.2],[7.0,45.9],[7.1,44.3],[7.7,43.8],[6.5,43.1],[3.1,43.0],[3.0,42.4],[0.7,42.8],[-1.8,43.4],[-1.2,45.3],[-1.2,46.2],[-2.2,47.1],[-4.4,47.8]];
function dans(pt, poly) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (yi > pt[1] !== yj > pt[1] && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}
let s = 42;
const rnd = () => ((s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296);
const bruit = (x, y, k) => 0.5 + 0.25 * Math.sin(x * 0.9 + k) + 0.25 * Math.cos(y * 1.3 - k * 1.7);
const clip = (v) => Math.max(0, Math.min(100, Math.round(v)));

const PAS = 0.2;
const features = [];
let n = 0;
for (let lon = -4.8; lon < 8.2; lon += PAS) {
  for (let lat = 42.4; lat < 51.0; lat += PAS) {
    const c = [lon + PAS / 2, lat + PAS / 2];
    if (!dans(c, FRANCE)) continue;
    n++;
    const urb = bruit(c[0] * 2.1, c[1] * 1.7, 3);
    const grille = Math.max(1, Math.min(7, Math.round(7 - urb * 5 + (rnd() - 0.5) * 2)));
    const rural = grille >= 5 ? 1 : 0;
    const p = { code: "D" + String(n).padStart(5, "0"), nom: "Cellule démo " + n, dep: String(Math.floor(c[0] + 5)), grille };
    const defs = {
      i_gisement: bruit(c[0], c[1], 1) * 70 + rnd() * 30,
      i_emploi_local: urb * 60 + rnd() * 40,
      i_compacite: (1 - rural) * 50 + rnd() * 50,
      i_peu_motorises: urb * 50 + rnd() * 50,
      i_relief: bruit(c[0] * 1.5, c[1], 5) * 80 + rnd() * 20,
      i_climat: bruit(c[0], c[1] * 0.8, 7) * 80 + rnd() * 20,
      i_routes_calmes: (rural ? 60 : 30) + rnd() * 40,
      i_intermodalite: urb * 60 + rnd() * 40,
      i_emprises_ferrees: rnd() > 0.85 ? 20 + rnd() * 80 : 0,   // 'presence' : la plupart des communes n'ont rien
      i_canaux: rnd() > 0.93 ? 20 + rnd() * 80 : 0,
      i_covoiturage: rnd() > 0.7 ? 20 + rnd() * 80 : 0,
      i_securite: bruit(c[0] * 0.7, c[1], 9) * 60 + rnd() * 40,
      i_deficit_lineaire: (1 - urb) * 60 + rnd() * 40,
      i_deficit_stationnement: (1 - urb) * 50 + rnd() * 50,
    };
    for (const [k, v] of Object.entries(defs)) if (rnd() > 0.04) p[k] = clip(v); // ~4 % de valeurs manquantes
    features.push({
      type: "Feature",
      properties: p,
      geometry: { type: "Polygon", coordinates: [[[lon, lat], [lon + PAS, lat], [lon + PAS, lat + PAS], [lon, lat + PAS], [lon, lat]].map(([x, y]) => [+x.toFixed(3), +y.toFixed(3)])] },
    });
  }
}
writeFileSync("public/data/demo.geojson", JSON.stringify({ type: "FeatureCollection", features }));
writeFileSync("public/config.json", JSON.stringify({ demo: true, source: { type: "geojson", url: "data/demo.geojson" } }, null, 2));
console.log(features.length + " cellules de demonstration");
