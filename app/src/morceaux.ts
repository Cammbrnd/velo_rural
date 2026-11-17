// PMTiles servi en morceaux de 1 Mo (fichiers entiers, sans requete HTTP Range).
// Raison : GitHub Pages + Firefox = "Decoding failed" (NS_ERROR_INVALID_CONTENT_ENCODING) sur les reponses 206 compressees.
import { PMTiles, type Protocol, type RangeResponse, type Source } from "pmtiles";

export class SourceMorceaux implements Source {
  private cache = new Map<number, Promise<Uint8Array>>();
  constructor(private base: string, private suffixe: string, private taille: number, private morceau: number) {}

  getKey(): string {
    return this.base;
  }

  private charger(i: number, essai = 1): Promise<Uint8Array> {
    let p = this.cache.get(i);
    if (!p) {
      p = fetch(`${this.base}/${String(i).padStart(4, "0")}.bin${this.suffixe}`)
        .then((r) => {
          if (!r.ok) throw new Error(`morceau ${i} : HTTP ${r.status}`);
          return r.arrayBuffer();
        })
        .then((b) => new Uint8Array(b));
      this.cache.set(i, p);
      p.catch(() => this.cache.delete(i)); // un echec n'est pas garde : le prochain appel retente
    }
    return p.catch((e) => {
      if (essai >= 3) throw e;
      return this.charger(i, essai + 1);
    });
  }

  async getBytes(offset: number, length: number): Promise<RangeResponse> {
    const fin = Math.min(offset + length, this.taille);
    const sortie = new Uint8Array(Math.max(0, fin - offset));
    for (let i = Math.floor(offset / this.morceau); i * this.morceau < fin; i++) {
      const m = await this.charger(i);
      const debut = Math.max(offset, i * this.morceau);
      const part = m.subarray(debut - i * this.morceau, Math.min(fin, (i + 1) * this.morceau) - i * this.morceau);
      sortie.set(part, debut - offset);
    }
    return { data: sortie.buffer as ArrayBuffer };
  }
}

/** Enregistre l'archive dans le protocole ; renvoie l'URL "pmtiles://..." a donner a MapLibre.
 *  `url` : dossier des morceaux (ex. "data/communes?v=123") ; un `.pmtiles` direct reste accepte (serveur avec Range). */
export async function monterPmtiles(protocole: Protocol, url: string): Promise<string> {
  const abs = new URL(url, window.location.href);
  if (abs.pathname.endsWith(".pmtiles")) return "pmtiles://" + abs.href;
  const suffixe = abs.search;
  abs.search = "";
  const base = abs.href.replace(/\/$/, "");
  const r = await fetch(`${base}/meta.json${suffixe}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`pmtiles ${base} : meta.json introuvable (HTTP ${r.status})`);
  const meta = (await r.json()) as { taille: number; morceau: number };
  protocole.add(new PMTiles(new SourceMorceaux(base, suffixe, meta.taille, meta.morceau)));
  return "pmtiles://" + base;
}
