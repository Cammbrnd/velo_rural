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
from routes_calmes import est_calme_voie, etiquettes, type_piste

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
HIGHWAYS = "residential|living_street|unclassified|tertiary|secondary|track|cycleway|path"
FACTEUR = {"existant": 0.5, "calme": 1.0, "a_securiser": 1.8}
COUT_MONTEE = 6.0            # m de cout par m de montee (|dz| entre deux noeuds, altitudes lissees)
PENTE_REF = 0.04             # pente (4 %) a partir de laquelle le cout d'une arete double ; il croit ensuite au carre
PENTE_MAX_ARETE = 0.15       # arete plus raide (sur >= 40 m) : exclue du graphe
L_MIN_PENTE = 40.0           # longueur minimale pour calculer une pente (le MNT est a ~50 m)
PENALITE_CHANGEMENT = 250.0  # m de cout a chaque changement de route (nom / ref / voie OSM differents) : evite les zigzags
PENALITE_CHANGEMENT_PISTE = 60.0  # idem quand l'une des deux voies est un amenagement cyclable existant (raccords normaux)
FACTEUR_PARTAGE = 0.7        # cout des aretes deja utilisees par un autre chemin : les branches partagent un tronc au lieu de longer en parallele
PASSES_PARTAGE = 3
PENALITE_VIRAGE = ((150, math.inf), (120, 150.0), (60, 80.0), (30, 25.0))  # (angle mini en degres, penalite en m)
RAYON_DESSERTE_M = 300       # une commune est desservie si la trace passe a moins de 300 m de son centre-bourg
SNAP_MAX_M = 600             # le centre-bourg doit etre a moins de 600 m d'un noeud du reseau
RAYON_BOURG_M = 200          # aretes a moins de 200 m d'un centre-bourg : cout reduit (les traces traversent les villages)
FACTEUR_BOURG = 0.7
LIAISON_MAX_KM = 60          # liaison entre deux poles d'EPCI voisins
GROS_VILLAGE_HAB = 1500      # departement traite en entier : villages d'au moins 1 500 hab. (et poles d'EPCI) relies en priorite entre eux
VOISIN_GROS_KM = 20.0        # + liens vers les 2 plus proches voisins a moins de 20 km (en plus de l'arbre couvrant)
NB_GROS_EPCI = 4             # par EPCI : les 4 plus gros villages (hors pole) sont desservis en priorite
NB_TRACES = 5                # nombre maximal de traces (branches les plus pertinentes du reseau)
NB_EPCI = 20
PISTE_MIN_M = 2000           # une piste existante d'au moins 2 km est un point a rejoindre
POIDS_PISTE_PAR_KM = 150.0   # poids d'une piste a rejoindre (par km, plafonne a 10 km), a comparer a pop x score/100 des communes
LONGUEUR_MIN_M = 500         # longueur minimale de la partie nouvelle d'une branche
LONGUEUR_MAX_M = 25000       # une commune plus loin du pole (par la route) n'est pas reliee
DETOUR_MAX = 1.8             # longueur par la route / distance a vol d'oiseau
PENTE_MAX_500M = 0.07        # pente moyenne maximale sur 500 m
MONTEE_MAX_M_KM = 22.0       # montee cumulee maximale par km
CHANGEMENTS_MAX_KM = 4.0     # changements de route par km au plus
RURAL_MIN = 0.95             # part de communes rurales (grille de densite 5 a 7) d'au moins 95 %
HUB_MAX = 15000              # pole de moins de 15 000 hab. (pas une ville)
RELIEF_MIN = 45.0            # EPCI retenus : indicateur de relief moyen (0-100, 100 = plat) d'au moins 45 (pas de haute montagne)
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
        "relief": g["relief"].mean() if "relief" in communes.columns else 100.0,
        "n": g.size(), "pop": g["pop"].sum(), "rural": g["rural"].mean(), "score": g["score"].mean(), "hub": g["pop"].max(),
        "lon": g["lon"].mean(), "lat": g["lat"].mean(), "dep": g["dep"].agg(lambda s: s.mode().iat[0]),
        "etendue": g.apply(lambda d: distance_km((d.lon.min(), d.lat.min()), (d.lon.max(), d.lat.max())), include_groups=False),
    })
    cand = e[(e.n.between(10, 60)) & (e.rural >= RURAL_MIN) & (e.etendue <= 80) & (e.hub.between(1500, HUB_MAX)) & (e["pop"] >= 8000) & (e.relief >= RELIEF_MIN)].sort_values("score", ascending=False)
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


def choisir_departement(communes, dep):
    """Tous les EPCI dont la majorite des communes est dans le departement `dep` (code INSEE, ex. "03"), sans critere de ruralite."""
    c = communes.dropna(subset=["epci"])
    part = c.assign(dedans=c["dep"].astype(str) == str(dep)).groupby("epci")["dedans"].agg(["mean", "size"])
    return list(part[(part["mean"] > 0.5) & (part["size"] >= 5)].index)


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
    if highway == "cycleway" or (highway == "path" and tags.get("bicycle") in ("yes", "designated")) or type_piste(highway, tags) == "piste":
        return "existant"
    if highway == "path":
        return None
    return "calme" if est_calme_voie(highway, tags) else "a_securiser"


