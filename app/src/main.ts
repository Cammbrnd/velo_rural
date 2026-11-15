import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import { Protocol } from "pmtiles";
import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import { chargerConfig, chargerDonnees } from "./data";
import { GRILLE_RURAL_MIN } from "./indicators";
import { monterPanneau, type Etat } from "./panel";
import { exprCouleur, poidsParDefaut, scoreMode, type Ligne } from "./score";

// Plan IGN (Geoplateforme). Surchargeable via "fond" dans config.json.
const FOND_IGN =
  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&FORMAT=image/png&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}";

maplibregl.setWorkerUrl(new URL(import.meta.env.BASE_URL + "maplibre/maplibre-gl-worker.mjs", window.location.href).href);

async function demarrer() {
  const panneau = document.getElementById("panneau")!;
  const cfg = await chargerConfig();
  const { geojson, table } = await chargerDonnees(cfg);

  const etat: Etat = { mode: "global", rural: true, poids: poidsParDefaut() };

  const protocole = new Protocol();
  maplibregl.addProtocol("pmtiles", protocole.tile);

  const style: StyleSpecification = {
    version: 8,
    sources: { fond: { type: "raster", tiles: [cfg.fond ?? FOND_IGN], tileSize: 256, attribution: "© IGN – Géoplateforme" } },
    layers: [{ id: "fond", type: "raster", source: "fond", paint: { "raster-saturation": -0.6, "raster-opacity": 0.9 } }],
  };
  const carte = new maplibregl.Map({ container: "carte", style, center: [2.6, 46.6], zoom: 5.3, minZoom: 4, maxZoom: 14 });
  carte.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  carte.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

  const infobulle = document.createElement("div");
  infobulle.className = "infobulle";
  document.getElementById("carte")!.appendChild(infobulle);

  const couche = cfg.source.type === "pmtiles" ? { "source-layer": cfg.source.couche ?? "communes" } : {};
  const filtreRural = () => (etat.rural ? ([">=", ["to-number", ["get", "grille"], 0], GRILLE_RURAL_MIN] as never) : null);

  function recolorer() {
    carte.setPaintProperty("communes-fill", "fill-color", exprCouleur(etat.mode, etat.poids));
    carte.setFilter("communes-fill", filtreRural());
    carte.setFilter("communes-trait", filtreRural());
  }

  const ui = monterPanneau(panneau, cfg, table, etat, {
    onChange: () => recolorer(),
    onSelection: (code) => {
      ui.selectionner(code);
      carte.setFilter("communes-sel", ["==", ["get", "code"], code ?? ""] as never);
    },
  });

  carte.on("load", () => {
    if (cfg.source.type === "geojson") {
      carte.addSource("communes", { type: "geojson", data: geojson as GeoJSON.FeatureCollection });
    } else {
      // URL absolue : indispensable sous un sous-chemin (ex. GitHub Pages /depot/)
      carte.addSource("communes", { type: "vector", url: "pmtiles://" + new URL(cfg.source.url, window.location.href).href });
    }
    carte.addLayer({
      id: "communes-fill", type: "fill", source: "communes", ...couche,
      paint: { "fill-color": exprCouleur(etat.mode, etat.poids), "fill-opacity": 0.78 },
    } as never);
    carte.addLayer({
      id: "communes-trait", type: "line", source: "communes", ...couche,
      paint: { "line-color": "#fcfcfb", "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.1, 10, 0.8], "line-opacity": 0.8 },
    } as never);
    carte.addLayer({
      id: "communes-sel", type: "line", source: "communes", ...couche, filter: ["==", ["get", "code"], ""],
      paint: { "line-color": "#0b0b0b", "line-width": 2.5 },
    } as never);
    recolorer();
  });

  // infobulle au survol
  carte.on("mousemove", "communes-fill", (e) => {
    const f = e.features?.[0];
    if (!f) return;
    const p = f.properties as Ligne;
    const s = scoreMode(p, etat.mode, etat.poids);
    infobulle.innerHTML = `<b></b><span></span>`;
    infobulle.querySelector("b")!.textContent = String(p.nom ?? p.code);
    infobulle.querySelector("span")!.textContent = s === null ? "score indisponible" : `score ${Math.round(s)} / 100`;
    infobulle.style.left = e.point.x + "px";
    infobulle.style.top = e.point.y + "px";
    infobulle.style.display = "block";
    carte.getCanvas().style.cursor = "pointer";
  });
  carte.on("mouseleave", "communes-fill", () => {
    infobulle.style.display = "none";
    carte.getCanvas().style.cursor = "";
  });
  // clic : fiche commune
  carte.on("click", "communes-fill", (e) => {
    const code = e.features?.[0]?.properties?.code as string | undefined;
    if (!code) return;
    ui.selectionner(code);
    carte.setFilter("communes-sel", ["==", ["get", "code"], code] as never);
  });
}

demarrer().catch((err) => {
  document.getElementById("panneau")!.innerHTML = `<p class="erreur">Erreur : ${String(err.message ?? err)}</p>`;
  console.error(err);
});
