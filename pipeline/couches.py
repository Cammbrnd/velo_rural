"""Couches geographiques (lignes / points) agregees par commune : lignes SNCF desaffectees, canaux,
aires de covoiturage, BNAC (amenagements cyclables), stationnements velo OSM.

Chaque couche = une entree de config.COUCHES ; une couche en echec est ignoree (comme les indicateurs TBMD).
"""
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

import config as cfg
from outils import (choisir_ressource, lire_csv, log, percentile, percentile_presence, rechercher_datasets,
                    telecharger, trouver_col, vers_nombre)

CRS_METRIQUE = 2154  # Lambert-93 (metropole)
FORMATS_GEO = ("geojson", "json", "gpkg", "zip", "shp", "csv")


# ---------------------------------------------------------------- recherche / telechargement
def resoudre_url(c):
    """URL de la couche : url explicite > dataset_id > recherche plein texte (premier jeu au bon titre)."""
    if c.get("url"):
        return c["url"], c["url"].rsplit("/", 1)[-1]
    formats = c.get("formats", FORMATS_GEO)
    if c.get("dataset_id"):
        r = choisir_ressource(c["dataset_id"], c.get("ressource"), formats, c.get("plus_grosse", False))
        return r["url"], r["titre"]
    for d in rechercher_datasets(c["recherche"], n=10):
        if not re.search(c.get("titre", c["recherche"]), d["titre"], re.I):
            continue
        rs = [r for r in d["ressources"] if r["format"] in formats and r["url"]]
        if c.get("ressource"):
            rs = [r for r in rs if re.search(c["ressource"], r["titre"] or "", re.I)]
        if rs:
            log(f"  jeu retenu : {d['titre']} ({d['org']}) / {rs[0]['titre']}")
            return rs[0]["url"], rs[0]["titre"]
    raise RuntimeError(f"aucun jeu data.gouv ne correspond a '{c['recherche']}' : fournir `url` dans config.COUCHES")


def extension(url, titre):
    for s in (url.split("?")[0], titre or ""):
        m = re.search(r"\.(geojson|json|gpkg|zip|shp|csv)(\.gz)?$", s.lower())
        if m:
            return m.group(1)
    return "geojson" if "geojson" in url.lower() else "csv"


# ---------------------------------------------------------------- lecture
def lire_points_csv(chemin, c):
    """CSV a coordonnees (lon/lat) -> GeoDataFrame WGS84 ; conserve la colonne code commune si elle existe."""
    df = lire_csv(chemin)
    try:
        col_x = trouver_col(df, c.get("col_lon", r"^(xlong|x_?long|lon|longitude|x)$"), "longitude")
        col_y = trouver_col(df, c.get("col_lat", r"^(ylat|y_?lat|lat|latitude|y)$"), "latitude")
        x, y = vers_nombre(df[col_x]), vers_nombre(df[col_y])
    except KeyError:  # schema stationnement cyclable : une seule colonne "lon,lat"
        xy = df[trouver_col(df, r"coordonnees.?xy|geo_?point", "coordonneesxy")].astype(str).str.extract(
            r"(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)")
        x, y = vers_nombre(xy[0]), vers_nombre(xy[1])
    ok = x.between(-6, 10) & y.between(41, 52)  # metropole
    df = df[ok]
    g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(x[ok], y[ok]), crs=4326)
    return g


def lire_couche(chemin, c, ext):
    if ext == "zip":  # on extrait le premier fichier geo/csv de l'archive (GDAL ne lit pas toujours les zip a sous-dossiers)
        import zipfile
        with zipfile.ZipFile(chemin) as z:
            noms = [n for n in z.namelist() if re.search(r"\.(geojson|json|gpkg|shp|csv)$", n, re.I) and not n.endswith("/")]
            if not noms:
                raise RuntimeError(f"aucun fichier geo/csv dans l'archive : {z.namelist()[:10]}")
            log(f"  archive : lecture de {noms[0]}")
            chemin = Path(z.extract(noms[0], Path(chemin).parent / (Path(chemin).stem + "_extrait")))
        ext = chemin.suffix.lower().lstrip(".")
    if ext == "csv":
        return lire_points_csv(chemin, c)
    g = gpd.read_file(chemin)
    if g.crs is None:
        g = g.set_crs(4326)
    return g.to_crs(4326)


def filtrer(g, filtre):
    if not filtre:
        return g
    col = trouver_col(g.drop(columns="geometry"), filtre[0], "filtre")
    return g[g[col].astype(str).str.contains(filtre[1], case=False, regex=True, na=False)]