def cle_route(tags, ident):
    """Identite d'une route pour detecter les changements de route : ref, sinon nom, sinon voie OSM."""
    return tags.get("ref") or tags.get("name") or f"w{ident}"


def aretes_osm(elements):
    """-> coords {id: (lon, lat)}, aretes [(u, v, longueur_m, categorie, route)] entre noeuds OSM consecutifs."""
    coords, aretes = {}, []
    for w in elements:
        if w.get("type") != "way" or "geometry" not in w:
            continue
        tags = w.get("tags", {})
        cat = categorie(tags.get("highway", ""), tags)
        if cat is None or len(w["nodes"]) != len(w["geometry"]):
            continue
        pts = [(p["lon"], p["lat"]) for p in w["geometry"]]
        route = cle_route(tags, w.get("id"))
        for i, nid in enumerate(w["nodes"]):
            coords[nid] = pts[i]
        for i in range(len(pts) - 1):
            aretes.append((w["nodes"][i], w["nodes"][i + 1], 1000 * distance_km(pts[i], pts[i + 1]), cat, route))
    return coords, aretes


REGIONS_DEP = {
    "alsace": "67 68", "aquitaine": "24 33 40 47 64", "auvergne": "03 15 43 63", "basse-normandie": "14 50 61",
    "bourgogne": "21 58 71 89", "bretagne": "22 29 35 56", "centre": "18 28 36 37 41 45", "champagne-ardenne": "08 10 51 52",
    "corse": "2A 2B", "franche-comte": "25 39 70 90", "haute-normandie": "27 76", "ile-de-france": "75 77 78 91 92 93 94 95",
    "languedoc-roussillon": "11 30 34 48 66", "limousin": "19 23 87", "lorraine": "54 55 57 88",
    "midi-pyrenees": "09 12 31 32 46 65 81 82", "nord-pas-de-calais": "59 62", "pays-de-la-loire": "44 49 53 72 85",
    "picardie": "02 60 80", "poitou-charentes": "16 17 79 86", "provence-alpes-cote-d-azur": "04 05 06 13 83 84",
    "rhone-alpes": "01 07 26 38 42 69 73 74",
}
DEP_REGION = {d: r for r, ds in REGIONS_DEP.items() for d in ds.split()}


def regions_pour(deps):
    """{epci: {departements}} -> {region Geofabrik: [epci...]} (mapping statique, sans appel a l'index Geofabrik)."""
    out = defaultdict(list)
    for epci, ds in deps.items():
        for r in sorted({DEP_REGION[d] for d in ds if d in DEP_REGION}):
            out[r].append(epci)
    return out


def lignes_vers_aretes(lignes):
    """GeoDataFrame [geometry LineString, highway, other_tags, (name)] -> coords {noeud: (lon, lat)}, aretes.
    Les noeuds sont identifies par leurs coordonnees arrondies (les noeuds OSM partages coincident exactement)."""
    coords, aretes = {}, []
    noms = lignes["name"] if "name" in lignes.columns else [None] * len(lignes)
    for k, (geom, hw, ot, nom) in enumerate(zip(lignes.geometry, lignes["highway"], lignes["other_tags"], noms)):
        tags = etiquettes(ot)
        cat = categorie(str(hw), tags)
        if cat is None or geom is None or geom.is_empty:
            continue
        route = cle_route({**tags, "name": nom if isinstance(nom, str) else None}, k)
        for ligne in (geom.geoms if geom.geom_type == "MultiLineString" else [geom]):
            pts = [(round(x, 6), round(y, 6)) for x, y in ligne.coords]
            for a, b in zip(pts[:-1], pts[1:]):
                if a != b:
                    coords[a], coords[b] = a, b
                    aretes.append((a, b, 1000 * distance_km(a, b), cat, route))
    return coords, aretes


def extraire_reseau(pbf, bbox, tmp, nom, marge=0.03):
    """osmium : decoupe de l'emprise puis filtre des voies utiles ; lecture GDAL des lignes -> GeoDataFrame (ou None si vide)."""
    w, s_, e, n = bbox[0] - marge, bbox[1] - marge, bbox[2] + marge, bbox[3] + marge
    part, filtre = Path(tmp) / f"{nom}.part.osm.pbf", Path(tmp) / f"{nom}.voies.osm.pbf"
    subprocess.run(["osmium", "extract", "-b", f"{w},{s_},{e},{n}", str(pbf), "-o", str(part), "--overwrite"], check=True)
    subprocess.run(["osmium", "tags-filter", str(part), *[f"w/highway={h}" for h in HIGHWAYS.split("|")], "-o", str(filtre), "--overwrite"], check=True)
    sel = ",".join(f"'{h}'" for h in HIGHWAYS.split("|"))
    g = gpd.read_file(filtre, engine="pyogrio", sql=f"SELECT highway, name, other_tags FROM lines WHERE highway IN ({sel})")
    part.unlink(missing_ok=True)
    filtre.unlink(missing_ok=True)
    return g if len(g) else None


