"""Etape 3 : joint contours + indicateurs, ecrit geojson / json / config pour l'application."""
import json
import time

import geopandas as gpd
import pandas as pd
import requests
import shapely

import config as cfg
from outils import api_get, log, trouver_col  # noqa: F401


def contours_geoapi():
    cache = cfg.DOSSIER_BRUT / "contours_geoapi_v2.parquet"
    if cache.exists():
        log("contours : lecture du cache")
        return gpd.read_parquet(cache)
    g = _telecharger_contours()
    cfg.DOSSIER_BRUT.mkdir(exist_ok=True)
    g.to_parquet(cache)
    return g


def _telecharger_contours():
    deps = [f"{i:02d}" for i in list(range(1, 20)) + list(range(21, 96))] + ["2A", "2B"]
    morceaux = []
    for d in deps:
        u = "https://geo.api.gouv.fr/communes"
        for essai in range(1, 7):  # geo.api.gouv.fr coupe parfois la connexion depuis les runners GitHub
            try:
                j = requests.get(u, params=dict(codeDepartement=d, fields="nom,code,codeDepartement,population", format="geojson", geometry="contour"), timeout=120)
                j.raise_for_status()
                break
            except requests.RequestException as e:
                log(f"  departement {d} : essai {essai}/6 echoue ({type(e).__name__})")
                if essai == 6:
                    raise
                time.sleep(5 * essai)
        g = gpd.GeoDataFrame.from_features(j.json()["features"], crs=4326)
        morceaux.append(g.rename(columns={"codeDepartement": "dep", "population": "pop"}))
        log(f"  departement {d} : {len(g)} communes")
    return pd.concat(morceaux, ignore_index=True)


def charger_communes():
    if cfg.CHEMIN_COMMUNES:
        g = gpd.read_file(cfg.CHEMIN_COMMUNES)
        g.columns = [c.lower() if c != "geometry" else c for c in g.columns]
        cc = trouver_col(g, r"^(insee_com|code|codgeo|code_insee)$", "code commune")
        cn = trouver_col(g, r"^(nom|nom_com|libgeo|nom_officiel)", "nom")
        g = g.rename(columns={cc: "code", cn: "nom"})[["code", "nom", "geometry"]].to_crs(4326)
        g["dep"] = g["code"].str[:3].where(g["code"].str[:2].isin(["97", "98"]), g["code"].str[:2])
        return g.assign(pop=float("nan"))  # pas de population dans un fichier de contours local
    return contours_geoapi()


def simplifier(g, tol):
    """Simplification topologique (pas de trous entre communes voisines) si possible."""
    try:
        g = g.copy()
        g["geometry"] = shapely.coverage_simplify(g.geometry.values, tol)
    except Exception as e:  # noqa: BLE001
        log(f"coverage_simplify indisponible ({e}) : simplification classique")
        g = g.copy()
        g["geometry"] = g.geometry.simplify(tol, preserve_topology=True)
    return g


def exporter(communes, indic, sortie, fichier_config, tol=cfg.SIMPLIFICATION_DEG):
    communes = communes[["code", "nom", "dep", "geometry"]].copy()
    communes["code"] = communes["code"].astype(str)
    carte = simplifier(communes, tol).merge(indic, on="code", how="left")
    sortie.mkdir(parents=True, exist_ok=True)
    f_geo = sortie / "communes.geojson"
    f_geo.unlink(missing_ok=True)
    carte.to_file(f_geo, driver="GeoJSON", COORDINATE_PRECISION=5)
    # table des indicateurs (classement, fiche) : NaN -> null
    tab = pd.DataFrame(carte.drop(columns="geometry"))
    (sortie / "indicateurs.json").write_text(tab.to_json(orient="records", force_ascii=False), encoding="utf-8")
    fichier_config.write_text(json.dumps({"demo": False, "source": {"type": "geojson", "url": "data/communes.geojson"}}, indent=2), encoding="utf-8")
    log(f"ecrit {f_geo} ({f_geo.stat().st_size / 1e6:.1f} Mo, {len(carte)} communes)")
    return f_geo


def main():
    indic = pd.read_parquet(cfg.DOSSIER_BRUT / "indicateurs_communes.parquet")
    exporter(charger_communes(), indic, cfg.DOSSIER_SORTIE, cfg.FICHIER_CONFIG_APP)


if __name__ == "__main__":
    main()
