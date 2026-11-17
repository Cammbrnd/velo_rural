"""Routes calmes (OSM) : km de voirie peu circulee mobilisable en itineraire partage, par km2 de commune.

Lourd (extraits regionaux Geofabrik, ~4,5 Go au total) : calcule a la demande (ROUTES_CALMES=1), puis le resultat par
commune est conserve dans routes_calmes.csv (cache du workflow) et reutilise tel quel aux runs suivants.
Chaque region est pre-filtree par `osmium tags-filter` (rapide) quand l'outil est installe, puis lue par GDAL.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

import config as cfg
from couches import longueur_par_commune, superficie_km2
from outils import log, percentile, telecharger

HIGHWAY_RETENUS = ("residential", "living_street", "unclassified", "tertiary", "track")
REVETUS = {"asphalt", "paved", "concrete", "concrete:plates", "concrete:lanes", "paving_stones", "sett", "compacted", "fine_gravel"}
_TAG = re.compile(r'"([^"]+)"=>"((?:[^"\\]|\\.)*)"')


def etiquettes(other_tags):
    """Champ hstore `other_tags` du pilote OSM de GDAL -> dict."""
    return dict(_TAG.findall(other_tags)) if isinstance(other_tags, str) else {}


def vitesse(t):
    """maxspeed (km/h) d'un dict d'etiquettes, NaN si absent ou non numerique."""
    try:
        return float(str(t.get("maxspeed", "")).split()[0])
    except (ValueError, IndexError):
        return float("nan")


def est_calme_voie(highway, t):
    """Vrai si la voie est secondaire ET peu rapide et ouverte aux velos :
    residentielle / living_street / non classee (sauf maxspeed > 50) ; tertiaire seulement si limitee a 50 ;
    piste (track) seulement si revetue ou de bonne tenue (tracktype grade1-2). Exclut acces interdit/prive et bicycle=no."""
    if t.get("bicycle") in ("no", "dismount") or t.get("access") in ("no", "private") or t.get("vehicle") == "no":
        return False
    v = vitesse(t)
    if highway in ("residential", "living_street", "unclassified"):
        return not v > 50
    if highway == "tertiary":
        return v <= 50
    if highway == "track":
        return t.get("tracktype") in ("grade1", "grade2") or t.get("surface") in REVETUS
    return False


def est_calme(highway, other_tags):
    tags = other_tags.map(etiquettes)
    return pd.Series([est_calme_voie(h, t) for h, t in zip(highway.astype(str), tags)], index=highway.index)


def lire_lignes(pbf):
    sel = ",".join(f"'{h}'" for h in HIGHWAY_RETENUS)
    return gpd.read_file(pbf, engine="pyogrio", sql=f"SELECT highway, other_tags FROM lines WHERE highway IN ({sel})")


def prefiltrer(pbf, dossier_tmp):
    """osmium tags-filter : ne garde que les voies utiles (10 a 20 fois plus petit que la region). Sans osmium : fichier inchange."""
    if not shutil.which("osmium"):
        return pbf
    sortie = Path(dossier_tmp) / (Path(pbf).name + ".filtre.osm.pbf")
    filtres = [f"w/highway={h}" for h in HIGHWAY_RETENUS]
    subprocess.run(["osmium", "tags-filter", str(pbf), *filtres, "-o", str(sortie), "--overwrite"], check=True)
    return sortie


ROUTES_CYCLABLES = {"residential", "living_street", "unclassified", "tertiary", "secondary", "primary", "trunk", "service", "track"}
CHEMINS = {"path", "footway", "pedestrian", "track", "bridleway", "steps"}


def type_piste(highway, t):
    """'piste' (voie separee : cycleway, voie verte, cycleway=track), 'bande' (cycleway=lane) ou None."""
    if t.get("bicycle") == "no" or t.get("access") in ("no", "private"):
        return None
    if highway == "cycleway":
        return "piste"
    if highway in CHEMINS and t.get("bicycle") == "designated":
        return "piste"
    vals = {t.get(k) for k in ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")}
    if highway in ROUTES_CYCLABLES:
        if vals & {"track", "opposite_track"}:
            return "piste"
        if vals & {"lane", "opposite_lane"}:
            return "bande"
    return None


def pistes_region(pbf, dossier_tmp):
    """GeoDataFrame [type, geometry] des amenagements cyclables existants d'une region (osmium tags-filter, puis GDAL)."""
    sortie = Path(dossier_tmp) / (Path(pbf).name + ".pistes.osm.pbf")
    filtres = ["w/highway=cycleway", "w/cycleway", "w/cycleway:left", "w/cycleway:right", "w/cycleway:both", "w/bicycle=designated"]
    subprocess.run(["osmium", "tags-filter", str(pbf), *filtres, "-o", str(sortie), "--overwrite"], check=True)
    g = gpd.read_file(sortie, engine="pyogrio", sql="SELECT highway, other_tags FROM lines")
    sortie.unlink(missing_ok=True)
    g["type"] = [type_piste(str(h), etiquettes(o)) for h, o in zip(g["highway"], g["other_tags"])]
    g = g[g["type"].notna()][["type", "geometry"]]
    g["geometry"] = g.geometry.simplify(0.00005)
    return g