def extraire_lieux(pbf, bbox, tmp, nom, marge=0.03):
    """Noeuds place=city|town|village|hamlet de l'emprise -> GeoDataFrame [name, place, geometry] (ou None)."""
    w, s_, e, n = bbox[0] - marge, bbox[1] - marge, bbox[2] + marge, bbox[3] + marge
    part, filtre = Path(tmp) / f"{nom}.p.osm.pbf", Path(tmp) / f"{nom}.lieux.osm.pbf"
    subprocess.run(["osmium", "extract", "-b", f"{w},{s_},{e},{n}", str(pbf), "-o", str(part), "--overwrite"], check=True)
    subprocess.run(["osmium", "tags-filter", str(part), "n/place=city,town,village,hamlet", "-o", str(filtre), "--overwrite"], check=True)
    g = gpd.read_file(filtre, engine="pyogrio", sql="SELECT name, place FROM points WHERE place IN ('city','town','village','hamlet')")
    part.unlink(missing_ok=True)
    filtre.unlink(missing_ok=True)
    return g if len(g) else None


def normaliser(nom):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return re.sub(r"\bsaint(e?)\b", lambda m: "st" + m.group(1), t)


RANG_LIEU = {"city": 0, "town": 1, "village": 2, "hamlet": 3}


def bourgs(coms, lieux):
    """Remplace lon/lat (point interieur de la commune) par le centre-bourg : noeud place=* de meme nom (sinon le plus gros lieu
    a moins de 1,5 km). Sans donnees, la commune garde son point interieur."""
    coms = coms.copy()
    if lieux is None or not len(lieux):
        return coms
    xs, ys = lieux.geometry.x.values, lieux.geometry.y.values
    noms = [normaliser(x) if isinstance(x, str) else "" for x in lieux["name"]]
    rang = np.array([RANG_LIEU.get(x, 4) for x in lieux["place"]])
    for i, c in enumerate(coms.itertuples()):
        d = np.hypot((xs - c.lon) * 111.32 * math.cos(math.radians(c.lat)), (ys - c.lat) * 110.54)
        meme = np.array([n == normaliser(c.nom) for n in noms]) & (d <= 8)
        if meme.any():
            k = int(np.where(meme)[0][np.argmin(d[meme] + 10 * rang[meme])])
        else:
            proche = (d <= 1.5) & (rang <= 2)
            if not proche.any():
                continue
            k = int(np.where(proche)[0][np.argmin(rang[proche] * 10 + d[proche])])
        coms.iat[i, coms.columns.get_loc("lon")], coms.iat[i, coms.columns.get_loc("lat")] = float(xs[k]), float(ys[k])
    return coms


def reseaux_geofabrik(emprises, deps, lieux_out=None):
    """{epci: GeoDataFrame de voies} pour toutes les emprises, region par region (un telechargement par region)."""
    plan = regions_pour(deps)
    log(f"  reseaux OSM : {len(plan)} regions a lire ({', '.join(sorted(plan))})")
    morceaux = defaultdict(list)
    with tempfile.TemporaryDirectory() as tmp:
        for nom, epcis in plan.items():
            pbf = None
            for essai in range(1, 5):
                try:
                    pbf = telecharger(f"{cfg.GEOFABRIK}/{nom}-latest.osm.pbf", Path(tmp) / f"{nom}.osm.pbf")
                    break
                except requests.RequestException as e:
                    log(f"  [!] {nom} : essai {essai}/4 echoue ({type(e).__name__})")
                    (Path(tmp) / f"{nom}.osm.pbf").unlink(missing_ok=True)
                    time.sleep(15 * essai)
            if pbf is None:
                continue
            for epci in epcis:
                g = extraire_reseau(pbf, emprises[epci], tmp, f"{nom}_{epci}")
                if g is not None:
                    morceaux[epci].append(g)
                if lieux_out is not None:
                    try:
                        l = extraire_lieux(pbf, emprises[epci], tmp, f"{nom}_{epci}")
                        if l is not None:
                            lieux_out.setdefault(epci, []).append(l)
                    except Exception as e:  # noqa: BLE001
                        log(f"  [!] lieux {epci} ignores : {type(e).__name__}")
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
def lisser_altitudes(alt, aretes, passes=3):
    """Lissage des altitudes le long du reseau (le MNT a ~50 m rend les pentes des aretes courtes tres bruitees)."""
    if not aretes:
        return dict(alt)
    ids = list(alt)
    idx = {n: i for i, n in enumerate(ids)}
    z = np.array([alt[n] for n in ids], dtype=float)
    u = np.fromiter((idx[a[0]] for a in aretes), dtype=int, count=len(aretes))
    v = np.fromiter((idx[a[1]] for a in aretes), dtype=int, count=len(aretes))
    deg = np.bincount(u, minlength=len(ids)) + np.bincount(v, minlength=len(ids))
    for _ in range(passes):
        som = np.bincount(u, weights=z[v], minlength=len(ids)) + np.bincount(v, weights=z[u], minlength=len(ids))
        z = np.where(deg > 0, 0.5 * z + 0.5 * som / np.maximum(deg, 1), z)
    return dict(zip(ids, z.tolist()))


