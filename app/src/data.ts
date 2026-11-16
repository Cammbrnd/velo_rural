import type { Ligne } from "./score";

export interface Config {
  demo: boolean;
  source: { type: "geojson" | "pmtiles"; url: string; couche?: string };
  table?: string; // JSON [ {code, nom, grille, i_*...}, ... ] (obligatoire avec pmtiles)
  exemples?: string; // GeoJSON des traces d'exemple (pole + traces par EPCI)
  fond?: string; // gabarit de tuiles raster {z}/{x}/{y} (par defaut : Plan IGN)
}

const base = import.meta.env.BASE_URL;

export async function chargerConfig(): Promise<Config> {
  const r = await fetch(base + "config.json");
  if (!r.ok) throw new Error("config.json introuvable");
  return r.json();
}

export interface Donnees {
  geojson: GeoJSON.FeatureCollection | null;
  table: Ligne[];
}

export async function chargerDonnees(cfg: Config): Promise<Donnees> {
  if (cfg.source.type === "geojson") {
    const r = await fetch(base + cfg.source.url);
    if (!r.ok) throw new Error("GeoJSON introuvable : " + cfg.source.url);
    const geojson = (await r.json()) as GeoJSON.FeatureCollection;
    return { geojson, table: geojson.features.map((f) => (f.properties ?? {}) as Ligne) };
  }
  if (!cfg.table) throw new Error("Avec PMTiles, 'table' (JSON des indicateurs) est obligatoire dans config.json");
  const r = await fetch(base + cfg.table);
  if (!r.ok) throw new Error("Table introuvable : " + cfg.table);
  return { geojson: null, table: (await r.json()) as Ligne[] };
}

// part de communes renseignees pour chaque indicateur (affichee dans le panneau)
export function couverture(table: Ligne[], ids: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const id of ids) {
    let n = 0;
    for (const l of table) if (typeof l[id] === "number") n++;
    out[id] = table.length ? n / table.length : 0;
  }
  return out;
}

export async function chargerExemples(cfg: Config): Promise<GeoJSON.FeatureCollection | null> {
  if (!cfg.exemples) return null;
  try {
    const r = await fetch(base + cfg.exemples);
    return r.ok ? ((await r.json()) as GeoJSON.FeatureCollection) : null;
  } catch {
    return null; // couche facultative : l'application fonctionne sans
  }
}
