import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import { Protocol } from "pmtiles";
import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import { chargerConfig, chargerDonnees, chargerExemples } from "./data";
import { GRILLE_RURAL_MIN } from "./indicators";
import { monterPanneau, type Etat } from "./panel";
import { exprCouleur, poidsParDefaut, scoreMode, type Ligne } from "./score";

// Plan IGN (Geoplateforme). Surchargeable via "fond" dans config.json.
const FOND_IGN =
  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&FORMAT=image/png&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}";

maplibregl.setWorkerUrl(new URL(import.meta.env.BASE_URL + "maplibre/maplibre-gl-worker.mjs", window.location.href).href);

// URL absolue d'un PMTiles + marque propre a ce chargement : un navigateur de bureau qui garde en cache d'anciens octets
// (requetes Range d'un fichier remplace depuis) ne peut plus les melanger avec le nouveau fichier ("Decoding failed")
const urlPmtiles = (u: string) => {
  const url = new URL(u, window.location.href);
  url.searchParams.set("s", String(Date.now()));
  return "pmtiles://" + url.href;
};

async function demarrer() {
  const panneau = document.getElementById("panneau")!;
  const cfg = await chargerConfig();
  const { geojson, table } = await chargerDonnees(cfg);
  const exemples = await chargerExemples(cfg);

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

  (window as unknown as { __carte?: maplibregl.Map }).__carte = carte; // test navigateur (voir scripts/smoke.py)

  // alerte visible si les donnees communales ne se chargent pas (sinon la couche manque sans explication)
  const alerte = document.createElement("div");
  alerte.className = "alerte";
  document.getElementById("carte")!.appendChild(alerte);
  carte.on("error", (e) => {
    const err = e.error as Error | undefined;
    if ((e as unknown as { sourceId?: string }).sourceId !== "communes" && !/pmtiles|communes/i.test(String(err?.message ?? ""))) return; // fond IGN : ignore
    console.error("Donnees communales :", err);
    alerte.textContent = "Les données communales n'ont pas pu être chargées (" + String(err?.message ?? err).slice(0, 160) + "). Rechargez la page (Ctrl+F5).";
    alerte.style.display = "block";
  });

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
      carte.addSource("communes", { type: "vector", url: urlPmtiles(cfg.source.url) });
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
    if (cfg.epci) {
      carte.addSource("epci", { type: "vector", url: urlPmtiles(cfg.epci) });
      carte.addLayer({ id: "epci-trait", type: "line", source: "epci", "source-layer": "epci",
        paint: { "line-color": "#0b0b0b", "line-opacity": 0.75, "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.4, 8, 1.2, 11, 2.2] } } as never);
    }
    if (cfg.pistes) {
      carte.addSource("pistes", { type: "vector", url: urlPmtiles(cfg.pistes) });
      carte.addLayer({ id: "pistes-fond", type: "line", source: "pistes", "source-layer": "pistes", minzoom: 7,
        layout: { "line-cap": "round" }, paint: { "line-color": "#ffffff", "line-opacity": 0.8, "line-width": ["interpolate", ["linear"], ["zoom"], 7, 2, 12, 5] } } as never);
      carte.addLayer({ id: "pistes-trait", type: "line", source: "pistes", "source-layer": "pistes", minzoom: 7,
        layout: { "line-cap": "round" },
        paint: { "line-color": ["match", ["get", "type"], "piste", "#7b2d8e", "#c9a3d6"], "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.8, 12, 2.6] } } as never);
    }
    recolorer();
    montrerCouches(carte);
    if (exemples && exemples.features.length) monterExemples(carte, exemples, infobulle);
  });

  // infobulle au survol
  carte.on("mousemove", "communes-fill", (e) => {
    const f = e.features?.[0];
    if (!f || surExemple) return;
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

// cases a cocher : afficher / masquer les communes, les contours d'EPCI, les pistes existantes
function montrerCouches(carte: maplibregl.Map) {
  const lier = (idCase: string, couches: string[]) => {
    const c = document.getElementById(idCase) as HTMLInputElement | null;
    const maj = () => couches.forEach((id) => carte.getLayer(id) && carte.setLayoutProperty(id, "visibility", c?.checked ? "visible" : "none"));
    c?.addEventListener("change", maj);
    maj();
  };
  lier("communes-voir", ["communes-fill", "communes-trait", "communes-sel"]);
  lier("epci-voir", ["epci-trait"]);
  lier("pistes-voir", ["pistes-fond", "pistes-trait"]);
}

let surExemple = false; // vrai quand la souris est sur un trace d'exemple (son infobulle prime sur celle de la commune)

const COULEURS_CAT: Record<string, string> = { existant: "#1a9850", calme: "#f2a900", a_securiser: "#d7191c" };

function monterExemples(carte: maplibregl.Map, fc: GeoJSON.FeatureCollection, infobulle: HTMLElement) {
  carte.addSource("exemples", { type: "geojson", data: fc });
  carte.addLayer({ id: "exemples-fond", type: "line", source: "exemples", filter: ["==", ["get", "type"], "trace"],
    layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 5, 3, 11, 8] } } as never);
  carte.addLayer({ id: "exemples-trait", type: "line", source: "exemples", filter: ["==", ["get", "type"], "trace"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": ["match", ["get", "categorie"], "existant", COULEURS_CAT.existant, "calme", COULEURS_CAT.calme, COULEURS_CAT.a_securiser],
      "line-width": ["interpolate", ["linear"], ["zoom"], 5, 1.6, 11, 4.5] } } as never);
  carte.addLayer({ id: "exemples-poles", type: "circle", source: "exemples", filter: ["==", ["get", "type"], "pole"],
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 4, 11, 8], "circle-color": "#0b0b0b", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } } as never);

  const bloc = document.getElementById("exemples-bloc");
  const voir = document.getElementById("exemples-voir") as HTMLInputElement | null;
  const choix = document.getElementById("exemples-choix") as HTMLSelectElement | null;
  if (bloc) bloc.hidden = false;
  const couches = ["exemples-fond", "exemples-trait", "exemples-poles"];
  voir?.addEventListener("change", () => couches.forEach((id) => carte.setLayoutProperty(id, "visibility", voir.checked ? "visible" : "none")));

  const poles = fc.features.filter((f) => f.properties?.type === "pole");
  poles.sort((a, b) => String(a.properties?.epci_nom).localeCompare(String(b.properties?.epci_nom), "fr"));
  for (const f of poles) {
    const o = document.createElement("option");
    o.value = String(f.properties?.epci);
    o.textContent = String(f.properties?.epci_nom);
    choix?.appendChild(o);
  }
  choix?.addEventListener("change", () => {
    if (!choix.value) return;
    const b = new maplibregl.LngLatBounds();
    const etendre = (c: unknown): void => {
      if (Array.isArray(c) && typeof c[0] === "number") b.extend(c as [number, number]);
      else (c as unknown[]).forEach(etendre);
    };
    for (const f of fc.features) if (f.properties?.epci === choix.value) etendre((f.geometry as GeoJSON.LineString | GeoJSON.Point).coordinates);
    if (!b.isEmpty()) carte.fitBounds(b, { padding: 60, maxZoom: 12 });
  });

  const ligne = (el: HTMLElement, titre: string, texte: string) => {
    el.replaceChildren();
    const b = document.createElement("b");
    b.textContent = titre;
    const s = document.createElement("span");
    s.textContent = texte;
    el.append(b, s);
  };
  const survol = (e: maplibregl.MapLayerMouseEvent) => {
    const p = e.features?.[0]?.properties;
    if (!p) return;
    surExemple = true;
    if (p.type === "pole") {
      ligne(infobulle, `${p.epci_nom} — pôle : ${p.pole}`, `${p.communes_epci} communes, ${Number(p.pop_epci).toLocaleString("fr-FR")} hab., ${p.traces} tracés proposés`);
    } else {
      ligne(infobulle, `${p.epci_nom} — tracé ${p.trace} depuis ${p.pole}`,
        `${p.longueur_km} km (${p.km_existant} existants, ${p.km_calme} routes calmes, ${p.km_a_securiser} à sécuriser) · ${p.communes} communes, ${Number(p.pop_desservie).toLocaleString("fr-FR")} hab. · dénivelé + ${p.denivele_positif_m} m`);
    }
    infobulle.style.left = e.point.x + "px";
    infobulle.style.top = e.point.y + "px";
    infobulle.style.display = "block";
    carte.getCanvas().style.cursor = "pointer";
  };
  for (const id of ["exemples-trait", "exemples-poles"]) {
    carte.on("mousemove", id, survol);
    carte.on("mouseleave", id, () => {
      surExemple = false;
      infobulle.style.display = "none";
      carte.getCanvas().style.cursor = "";
    });
  }
}

demarrer().catch((err) => {
  document.getElementById("panneau")!.innerHTML = `<p class="erreur">Erreur : ${String(err.message ?? err)}</p>`;
  console.error(err);
});