class Graphe:
    """Graphe d'aretes orientees. Un etat de Dijkstra est une arete orientee : on connait ainsi la route empruntee et la
    direction d'arrivee, donc on peut penaliser les changements de route et les virages (traces en zigzag)."""

    def __init__(self, coords, aretes, alt, attirants=()):
        self.coords = coords
        lat0 = float(np.mean([p[1] for p in coords.values()])) if coords else 46.0
        kx, ky = 111.32 * math.cos(math.radians(lat0)), 110.54
        self.E = []  # (u, v, longueur, categorie, route, cout, ux, uy)
        self.sortant = defaultdict(list)
        proches = np.zeros(len(aretes), dtype=bool)  # aretes a moins de RAYON_BOURG_M d'un centre-bourg
        if len(aretes) and len(attirants):
            mx = np.array([(coords[a[0]][0] + coords[a[1]][0]) / 2 for a in aretes])
            my = np.array([(coords[a[0]][1] + coords[a[1]][1]) / 2 for a in aretes])
            for lon, lat in attirants:
                proches |= np.hypot((mx - lon) * kx, (my - lat) * ky) * 1000 <= RAYON_BOURG_M
        for k, (u, v, L, cat, route) in enumerate(aretes):
            dz = alt.get(v, 0.0) - alt.get(u, 0.0)
            g = abs(dz) / max(L, L_MIN_PENTE)
            if g > PENTE_MAX_ARETE:
                continue  # trop raide : personne n'y passera a velo
            cout = L * FACTEUR[cat] * (1 + (g / PENTE_REF) ** 2) * (FACTEUR_BOURG if proches[k] else 1.0) + COUT_MONTEE * abs(dz)
            dx, dy = (coords[v][0] - coords[u][0]) * kx, (coords[v][1] - coords[u][1]) * ky
            n = math.hypot(dx, dy) or 1.0
            for a, b, sx, sy in ((u, v, dx / n, dy / n), (v, u, -dx / n, -dy / n)):
                self.sortant[a].append(len(self.E))
                self.E.append((a, b, L, cat, route, cout, sx, sy))
        self.cout = [e[5] for e in self.E]

    def partager(self, paires):
        """Rend moins chères les aretes (non orientees) deja utilisees : les chemins suivants tendent a les reprendre."""
        self.cout = [e[5] * (FACTEUR_PARTAGE if frozenset((e[0], e[1])) in paires else 1.0) for e in self.E]

    def penalite(self, e, f):
        a, b = self.E[e], self.E[f]
        angle = math.degrees(math.acos(max(-1.0, min(1.0, a[6] * b[6] + a[7] * b[7]))))  # 0 = tout droit
        pen = next((p for seuil, p in PENALITE_VIRAGE if angle >= seuil), 0.0)
        if a[4] == b[4]:
            return pen
        return pen + (PENALITE_CHANGEMENT_PISTE if "existant" in (a[3], b[3]) else PENALITE_CHANGEMENT)


def construire_graphe(coords, aretes, alt, attirants=()):
    return Graphe(coords, aretes, alt, attirants)


def dijkstra(G, source, horizon=4 * LONGUEUR_MAX_M):
    """Plus courts chemins depuis `source` sur les aretes orientees -> (dist, parent) indexes par arete (parent -1 = depart)."""
    E = G.E
    dist, parent = [math.inf] * len(E), [-1] * len(E)
    file = []
    for e in G.sortant.get(source, ()):
        dist[e] = G.cout[e]
        heapq.heappush(file, (dist[e], e))
    while file:
        d, e = heapq.heappop(file)
        if d > dist[e]:
            continue
        for f in G.sortant.get(E[e][1], ()):
            pen = G.penalite(e, f)
            if pen == math.inf:
                continue
            nd = d + G.cout[f] + pen
            if nd < dist[f] and nd < horizon:
                dist[f], parent[f] = nd, e
                heapq.heappush(file, (nd, f))
    return dist, parent


def plus_proche(coords, noeuds, point):
    ids = list(noeuds)
    xy = np.array([coords[i] for i in ids])
    d = np.hypot((xy[:, 0] - point[0]) * 111.32 * math.cos(math.radians(point[1])), (xy[:, 1] - point[1]) * 110.54)
    k = int(d.argmin())
    return ids[k], float(d[k]) * 1000


def grande_composante(G):
    pere = {}

    def racine(x):
        while pere.setdefault(x, x) != x:
            pere[x] = pere[pere[x]]
            x = pere[x]
        return x

    for u, v, *_ in G.E:
        pere[racine(u)] = racine(v)
    tailles = defaultdict(int)
    for x in list(pere):
        tailles[racine(x)] += 1
    if not tailles:
        return set()
    r = max(tailles, key=tailles.get)
    return {x for x in list(pere) if racine(x) == r}


def pistes_existantes(G):
    """Composantes connexes d'amenagements existants (arete 'existant') d'au moins PISTE_MIN_M -> ({noeud: id}, {id: km})."""
    pere = {}

    def racine(x):
        while pere.setdefault(x, x) != x:
            pere[x] = pere[pere[x]]
            x = pere[x]
        return x

    for u, v, L, cat, *_ in G.E:
        if cat == "existant":
            pere[racine(u)] = racine(v)
    km = defaultdict(float)
    for u, v, L, cat, *_ in G.E:
        if cat == "existant":
            km[racine(u)] += L / 2000  # chaque arete existe dans les deux sens
    ok = {r for r, k in km.items() if k * 1000 >= PISTE_MIN_M}
    return {x: racine(x) for x in list(pere) if racine(x) in ok}, {r: km[r] for r in ok}


