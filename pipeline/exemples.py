"""Exemples de trace d'amenagement pour quelques EPCI repartis sur le territoire.

Pour chaque EPCI retenu :
  1. reseau routier/cyclable OSM (extraits Geofabrik decoupes par osmium ; repli : Overpass) ; chaque voie est classee existant / calme / a securiser ;
  2. plus courts chemins depuis le pole (commune la plus peuplee), cout = longueur x type de voie + denivele ;
  3. la demande des communes (population x score global) est agregee sur l'arbre des chemins : les axes qui concentrent
     le plus de demande (decomposition en chemins lourds) donnent les 3 traces les plus structurantes.
Ecrit exemples.geojson (traces par categorie + un point par pole).
"""
import heapq
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import LineString, Point, box, shape

import config as cfg
import relief
from outils import log, telecharger
from routes_calmes import est_calme_voie, etiquettes

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
HIGHWAYS = "residential|living_street|unclassified|tertiary|secondary|track|cycleway|path"
FACTEUR = {"existant": 0.8, "calme": 1.0, "a_securiser": 1.8}
COUT_DENIVELE = 4.0          # metres de cout par metre de denivele (|dz| entre deux noeuds)
RAYON_DESSERTE_M = 600       # une commune est desservie si son bourg est a moins de 600 m de la trace
SNAP_MAX_M = 2000
NB_TRACES = 3
LONGUEUR_MIN_M = 2500
ZOOM_MNT = 11