def routes_calmes_region(pbf, communes_region):
    lignes = lire_lignes(pbf)
    lignes = lignes[est_calme(lignes["highway"], lignes["other_tags"])]
    return longueur_par_commune(lignes, communes_region)


def urls_regions():
    """URL des extraits regionaux de France : lues dans l'index Geofabrik (noms de regions changeants), sinon liste de config."""
    try:
        import requests
        idx = requests.get("https://download.geofabrik.de/index-v1-nogeom.json", timeout=60).json()
        urls = {f["properties"]["id"]: f["properties"]["urls"]["pbf"] for f in idx["features"]
                if f["properties"].get("parent") == "france" and f["properties"].get("urls", {}).get("pbf")}
        # on exclut les territoires d'outre-mer s'ils sont listes sous france (les communes sont metropolitaines)
        urls = {k: u for k, u in urls.items() if not re.search(r"guadeloupe|martinique|guyane|reunion|mayotte", k)}
        if urls:
            log(f"  index Geofabrik : {len(urls)} regions ({', '.join(sorted(urls))})")
            return urls
    except Exception as e:  # noqa: BLE001
        log(f"  [!] index Geofabrik illisible ({e}) : liste de config")
    return {r: f"{cfg.GEOFABRIK}/{r}-latest.osm.pbf" for r in cfg.REGIONS_GEOFABRIK}


def calculer(communes, fichier_pistes=None):
    """km de routes calmes par commune ; ecrit aussi, si fichier_pistes est donne, les pistes cyclables existantes (GeoJSON national)."""
    km = pd.Series(0.0, index=communes["code"].values)
    pistes = []
    with tempfile.TemporaryDirectory() as tmp:  # hors du cache : les extraits ne sont pas conserves
        for region, url in urls_regions().items():
            log(f"  routes calmes : {region}")
            pbf = telecharger(url, Path(tmp) / f"{region}.osm.pbf")
            if fichier_pistes and shutil.which("osmium"):
                try:
                    pistes.append(pistes_region(pbf, tmp))
                except Exception as e:  # noqa: BLE001
                    log(f"  [!] pistes {region} ignorees : {type(e).__name__} {e}")
            part = routes_calmes_region(prefiltrer(pbf, tmp), communes)
            km = km.add(part, fill_value=0.0)
            for f in Path(tmp).iterdir():
                f.unlink()
    if fichier_pistes and pistes:
        g = pd.concat(pistes, ignore_index=True)
        g = gpd.GeoDataFrame(g, geometry="geometry", crs=4326)
        Path(fichier_pistes).unlink(missing_ok=True)
        g.to_file(fichier_pistes, driver="GeoJSON", COORDINATE_PRECISION=5)
        log(f"  pistes cyclables : {len(g)} troncons ({g['type'].value_counts().to_dict()}), {Path(fichier_pistes).stat().st_size / 1e6:.0f} Mo")
    return km


def indicateur_routes_calmes(communes, dossier, recalculer=False):
    cache = Path(dossier) / "routes_calmes.csv"
    if cache.exists() and cache.stat().st_size > 0 and not recalculer:
        km = pd.read_csv(cache, dtype={"code": str}).set_index("code")["km"]
        log(f"  routes calmes : cache {cache.name}")
    else:
        km = calculer(communes, Path(dossier) / "pistes.geojson")
        km.rename("km").rename_axis("code").to_csv(cache)
    km = km.reindex(communes["code"].values).fillna(0.0)
    dens = km / superficie_km2(communes).clip(lower=0.1)
    return percentile(dens).rename("i_routes_calmes"), f"{km.sum():.0f} km de routes calmes, {int((km > 0).sum())} communes"