def chaine(parent, e):
    """Aretes du depart jusqu'a l'arete `e`."""
    out = []
    while e != -1:
        out.append(e)
        e = parent[e]
    return out[::-1]


def profil_chemin(G, alt, ch):
    """(longueur m, montee cumulee m, pente moyenne max sur 500 m, nb de changements de route) d'une chaine d'aretes."""
    E = G.E
    cum = np.cumsum([0.0] + [E[e][2] for e in ch])
    z = np.array([alt.get(E[ch[0]][0], 0.0)] + [alt.get(E[e][1], 0.0) for e in ch])
    zr = np.interp(np.arange(0, cum[-1], 100.0), cum, z) if cum[-1] >= 100 else z
    dz = np.diff(zr)
    pente = float(np.max(np.abs(zr[5:] - zr[:-5])) / 500.0) if len(zr) > 5 else float(abs(zr[-1] - zr[0]) / max(cum[-1], 1.0))
    chg = sum(1 for e, f in zip(ch[:-1], ch[1:]) if E[e][4] != E[f][4])
    return float(cum[-1]), float(dz[dz > 0].sum()), pente, chg


def accepte(G, alt, ch, crow_m):
    """Chemin pole -> commune assez direct, plat et sans zigzag pour qu'on l'emprunte vraiment."""
    L, montee, pente, chg = profil_chemin(G, alt, ch)
    km = max(L / 1000, 0.1)
    return (L <= LONGUEUR_MAX_M and L <= DETOUR_MAX * max(crow_m, 1000.0) and montee / km <= MONTEE_MAX_M_KM
            and pente <= PENTE_MAX_500M and chg / km <= CHANGEMENTS_MAX_KM)


def traces_epci(coms, G, coords, alt, hub_code, k=NB_TRACES):
    """Reseau de traces reliant au pole (commune la plus peuplee) le maximum de communes de l'EPCI par des chemins
    directs et peu pentus : arbre des plus courts chemins vers les communes atteignables, decoupe en branches (traces)."""
    E = G.E
    comp = grande_composante(G)
    hub = coms[coms.code == hub_code].iloc[0]
    n_hub, _ = plus_proche(coords, {i: coords[i] for i in comp}, (hub.lon, hub.lat))
    comp_piste, km_piste = pistes_existantes(G)

    def passage():
        """Plus courts chemins puis communes / pistes atteignables -> (parent, poids par arete, paires d'aretes utilisees)."""
        dist, parent = dijkstra(G, n_hub)
        meilleure = {}
        for e, d in enumerate(dist):
            if d < math.inf and (E[e][1] not in meilleure or d < dist[meilleure[E[e][1]]]):
                meilleure[E[e][1]] = e
        poids, cibles = defaultdict(float), {}
        if not meilleure:
            return parent, poids, set(), cibles
        atteints = {n: coords[n] for n in meilleure}
        for cid, km in km_piste.items():  # pistes deja amenagees a rejoindre : on vise leur noeud le plus proche du pole
            noeuds_c = [n for n in meilleure if comp_piste.get(n) == cid]
            if not noeuds_c:
                continue
            n = min(noeuds_c, key=lambda x: dist[meilleure[x]])
            ch = chaine(parent, meilleure[n])
            if sum(E[e][2] for e in ch) < 300 or not accepte(G, alt, ch, 1000 * distance_km((hub.lon, hub.lat), coords[n])):
                continue
            for e in ch:
                poids[e] += POIDS_PISTE_PAR_KM * min(km, 10.0)
        for c in coms.itertuples():
            if c.code == hub_code:
                continue
            n, d = plus_proche(coords, atteints, (c.lon, c.lat))
            if d > SNAP_MAX_M:
                continue
            ch = chaine(parent, meilleure[n])
            if not accepte(G, alt, ch, 1000 * distance_km((hub.lon, hub.lat), (c.lon, c.lat))):
                continue
            w = 1.0 + float(c.pop) * (50.0 if pd.isna(c.score) else float(c.score)) / 100 * max(1.0, float(c.pop) / 1000)  # les gros villages pesent plus que proportionnellement
            cibles[c.code] = (n, float(c.pop))
            for e in ch:
                poids[e] += w
        return parent, poids, {frozenset((E[e][0], E[e][1])) for e in poids}, cibles

    for _ in range(PASSES_PARTAGE - 1):  # chaque passe rend moins cheres les aretes deja utilisees : les branches partagent un tronc
        _p, _w, paires, _c = passage()
        if not paires:
            return []
        G.partager(paires)
    parent, poids, _, cibles = passage()
    if not poids:
        return []
    # priorite : les plus gros villages (hors pole) doivent etre desservis par les premieres branches retenues
    gros = {code: n for code, (n, _pop) in sorted(cibles.items(), key=lambda kv: -kv[1][1])[:NB_GROS_EPCI]}
    enfants = defaultdict(list)
    for e in poids:
        enfants[parent[e]].append(e)
    lourd = {p: max(es, key=lambda e: poids[e]) for p, es in enfants.items()}

    def prolonger(e):
        while e in lourd:
            e = lourd[e]
        return e

    tetes = sorted((e for p, es in enfants.items() for e in es if p == -1 or lourd[p] != e), key=lambda e: -poids[e])
    cand = []
    for tete in tetes:
        ch = chaine(parent, prolonger(tete))
        cand.append((tete, ch, {E[e][0] for e in ch} | {E[e][1] for e in ch}))
    non_servis = dict(gros)
    traces, utilises = [], set()
    lat0 = float(hub.lat)
    while cand and len(traces) < k:
        # branche qui dessert le plus d'habitants parmi les gros villages pas encore servis ; a egalite, la plus lourde
        cand.sort(key=lambda x: (-sum(cibles[c][1] for c, n in non_servis.items() if n in x[2]), -poids[x[0]]))
        tete, ch, noeuds_ch = cand.pop(0)
        aretes_chemin = [(E[e][0], E[e][1], E[e][2], E[e][3], E[e][4]) for e in ch]
        nouvelles = [a for a in aretes_chemin if frozenset(a[:2]) not in utilises]
        if sum(a[2] for a in nouvelles) < LONGUEUR_MIN_M:
            continue
        utilises |= {frozenset(a[:2]) for a in aretes_chemin}
        non_servis = {c: n for c, n in non_servis.items() if n not in noeuds_ch}
        noeuds_chemin = [aretes_chemin[0][0]] + [a[1] for a in aretes_chemin]
        t = decrire(coms, coords, alt, noeuds_chemin, aretes_chemin, nouvelles, lat0, hub)
        rejointes = {comp_piste[n] for n in noeuds_chemin if n in comp_piste and km_piste.get(comp_piste[n], 0) * 1000 >= PISTE_MIN_M}
        t["props"]["pistes_rejointes"] = len(rejointes)
        t["props"]["km_pistes_rejointes"] = round(sum(km_piste[c] for c in rejointes), 1)
        traces.append(t)
    return traces