# ------------------------------------------------------------------ choix des EPCI
def get_json(url, params, essais=5, pause=4):
    for i in range(1, essais + 1):
        try:
            r = requests.get(url, params=params, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if i == essais:
                raise
            time.sleep(pause * i)


def table_epci():
    """code commune -> (epci, epci_nom), via geo.api.gouv.fr ; mis en cache."""
    cache = cfg.DOSSIER_BRUT / "epci_communes.csv"
    if cache.exists() and cache.stat().st_size > 0:
        return pd.read_csv(cache, dtype=str)
    noms = {e["code"]: e["nom"] for e in get_json("https://geo.api.gouv.fr/epcis", dict(fields="code,nom"))}
    deps = [f"{i:02d}" for i in list(range(1, 20)) + list(range(21, 96))] + ["2A", "2B"]
    lignes = []
    for d in deps:
        for c in get_json("https://geo.api.gouv.fr/communes", dict(codeDepartement=d, fields="code,codeEpci")):
            if c.get("codeEpci"):
                lignes.append((c["code"], c["codeEpci"], noms.get(c["codeEpci"], c["codeEpci"])))
    t = pd.DataFrame(lignes, columns=["code", "epci", "epci_nom"])
    cfg.DOSSIER_BRUT.mkdir(exist_ok=True)
    t.to_csv(cache, index=False)
    return t


def distance_km(a, b):
    """Distance approchee (km) entre deux (lon, lat)."""
    dx = (a[0] - b[0]) * 111.32 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot(dx, (a[1] - b[1]) * 110.54)


def choisir_epci(communes, n=10):
    """communes : DataFrame [code, dep, pop, epci, rural, score, lon, lat]. EPCI ruraux de taille raisonnable, repartis
    par echantillonnage du plus eloigne (un par departement) ; le premier est celui de meilleur score moyen."""
    g = communes.dropna(subset=["epci"]).groupby("epci")
    e = pd.DataFrame({
        "n": g.size(), "pop": g["pop"].sum(), "rural": g["rural"].mean(), "score": g["score"].mean(), "hub": g["pop"].max(),
        "lon": g["lon"].mean(), "lat": g["lat"].mean(), "dep": g["dep"].agg(lambda s: s.mode().iat[0]),
        "etendue": g.apply(lambda d: distance_km((d.lon.min(), d.lat.min()), (d.lon.max(), d.lat.max())), include_groups=False),
    })
    cand = e[(e.n.between(12, 60)) & (e.rural >= 0.8) & (e.etendue <= 80) & (e.hub >= 1500) & (e["pop"] >= 8000)].sort_values("score", ascending=False)
    if cand.empty:
        return []
    choix = [cand.index[0]]
    while len(choix) < min(n, len(cand)):
        pris = cand.loc[choix]
        restants = cand[~cand.index.isin(choix) & ~cand.dep.isin(pris.dep)]
        if restants.empty:
            break
        d = restants.apply(lambda r: min(distance_km((r.lon, r.lat), (p.lon, p.lat)) for p in pris.itertuples()), axis=1)
        choix.append(d.idxmax())
    return choix


# ------------------------------------------------------------------ reseau OSM
def telecharger_reseau(bbox, marge=0.03):
    """Voies OSM de l'emprise (lon min, lat min, lon max, lat max) elargie de `marge` degres -> elements Overpass (geometrie)."""
    w, s, e, n = bbox[0] - marge, bbox[1] - marge, bbox[2] + marge, bbox[3] + marge
    q = f'[out:json][timeout:240];way["highway"~"^({HIGHWAYS})$"]["access"!~"^(no|private)$"]["bicycle"!="no"]({s},{w},{n},{e});out geom;'
    derniere = None
    for essai in range(3):
        url = OVERPASS[essai % len(OVERPASS)]
        try:
            r = requests.post(url, data={"data": q}, timeout=300)
            r.raise_for_status()
            return r.json()["elements"]
        except Exception as ex:  # noqa: BLE001
            derniere = ex
            time.sleep(10 * (essai + 1))
    raise RuntimeError(f"Overpass indisponible : {derniere}")


def categorie(highway, tags):
    if tags.get("bicycle") in ("no", "dismount") or tags.get("access") in ("no", "private") or tags.get("vehicle") == "no":
        return None
    if highway == "cycleway" or (highway == "path" and tags.get("bicycle") in ("yes", "designated")):
        return "existant"
    if highway == "path":
        return None
    return "calme" if est_calme_voie(highway, tags) else "a_securiser"


def aretes_osm(elements):
    """-> coords {id: (lon, lat)}, aretes [(u, v, longueur_m, categorie)] entre noeuds OSM consecutifs."""
    coords, aretes = {}, []
    for w in elements:
        if w.get("type") != "way" or "geometry" not in w:
            continue
        tags = w.get("tags", {})
        cat = categorie(tags.get("highway", ""), tags)
        if cat is None or len(w["nodes"]) != len(w["geometry"]):
            continue
        pts = [(p["lon"], p["lat"]) for p in w["geometry"]]
        for i, nid in enumerate(w["nodes"]):
            coords[nid] = pts[i]
        for i in range(len(pts) - 1):
            aretes.append((w["nodes"][i], w["nodes"][i + 1], 1000 * distance_km(pts[i], pts[i + 1]), cat))
    return coords, aretes


def regions_france():
    """Regions Geofabrik de France metropolitaine : {id: (url pbf, polygone)} depuis l'index (avec geometries)."""
    idx = get_json("https://download.geofabrik.de/index-v1.json", None, essais=8, pause=15)
    out = {}
    for f in idx["features"]:
        p = f["properties"]
        if p.get("parent") == "france" and p.get("urls", {}).get("pbf") and not re.search(r"guadeloupe|martinique|guyane|reunion|mayotte", p["id"]):
            out[p["id"]] = (p["urls"]["pbf"], shape(f["geometry"]))
    return out


def regions_pour(emprises, regions):
    """emprises {epci: (lon min, lat min, lon max, lat max)} -> {region: [epci...]} (regions dont le polygone touche l'emprise)."""
    out = defaultdict(list)
    for epci, b in emprises.items():
        zone = box(*b)
        for nom, (_url, poly) in regions.items():
            if poly.intersects(zone):
                out[nom].append(epci)
    return out


def lignes_vers_aretes(lignes):
    """GeoDataFrame [geometry LineString, highway, other_tags] -> coords {noeud: (lon, lat)}, aretes.
    Les noeuds sont identifies par leurs coordonnees arrondies (les noeuds OSM partages coincident exactement)."""
    coords, aretes = {}, []
    for geom, hw, ot in zip(lignes.geometry, lignes["highway"], lignes["other_tags"]):
        cat = categorie(str(hw), etiquettes(ot))
        if cat is None or geom is None or geom.is_empty:
            continue
        for ligne in (geom.geoms if geom.geom_type == "MultiLineString" else [geom]):
            pts = [(round(x, 6), round(y, 6)) for x, y in ligne.coords]
            for a, b in zip(pts[:-1], pts[1:]):
                if a != b:
                    coords[a], coords[b] = a, b
                    aretes.append((a, b, 1000 * distance_km(a, b), cat))
    return coords, aretes


def extraire_reseau(pbf, bbox, tmp, nom, marge=0.03):
    """osmium : decoupe de l'emprise puis filtre des voies utiles ; lecture GDAL des lignes -> GeoDataFrame (ou None si vide)."""
    w, s_, e, n = bbox[0] - marge, bbox[1] - marge, bbox[2] + marge, bbox[3] + marge
    part, filtre = Path(tmp) / f"{nom}.part.osm.pbf", Path(tmp) / f"{nom}.voies.osm.pbf"
    subprocess.run(["osmium", "extract", "-b", f"{w},{s_},{e},{n}", str(pbf), "-o", str(part), "--overwrite"], check=True)
    subprocess.run(["osmium", "tags-filter", str(part), *[f"w/highway={h}" for h in HIGHWAYS.split("|")], "-o", str(filtre), "--overwrite"], check=True)
    sel = ",".join(f"'{h}'" for h in HIGHWAYS.split("|"))
    g = gpd.read_file(filtre, engine="pyogrio", sql=f"SELECT highway, other_tags FROM lines WHERE highway IN ({sel})")
    part.unlink(missing_ok=True)
    filtre.unlink(missing_ok=True)
    return g if len(g) else None


def reseaux_geofabrik(emprises):
    """{epci: GeoDataFrame de voies} pour toutes les emprises, region par region (un telechargement par region)."""
    regions = regions_france()
    plan = regions_pour(emprises, regions)
    log(f"  reseaux OSM : {len(plan)} regions a lire ({', '.join(sorted(plan))})")
    morceaux = defaultdict(list)
    with tempfile.TemporaryDirectory() as tmp:
        for nom, epcis in plan.items():
            pbf = telecharger(regions[nom][0], Path(tmp) / f"{nom}.osm.pbf")
            for epci in epcis:
                g = extraire_reseau(pbf, emprises[epci], tmp, f"{nom}_{epci}")
                if g is not None:
                    morceaux[epci].append(g)
            pbf.unlink()
    return {e: pd.concat(m, ignore_index=True) for e, m in morceaux.items()}


def altitudes(coords, tuile_png=relief.telecharger_tuile, z=ZOOM_MNT):
    """Altitude (m) de chaque noeud, lue dans les tuiles Terrarium ; 0 si la tuile manque."""
    ids = list(coords)
    lon = np.array([coords[i][0] for i in ids])
    lat = np.array([coords[i][1] for i in ids])
    n = 2 ** z * 256
    px = (lon + 180) / 360 * n
    py = (1 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2 * n
    tx, ty = (px // 256).astype(int), (py // 256).astype(int)
    alt = np.zeros(len(ids))
    for (x, y) in set(zip(tx.tolist(), ty.tolist())):
        png = tuile_png(x, y, z)
        if png is None:
            continue
        a = relief.decoder(png)
        m = (tx == x) & (ty == y)
        alt[m] = a[np.clip((py[m] - y * 256).astype(int), 0, 255), np.clip((px[m] - x * 256).astype(int), 0, 255)]
    return dict(zip(ids, alt.tolist()))


# ------------------------------------------------------------------ graphe et traces
def construire_graphe(coords, aretes, alt):
    adj = defaultdict(list)
    for u, v, L, cat in aretes:
        c = L * FACTEUR[cat] + COUT_DENIVELE * abs(alt.get(u, 0) - alt.get(v, 0))
        adj[u].append((v, c, L, cat))
        adj[v].append((u, c, L, cat))
    return adj


def dijkstra(adj, source):
    dist, parent = {source: 0.0}, {source: None}
    file = [(0.0, source)]
    while file:
        d, u = heapq.heappop(file)
        if d > dist[u]:
            continue
        for v, c, _L, _cat in adj[u]:
            nd = d + c
            if nd < dist.get(v, math.inf):
                dist[v], parent[v] = nd, u
                heapq.heappush(file, (nd, v))
    return dist, parent


def plus_proche(coords, noeuds, point):
    ids = list(noeuds)
    xy = np.array([coords[i] for i in ids])
    d = np.hypot((xy[:, 0] - point[0]) * 111.32 * math.cos(math.radians(point[1])), (xy[:, 1] - point[1]) * 110.54)
    k = int(d.argmin())
    return ids[k], float(d[k]) * 1000


def grande_composante(adj):
    vus, meilleure = set(), set()
    for s in list(adj):
        if s in vus:
            continue
        comp, pile = {s}, [s]
        while pile:
            u = pile.pop()
            for v, *_ in adj[u]:
                if v not in comp:
                    comp.add(v)
                    pile.append(v)
        vus |= comp
        if len(comp) > len(meilleure):
            meilleure = comp
    return meilleure


def traces_epci(coms, adj, coords, alt, hub_code, k=NB_TRACES):
    """coms : DataFrame [code, nom, pop, score, lon, lat] des communes de l'EPCI. Retourne la liste de traces (dicts)."""
    comp = grande_composante(adj)
    noeuds = {i: coords[i] for i in comp}
    hub = coms[coms.code == hub_code].iloc[0]
    n_hub, _ = plus_proche(coords, noeuds, (hub.lon, hub.lat))
    dist, parent = dijkstra(adj, n_hub)
    atteints = {i: coords[i] for i in dist}
    # demande par noeud
    demande, noeud_de = defaultdict(float), {}
    for c in coms.itertuples():
        if c.code == hub_code:
            continue
        n, d = plus_proche(coords, atteints, (c.lon, c.lat))
        if d <= SNAP_MAX_M:
            noeud_de[c.code] = n
            demande[n] += float(c.pop) * (50.0 if pd.isna(c.score) else float(c.score)) / 100
    poids = defaultdict(float, demande)
    for n in sorted(dist, key=dist.get, reverse=True):
        if parent[n] is not None:
            poids[parent[n]] += poids[n]
    enfants = defaultdict(list)
    for n, p in parent.items():
        if p is not None and poids[n] > 0:
            enfants[p].append(n)
    lourd = {p: max(es, key=lambda e: poids[e]) for p, es in enfants.items()}

    def chemin_vers_racine(n):
        out = [n]
        while parent[out[-1]] is not None:
            out.append(parent[out[-1]])
        return out[::-1]

    def prolonger(n):  # descend le long des enfants les plus lourds jusqu'a une commune
        while n in lourd:
            n = lourd[n]
        return n

    tetes = [(poids[n_hub], n_hub)] + sorted(((poids[e], e) for p, es in enfants.items() for e in es if lourd.get(p) != e), reverse=True)
    traces, utilises = [], set()
    lat0 = float(hub.lat)
    for _, tete in tetes:
        if len(traces) >= k:
            break
        fin = prolonger(tete)
        noeuds_chemin = chemin_vers_racine(fin)
        if len(noeuds_chemin) < 2:
            continue
        aretes_chemin = []
        for u, v in zip(noeuds_chemin[:-1], noeuds_chemin[1:]):
            _v, _c, L, cat = min((a for a in adj[u] if a[0] == v), key=lambda a: a[1])
            aretes_chemin.append((u, v, L, cat))
        longueur = sum(a[2] for a in aretes_chemin)
        if longueur < LONGUEUR_MIN_M:
            continue
        nouvelles = [a for a in aretes_chemin if frozenset(a[:2]) not in utilises]
        if not nouvelles:
            continue
        utilises |= {frozenset(a[:2]) for a in aretes_chemin}
        traces.append(decrire(coms, coords, alt, noeuds_chemin, aretes_chemin, nouvelles, lat0, hub))
    return traces


def decrire(coms, coords, alt, noeuds, aretes, nouvelles, lat0, hub):
    ligne = LineString([(coords[n][0] * 111320 * math.cos(math.radians(lat0)), coords[n][1] * 110540) for n in noeuds])
    pts = {c.code: Point(c.lon * 111320 * math.cos(math.radians(lat0)), c.lat * 110540) for c in coms.itertuples()}
    servies = coms[[ligne.distance(pts[c]) <= RAYON_DESSERTE_M for c in coms.code]]
    km = defaultdict(float)
    for _u, _v, L, cat in aretes:
        km[cat] += L / 1000
    total = sum(km.values())
    # denivele sur un profil re-echantillonne tous les 100 m (le MNT ~50 m bruite les aretes courtes)
    cum = np.cumsum([0.0] + [a[2] for a in aretes])
    z = np.array([alt.get(n, 0.0) for n in noeuds])
    zr = np.interp(np.arange(0, cum[-1], 100.0), cum, z) if cum[-1] >= 100 else z
    dz = np.diff(zr)
    props = dict(
        longueur_km=round(total, 1), km_existant=round(km["existant"], 1), km_calme=round(km["calme"], 1), km_a_securiser=round(km["a_securiser"], 1),
        pct_adapte=round(100 * (km["existant"] + km["calme"]) / total) if total else 0,
        communes=int(len(servies)), communes_noms=", ".join(servies.sort_values("pop", ascending=False).nom.head(8)), pop_desservie=int(servies["pop"].sum()),
        score_moyen=round(float(servies.score.mean()), 0) if servies.score.notna().any() else None,
        denivele_positif_m=int(dz[dz > 0].sum()), pente_moyenne_pct=round(float(np.abs(dz).sum() / max(cum[-1], 1) * 100), 1), pole=hub.nom,
    )
    # segments a afficher : aretes non deja tracees, regroupees par categorie consecutive
    segs, cur = [], None
    for u, v, L, cat in nouvelles:
        if cur and cur[0] == cat and cur[1][-1] == coords[u]:
            cur[1].append(coords[v])
        else:
            if cur:
                segs.append(cur)
            cur = (cat, [coords[u], coords[v]])
    if cur:
        segs.append(cur)
    return dict(props=props, segments=[(c, [(round(x, 5), round(y, 5)) for x, y in pts_]) for c, pts_ in segs])


# ------------------------------------------------------------------ orchestration
def exemples_epci(code, coms, tuile_png=relief.telecharger_tuile, reseau=telecharger_reseau, lignes=None):
    """`lignes` (GeoDataFrame de voies, extrait Geofabrik) prime ; sinon `reseau(bbox)` interroge Overpass."""
    if lignes is not None:
        coords, aretes = lignes_vers_aretes(lignes)
    else:
        bbox = (coms.lon.min(), coms.lat.min(), coms.lon.max(), coms.lat.max())
        coords, aretes = aretes_osm(reseau(bbox))
    alt = altitudes(coords, tuile_png)
    adj = construire_graphe(coords, aretes, alt)
    hub = coms.sort_values("pop", ascending=False).iloc[0]
    return hub, traces_epci(coms, adj, coords, alt, hub.code)


def vers_geojson(resultats):
    feats = []
    for epci, nom, hub, traces, resume in resultats:
        feats.append(dict(type="Feature", geometry=dict(type="Point", coordinates=[round(hub.lon, 5), round(hub.lat, 5)]),
                          properties=dict(type="pole", epci=epci, epci_nom=nom, pole=hub.nom, **resume)))
        for i, t in enumerate(traces, 1):
            for cat, pts in t["segments"]:
                feats.append(dict(type="Feature", geometry=dict(type="LineString", coordinates=[list(p) for p in pts]),
                                  properties=dict(type="trace", epci=epci, epci_nom=nom, trace=i, categorie=cat, **t["props"])))
    return dict(type="FeatureCollection", features=feats)


def generer():
    import exporter
    from controle import poids_ts, score_global
    indic = pd.read_parquet(cfg.DOSSIER_BRUT / "indicateurs_communes.parquet")
    ind, axes = poids_ts()
    indic = indic.assign(score=score_global(indic.set_index("code"), ind, axes)[0].values)
    carte = exporter.charger_communes()
    pt = carte.to_crs(2154).representative_point().to_crs(4326)
    c = pd.DataFrame(dict(code=carte["code"].astype(str).values, nom=carte["nom"].values, dep=carte["dep"].values,
                          pop=pd.to_numeric(carte["pop"], errors="coerce").fillna(0).values, lon=pt.x.values, lat=pt.y.values))
    c = c.merge(indic[["code", "grille", "score"]], on="code", how="left").merge(table_epci(), on="code", how="left")
    c["rural"] = c["grille"].ge(5)  # grille de densite INSEE 5 a 7
    forces = [x for x in os.environ.get("EPCI_EXEMPLES", "").split(",") if x]
    choix = forces or choisir_epci(c, 10)
    log(f"exemples : {len(choix)} EPCI retenus : {choix}")
    reseaux = {}
    if shutil.which("osmium"):
        emprises = {e: (c[c.epci == e].lon.min(), c[c.epci == e].lat.min(), c[c.epci == e].lon.max(), c[c.epci == e].lat.max()) for e in choix}
        try:
            reseaux = reseaux_geofabrik(emprises)
        except Exception as e:  # noqa: BLE001
            log(f"  [!] extraits Geofabrik indisponibles ({type(e).__name__} {e}) : repli sur Overpass")
    else:
        log("  osmium absent : repli sur Overpass (public, limite en debit)")
    resultats = []
    for code in choix:
        coms = c[c.epci == code]
        nom = coms.epci_nom.iat[0]
        try:
            hub, traces = exemples_epci(code, coms, lignes=reseaux.get(code))
            resume = dict(communes_epci=int(len(coms)), pop_epci=int(coms["pop"].sum()), score_moyen=round(float(coms.score.mean()), 0), traces=len(traces))
            resultats.append((code, nom, hub, traces, resume))
            log(f"  {nom} ({code}) : {len(traces)} traces, pole {hub.nom}")
        except Exception as e:  # noqa: BLE001
            log(f"  [!] {nom} ({code}) ignore : {e}")
    f = cfg.DOSSIER_SORTIE / "exemples.geojson"
    cfg.DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(vers_geojson(resultats), ensure_ascii=False), encoding="utf-8")
    log(f"ecrit {f} ({f.stat().st_size / 1e3:.0f} ko, {len(resultats)} EPCI)")


def main():
    """Etape facultative : un echec (Overpass, geo.api...) ne doit pas bloquer le deploiement."""
    try:
        generer()
    except Exception as e:  # noqa: BLE001
        log(f"[!] exemples d'amenagement ignores : {type(e).__name__} {e}")


if __name__ == "__main__":
    main()
