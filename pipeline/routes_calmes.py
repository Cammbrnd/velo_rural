"""Routes calmes (OSM) : km de voirie peu circulee mobilisable en itineraire partage, par km2 de commune.

Lourd (extraits regionaux Geofabrik, plusieurs centaines de Mo chacun) : ROUTES_CALMES=1 pour l'activer.
Traitement region par region pour limiter la memoire.
"""
import geopandas as gpd
import pandas as pd

import config as cfg
from couches import longueur_par_commune, superficie_km2
from outils import log, percentile, telecharger

HIGHWAY_CALMES = {"residential", "living_street", "unclassified", "track", "path"}


def vitesse(other_tags):
    """maxspeed (km/h) lu dans le champ hstore `other_tags` du pilote OSM de GDAL, sinon NaN."""
    if not isinstance(other_tags, str):
        return float("nan")
    for kv in other_tags.split('","'):
        k, _, v = kv.strip('"').partition('"=>"')
        if k == "maxspeed":
            try:
                return float(v.split()[0])
            except ValueError:
                return float("nan")
    return float("nan")


def est_calme(highway, other_tags):
    """Vrai si la voie est secondaire ET peu rapide : residentielle / non classee / chemin, ou tertiaire limitee a 50."""
    h = highway.astype(str)
    v = other_tags.map(vitesse)
    base = h.isin(HIGHWAY_CALMES)
    tertiaire_lente = (h == "tertiary") & (v <= 50)
    trop_rapide = v > 50
    return (base | tertiaire_lente) & ~trop_rapide


def routes_calmes_region(pbf, communes_region):
    lignes = gpd.read_file(pbf, layer="lines", engine="pyogrio",
                           sql="SELECT highway, other_tags FROM lines WHERE highway IS NOT NULL")
    lignes = lignes[est_calme(lignes["highway"], lignes["other_tags"])]
    return longueur_par_commune(lignes, communes_region)


def indicateur_routes_calmes(communes, dossier):
    km = pd.Series(0.0, index=communes["code"].values)
    for region in cfg.REGIONS_GEOFABRIK:
        pbf = telecharger(f"{cfg.GEOFABRIK}/{region}-latest.osm.pbf", dossier / f"osm_{region}.osm.pbf")
        log(f"  routes calmes : {region}")
        part = routes_calmes_region(pbf, communes)  # communes recouvrant la region : les autres restent a 0
        km = km.add(part, fill_value=0.0)
        pbf.unlink()  # libere le disque du runner
    dens = km / superficie_km2(communes).clip(lower=0.1)
    return percentile(dens).rename("i_routes_calmes"), f"{km.sum():.0f} km de routes calmes, {int((km > 0).sum())} communes"