def decrire(coms, coords, alt, noeuds, aretes, nouvelles, lat0, hub):
    ligne = LineString([(coords[n][0] * 111320 * math.cos(math.radians(lat0)), coords[n][1] * 110540) for n in noeuds])
    pts = {c.code: Point(c.lon * 111320 * math.cos(math.radians(lat0)), c.lat * 110540) for c in coms.itertuples()}
    servies = coms[[ligne.distance(pts[c]) <= RAYON_DESSERTE_M for c in coms.code]]
    km = defaultdict(float)
    for a in aretes:
        km[a[3]] += a[2] / 1000
    total = sum(km.values())
    cum = np.cumsum([0.0] + [a[2] for a in aretes])
    z = np.array([alt.get(n, 0.0) for n in noeuds])
    zr = np.interp(np.arange(0, cum[-1], 100.0), cum, z) if cum[-1] >= 100 else z
    dz = np.diff(zr)
    pente500 = float(np.max(np.abs(zr[5:] - zr[:-5])) / 500.0) if len(zr) > 5 else float(abs(zr[-1] - zr[0]) / max(cum[-1], 1.0))
    chg = sum(1 for x, y in zip(aretes[:-1], aretes[1:]) if x[4] != y[4])
    fin = coords[noeuds[-1]]
    crow = max(1000 * distance_km((hub.lon, hub.lat), fin), 1.0)
    props = dict(
        longueur_km=round(total, 1), km_existant=round(km["existant"], 1), km_calme=round(km["calme"], 1), km_a_securiser=round(km["a_securiser"], 1),
        pct_adapte=round(100 * (km["existant"] + km["calme"]) / total) if total else 0,
        communes=int(len(servies)), communes_noms=", ".join(servies.sort_values("pop", ascending=False).nom.head(8)), pop_desservie=int(servies["pop"].sum()),
        score_moyen=round(float(servies.score.mean()), 0) if servies.score.notna().any() else None,
        denivele_positif_m=int(dz[dz > 0].sum()), pente_moyenne_pct=round(float(np.abs(dz).sum() / max(cum[-1], 1) * 100), 1),
        pente_max_500m_pct=round(100 * pente500, 1), changements_route=chg, sinuosite=round(float(total * 1000 / crow), 2), pole=hub.nom,
    )
    segs, cur = [], None
    for a in nouvelles:
        u, v, cat = a[0], a[1], a[3]
        if cur and cur[0] == cat and cur[1][-1] == coords[u]:
            cur[1].append(coords[v])
        else:
            if cur:
                segs.append(cur)
            cur = (cat, [coords[u], coords[v]])
    if cur:
        segs.append(cur)
    return dict(props=props, codes=set(servies.code), segments=[(c, [(round(x, 5), round(y, 5)) for x, y in pts_]) for c, pts_ in segs])