# ---------------------------------------------------------------- agregation par commune
def longueur_par_commune(lignes, communes):
    """Longueur (km) de lignes dans chaque commune : decoupe exacte des lignes par les contours."""
    l = lignes[~lignes.geometry.is_empty & lignes.geometry.notna()].to_crs(CRS_METRIQUE).reset_index(drop=True)[["geometry"]]
    c = communes[["code", "geometry"]].to_crs(CRS_METRIQUE).reset_index(drop=True)
    if l.empty:
        return pd.Series(dtype=float)
    paires = gpd.sjoin(l, c, how="inner", predicate="intersects")
    morceaux = shapely.intersection(paires.geometry.values, c.geometry.values[paires["index_right"].values])
    km = pd.Series(shapely.length(morceaux) / 1000.0, index=c["code"].values[paires["index_right"].values])
    return km.groupby(level=0).sum()


def compter_par_commune(points, communes, col_code=None):
    """Nombre de points par commune : via la colonne code commune si elle est fiable, sinon jointure spatiale."""
    if col_code and col_code in points.columns:
        codes = points[col_code].astype(str).str.strip().str.zfill(5)
        part_valides = codes.isin(set(communes["code"])).mean()
        if part_valides > 0.8:
            return codes.value_counts()
        log(f"  colonne '{col_code}' peu fiable ({part_valides:.0%} de codes connus) : jointure spatiale")
    c = communes[["code", "geometry"]].reset_index(drop=True)
    j = gpd.sjoin(points[["geometry"]].reset_index(drop=True), c, how="inner", predicate="within")
    return j["code"].value_counts()


def superficie_km2(communes):
    return pd.Series(communes.to_crs(CRS_METRIQUE).area.values / 1e6, index=communes["code"].values)


# ---------------------------------------------------------------- une couche -> un indicateur
def indicateur_couche(nom, c, communes, dossier):
    """Retourne (serie_indicateur_0_100 indexee par code, detail)."""
    url, titre = resoudre_url(c)
    ext = c.get("ext") or extension(url, titre)
    f = telecharger(url, dossier / f"couche_{nom}.{ext}")
    g = filtrer(lire_couche(f, c, ext), c.get("filtre"))
    if g.empty:
        raise RuntimeError("aucun objet apres filtrage (voir config.COUCHES[...]['filtre'])")
    if c["mode"] == "longueur":
        brut = longueur_par_commune(g, communes)
        unite = "km"
    else:
        brut = compter_par_commune(g, communes, c.get("col_code"))
        unite = "objets"
    brut = brut.reindex(communes["code"].values).fillna(0.0)
    brut.index = communes["code"].values
    if c.get("par_habitant"):
        pop = pd.Series(communes["pop"].values, index=communes["code"].values).clip(lower=c.get("pop_min", 200))
        brut = brut / (pop / 1000.0)
        unite += "/1000 hab"
    s = percentile_presence(brut) if c["transfo"] == "presence" else percentile(-brut if c["transfo"] == "bas" else brut)
    return s.rename(nom), f"{len(g)} objets lus, {int((brut > 0).sum())} communes concernees, total {brut.sum():.0f} {unite}"


def construire_couches(couches, communes, dossier):
    """Calcule toutes les couches disponibles ; retourne (table [code + indicateurs], rapport)."""
    series, rapport = [], []
    for nom, c in couches.items():
        try:
            log(f"couche {nom}")
            s, detail = indicateur_couche(nom, c, communes, dossier)
            series.append(s)
            rapport.append((nom, "ok", detail))
        except Exception as e:  # noqa: BLE001
            log(f"[!] {nom} ignore : {e}")
            rapport.append((nom, "IGNORE", str(e)[:300]))
    if not series:
        return pd.DataFrame({"code": []}), rapport
    table = pd.concat(series, axis=1)
    table.index.name = "code"
    return table.reset_index(), rapport


def fusionner(table, couches_table):
    """Ajoute les indicateurs-couches ; une couche remplace la colonne TBMD du meme nom lorsqu'elle est renseignee."""
    if couches_table.empty:
        return table
    ct = couches_table.set_index("code")
    t = table.set_index("code")
    for col in ct.columns:
        t[col] = ct[col].reindex(t.index).combine_first(t[col]) if col in t.columns else ct[col].reindex(t.index)
    nouveaux = ct.index.difference(t.index)
    if len(nouveaux):
        t = pd.concat([t, ct.loc[nouveaux, [c for c in ct.columns]]])
    return t.reset_index()