# ------------------------------------------------------------------ orchestration
def exemples_epci(code, coms, tuile_png=relief.telecharger_tuile, reseau=telecharger_reseau, lignes=None):
    """`lignes` (GeoDataFrame de voies, extrait Geofabrik) prime ; sinon `reseau(bbox)` interroge Overpass."""
    if lignes is not None:
        coords, aretes = lignes_vers_aretes(lignes)
    else:
        bbox = (coms.lon.min(), coms.lat.min(), coms.lon.max(), coms.lat.max())
        coords, aretes = aretes_osm(reseau(bbox))
    alt = lisser_altitudes(altitudes(coords, tuile_png), aretes)
    G = construire_graphe(coords, aretes, alt, list(zip(coms.lon, coms.lat)))
    hub = coms.sort_values("pop", ascending=False).iloc[0]
    return hub, traces_epci(coms, G, coords, alt, hub.code)


def mst_liaisons(hubs):
    """{epci: (lon, lat)} -> [(a, b)] : arbre couvrant minimal (Prim) des poles, liaisons de moins de LIAISON_MAX_KM seulement."""
    reste = list(hubs)
    if len(reste) < 2:
        return []
    dedans, liens = {reste.pop(0)}, []
    while reste:
        a, b = min(((a, b) for a in dedans for b in reste), key=lambda ab: distance_km(hubs[ab[0]], hubs[ab[1]]))
        if distance_km(hubs[a], hubs[b]) <= LIAISON_MAX_KM:
            liens.append((a, b))
        dedans.add(b)
        reste.remove(b)
    return liens


def liens_gros_villages(pts, voisins=2):
    """{code: (lon, lat)} -> [(a, b)] : arbre couvrant minimal + liens vers les `voisins` plus proches a moins de VOISIN_GROS_KM."""
    liens = {tuple(sorted(x)) for x in mst_liaisons(pts)}
    for a in pts:
        proches = sorted((b for b in pts if b != a and distance_km(pts[a], pts[b]) <= VOISIN_GROS_KM), key=lambda b: distance_km(pts[a], pts[b]))[:voisins]
        liens |= {tuple(sorted((a, b))) for b in proches}
    return sorted(liens)


def liaison(coms_ab, lignes, hub_a, hub_b, tuile_png=relief.telecharger_tuile):
    """Trace reliant les poles de deux EPCI voisins (meme modele de cout : pentes, virages, bourgs, pistes existantes).
    -> trace (dict de decrire) ou None si aucun chemin raisonnable."""
    coords, aretes = lignes_vers_aretes(lignes)
    alt = lisser_altitudes(altitudes(coords, tuile_png), aretes)
    G = construire_graphe(coords, aretes, alt, list(zip(coms_ab.lon, coms_ab.lat)))
    comp = grande_composante(G)
    noeuds = {i: coords[i] for i in comp}
    na, _ = plus_proche(coords, noeuds, (hub_a.lon, hub_a.lat))
    dist, parent = dijkstra(G, na, horizon=4 * LIAISON_MAX_KM * 1000)
    E = G.E
    meilleure = {}
    for e, d in enumerate(dist):
        if d < math.inf and (E[e][1] not in meilleure or d < dist[meilleure[E[e][1]]]):
            meilleure[E[e][1]] = e
    if not meilleure:
        return None
    nb, d = plus_proche(coords, {n: coords[n] for n in meilleure}, (hub_b.lon, hub_b.lat))
    if d > SNAP_MAX_M:
        return None
    ch = chaine(parent, meilleure[nb])
    L, montee, pente, chg = profil_chemin(G, alt, ch)
    crow = 1000 * distance_km((hub_a.lon, hub_a.lat), (hub_b.lon, hub_b.lat))
    if L > LIAISON_MAX_KM * 1000 or L > 2.0 * crow or pente > PENTE_MAX_500M or montee / max(L / 1000, 0.1) > MONTEE_MAX_M_KM:
        log(f"  liaison {hub_a.nom} - {hub_b.nom} : aucun chemin acceptable (L={L / 1000:.0f} km, detour {L / max(crow, 1):.1f}, pente {100 * pente:.1f} %)")
        return None
    ar = [(E[e][0], E[e][1], E[e][2], E[e][3], E[e][4]) for e in ch]
    t = decrire(coms_ab, coords, alt, [ar[0][0]] + [a[1] for a in ar], ar, ar, float(hub_a.lat), hub_a)
    t["props"]["liaison"] = True
    return t


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
    c = c.merge(indic[["code", "grille", "score"] + (["i_relief"] if "i_relief" in indic.columns else [])].rename(columns={"i_relief": "relief"}), on="code", how="left").merge(table_epci(), on="code", how="left")
    c["rural"] = c["grille"].ge(5)  # grille de densite INSEE 5 a 7
    forces = [x for x in os.environ.get("EPCI_EXEMPLES", "").split(",") if x]
    choix = choisir_epci(c, NB_EPCI)
    for dep in [x for x in os.environ.get("DEPARTEMENTS_EXEMPLES", "03").split(",") if x]:  # departements traites en entier, en plus
        choix += [e for e in choisir_departement(c, dep) if e not in choix]
    choix = forces or choix
    log(f"exemples : {len(choix)} EPCI retenus : {choix}")
    # liaisons prioritaires : entre les plus gros villages (>= GROS_VILLAGE_HAB) et les poles des EPCI d'un meme departement traite en entier
    liens = []
    for dep in [x for x in os.environ.get("DEPARTEMENTS_EXEMPLES", "03").split(",") if x]:
        ce = c[c.epci.isin(choix) & (c.dep.astype(str) == dep)]
        pts = {r.code: (r.lon, r.lat) for r in ce[ce["pop"] >= GROS_VILLAGE_HAB].itertuples()}
        for e in ce.epci.unique():
            h = ce[ce.epci == e].sort_values("pop", ascending=False).iloc[0]
            pts[h.code] = (h.lon, h.lat)
        liens += liens_gros_villages(pts)
    log(f"exemples : {len(liens)} liaisons entre gros villages a etudier")
    reseaux, lieux = {}, {}
    if shutil.which("osmium"):
        emprises = {e: (c[c.epci == e].lon.min(), c[c.epci == e].lat.min(), c[c.epci == e].lon.max(), c[c.epci == e].lat.max()) for e in choix}
        deps = {e: set(c[c.epci == e].dep.astype(str)) for e in choix}
        try:
            reseaux = reseaux_geofabrik(emprises, deps, lieux)
        except Exception as e:  # noqa: BLE001
            log(f"  [!] extraits Geofabrik indisponibles ({type(e).__name__} {e}) : repli sur Overpass")
    else:
        log("  osmium absent : repli sur Overpass (public, limite en debit)")
    lieux = {k: pd.concat(v, ignore_index=True) for k, v in lieux.items()}
    resultats, coms_b = [], {}
    for code in choix:
        coms = bourgs(c[c.epci == code], lieux.get(code))  # les traces visent et traversent le centre-bourg
        coms_b[code] = coms
        nom = coms.epci_nom.iat[0]
        try:
            hub, traces = exemples_epci(code, coms, lignes=reseaux.get(code))
            reliees = set().union(*[t["codes"] for t in traces]) | {hub.code} if traces else set()
            resume = dict(communes_epci=int(len(coms)), communes_reliees=len(reliees), pop_epci=int(coms["pop"].sum()),
                          score_moyen=round(float(coms.score.mean()), 0), traces=len(traces))
            resultats.append((code, nom, hub, traces, resume))
            log(f"  {nom} ({code}) : {len(traces)} traces, {resume['communes_reliees']}/{len(coms)} communes reliees, pole {hub.nom}")
        except Exception as e:  # noqa: BLE001
            log(f"  [!] {nom} ({code}) ignore : {e}")
    tous = pd.concat(coms_b.values(), ignore_index=True).drop_duplicates("code").set_index("code", drop=False) if coms_b else pd.DataFrame(index=[])
    for a, b in liens:
        try:
            if a not in tous.index or b not in tous.index:
                continue
            ha, hb = tous.loc[a], tous.loc[b]
            w, s_, e_, n_ = min(ha.lon, hb.lon) - 0.08, min(ha.lat, hb.lat) - 0.08, max(ha.lon, hb.lon) + 0.08, max(ha.lat, hb.lat) + 0.08
            morceaux = [reseaux[e].cx[w:e_, s_:n_] for e in coms_b if e in reseaux]
            morceaux = [m for m in morceaux if len(m)]
            if not morceaux:
                continue
            lignes = pd.concat(morceaux, ignore_index=True)
            lignes = lignes.loc[~lignes.geometry.to_wkb().duplicated()]  # les emprises d'EPCI voisins se recouvrent
            zone = tous[tous.lon.between(w, e_) & tous.lat.between(s_, n_)]
            t = liaison(zone, lignes, ha, hb)
            if t is None:
                continue
            nom = f"Liaison {ha.nom} - {hb.nom}"
            resume = dict(liaison=True, communes_epci=0, communes_reliees=len(t["codes"]), pop_epci=0, score_moyen=None, traces=1)
            resultats.append((f"liaison-{a}-{b}", nom, ha, [t], resume))
            log(f"  {nom} : {t['props']['longueur_km']} km, existant {t['props']['pct_adapte']} % adapte, {len(t['codes'])} communes sur le trajet")
        except Exception as e:  # noqa: BLE001
            log(f"  [!] liaison {a}-{b} ignoree : {type(e).__name__} {e}")
    if not resultats:
        log("[!] aucun exemple produit : exemples.geojson non ecrit")
        return
    f = cfg.DOSSIER_SORTIE / "exemples.geojson"
    cfg.DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(vers_geojson(resultats), ensure_ascii=False), encoding="utf-8")
    log(f"ecrit {f} ({f.stat().st_size / 1e3:.0f} ko, {len(resultats)} EPCI)")


def forcer_ipv4():
    """Les runners GitHub renvoient parfois 'Network is unreachable' en IPv6 : on resout en IPv4 uniquement."""
    import socket
    import urllib3.util.connection as uc
    uc.allowed_gai_family = lambda: socket.AF_INET


def main():
    """Etape facultative : un echec (Overpass, geo.api...) ne doit pas bloquer le deploiement."""
    forcer_ipv4()
    try:
        generer()
    except Exception as e:  # noqa: BLE001
        log(f"[!] exemples d'amenagement ignores : {type(e).__name__} {e}")


if __name__ == "__main__":
    main()
