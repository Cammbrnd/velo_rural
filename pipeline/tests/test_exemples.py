import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import exemples  # noqa: E402

LON0, LAT0 = 3.0, 46.0
DX, DY = 0.0155, 0.009  # ~1,2 km x 1 km


def reseau_grille(n=7, speciales=None):
    """Grille n x n de voies residentielles ; `speciales` : {(i, j, 'h'|'v'): highway} pour changer une voie."""
    speciales = speciales or {}
    els, nid = [], lambda i, j: 1000 + i * 100 + j
    def pt(i, j):
        return dict(lon=LON0 + i * DX, lat=LAT0 + j * DY)
    wid = 1
    for j in range(n):  # lignes horizontales (en j fixe)
        for i in range(n - 1):
            hw = speciales.get((i, j, "h"), "residential")
            els.append(dict(type="way", id=wid, nodes=[nid(i, j), nid(i + 1, j)], geometry=[pt(i, j), pt(i + 1, j)], tags=dict(highway=hw))); wid += 1
    for i in range(n):
        for j in range(n - 1):
            hw = speciales.get((i, j, "v"), "residential")
            els.append(dict(type="way", id=wid, nodes=[nid(i, j), nid(i, j + 1)], geometry=[pt(i, j), pt(i, j + 1)], tags=dict(highway=hw))); wid += 1
    return els


def communes_test():
    pos = {"A": (0, 0, 3000), "B": (6, 0, 800), "C": (6, 6, 600), "D": (0, 6, 400), "E": (3, 3, 100)}
    return pd.DataFrame([dict(code=k, nom="Commune " + k, pop=v[2], score=60.0, lon=LON0 + v[0] * DX, lat=LAT0 + v[1] * DY) for k, v in pos.items()])


def test_aretes_et_categories():
    els = reseau_grille(3, {(0, 0, "h"): "cycleway", (1, 0, "h"): "secondary", (0, 1, "h"): "track"})
    coords, aretes = exemples.aretes_osm(els)
    cats = {(a[0], a[1]): a[3] for a in aretes}
    assert cats[(1000, 1100)] == "existant" and cats[(1100, 1200)] == "a_securiser"
    assert cats[(1001, 1101)] is not None and cats[(1001, 1101)] == "a_securiser"  # track non revetue : pas calme
    assert exemples.categorie("path", {}) is None and exemples.categorie("path", {"bicycle": "designated"}) == "existant"
    assert sum(1 for a in aretes if a[3] == "calme") > 0 and all(a[2] > 500 for a in aretes)


def test_traces_hub_et_communes_desservies():
    coords, aretes = exemples.aretes_osm(reseau_grille())
    alt = {n: 0.0 for n in coords}
    adj = exemples.construire_graphe(coords, aretes, alt)
    t = exemples.traces_epci(communes_test(), adj, coords, alt, "A")
    assert len(t) >= 1
    p0 = t[0]["props"]
    assert p0["pole"] == "Commune A" and p0["communes"] >= 2 and p0["longueur_km"] > 5
    assert p0["pct_adapte"] == 100 and p0["km_a_securiser"] == 0
    # les traces suivantes ne redessinent pas les segments deja traces
    pts = [tuple(map(tuple, s[1])) for tr in t for s in tr["segments"]]
    aretes_vues = [frozenset(pair) for seg in pts for pair in zip(seg[:-1], seg[1:])]
    assert len(aretes_vues) == len(set(aretes_vues))


def test_trace_evite_les_voies_a_securiser():
    # la voie directe A->B (j=0) est une departementale ; le chemin par j=1 est calme et peu plus long
    sp = {(i, 0, "h"): "secondary" for i in range(6)}
    coords, aretes = exemples.aretes_osm(reseau_grille(7, sp))
    adj = exemples.construire_graphe(coords, aretes, {n: 0.0 for n in coords})
    coms = communes_test()[lambda d: d.code.isin(["A", "B"])]
    t = exemples.traces_epci(coms, adj, coords, {n: 0.0 for n in coords}, "A")
    assert t and t[0]["props"]["km_a_securiser"] < 3.0


def test_denivele_penalise_un_col():
    coords, aretes = exemples.aretes_osm(reseau_grille())
    # un relief de 300 m sur la ligne centrale j=0 : le chemin doit contourner
    alt = {n: (300.0 if (n - 1000) // 100 in (2, 3) and (n - 1000) % 100 == 0 else 0.0) for n in coords}
    adj = exemples.construire_graphe(coords, aretes, alt)
    t = exemples.traces_epci(communes_test()[lambda d: d.code.isin(["A", "B"])], adj, coords, alt, "A")
    assert t[0]["props"]["denivele_positif_m"] < 200


def test_choisir_epci_repartis_et_ruraux():
    lignes = []
    for k in range(6):  # 6 EPCI de 15 communes, departements differents, alignes d'ouest en est
        for j in range(15):
            lignes.append(dict(code=f"{k}{j:02d}", dep=f"{k:02d}", pop=2000 if j == 0 else 500, epci=f"E{k}", rural=True, score=50 + k, lon=-2 + k * 2.0 + j * 0.01, lat=46 + j * 0.01))
    lignes += [dict(code=f"U{j}", dep="99", pop=90000, epci="URB", rural=False, score=90, lon=3, lat=46) for j in range(15)]
    c = pd.DataFrame(lignes)
    choix = exemples.choisir_epci(c, n=4)
    assert len(choix) == 4 and "URB" not in choix and choix[0] == "E5"
    lons = sorted(c[c.epci.isin(choix)].groupby("epci").lon.mean())
    assert lons[1] - lons[0] >= 2.0 - 1e-6  # espaces


def test_geojson_et_altitudes_sans_tuile():
    els = reseau_grille()
    coords, _ = exemples.aretes_osm(els)
    alt = exemples.altitudes(coords, tuile_png=lambda x, y, z: None)
    assert set(alt) == set(coords) and all(v == 0 for v in alt.values())
    hub, traces = exemples.exemples_epci("E", communes_test(), tuile_png=lambda x, y, z: None, reseau=lambda bbox: els)
    gj = exemples.vers_geojson([("E", "EPCI test", hub, traces, dict(communes_epci=5, communes_reliees=5, pop_epci=4900, score_moyen=60, traces=len(traces)))])
    types = {f["properties"]["type"] for f in gj["features"]}
    assert types == {"pole", "trace"} and hub.nom == "Commune A"


def test_lignes_vers_aretes_et_regions():
    import geopandas as gpd
    from shapely.geometry import LineString, box
    els = reseau_grille(7)
    lignes = gpd.GeoDataFrame({"highway": [e["tags"]["highway"] for e in els], "other_tags": [None] * len(els),
                               "geometry": [LineString([(p["lon"], p["lat"]) for p in e["geometry"]]) for e in els]}, crs=4326)
    coords, aretes = exemples.lignes_vers_aretes(lignes)
    adj = exemples.construire_graphe(coords, aretes, {n: 0.0 for n in coords})
    t = exemples.traces_epci(communes_test(), adj, coords, {n: 0.0 for n in coords}, "A")
    assert len(t) >= 1 and t[0]["props"]["communes"] >= 2
    hub, tr = exemples.exemples_epci("E", communes_test(), tuile_png=lambda x, y, z: None, lignes=lignes)
    assert hub.nom == "Commune A" and tr
    assert len(exemples.DEP_REGION) == 96
    plan = exemples.regions_pour({"X": {"03", "63"}, "Y": {"2A"}, "Z": {"63", "15"}})
    assert dict(plan) == {"auvergne": ["X", "Z"], "corse": ["Y"]}
    ot = '"bicycle"=>"no"'
    g2 = lignes.copy(); g2["other_tags"] = ot
    assert exemples.lignes_vers_aretes(g2)[1] == []


def test_type_piste():
    from routes_calmes import type_piste
    assert type_piste("cycleway", {}) == "piste"
    assert type_piste("cycleway", {"access": "private"}) is None
    assert type_piste("path", {"bicycle": "designated"}) == "piste"
    assert type_piste("path", {}) is None
    assert type_piste("residential", {"cycleway:right": "lane"}) == "bande"
    assert type_piste("secondary", {"cycleway": "track"}) == "piste"
    assert type_piste("residential", {"cycleway": "shared_lane"}) is None


def test_commune_en_montagne_non_reliee_et_pentes_evitees():
    coords, aretes = exemples.aretes_osm(reseau_grille())
    # B (6,0) au sommet d'un versant raide : +400 m sur 3 mailles = ~11 % : rien de raisonnable pour l'atteindre
    alt = {n: (min(400.0, 130.0 * max(0, (n - 1000) // 100 - 3)) if (n - 1000) // 100 >= 4 else 0.0) for n in coords}
    G = exemples.construire_graphe(coords, aretes, alt)
    t = exemples.traces_epci(communes_test(), G, coords, alt, "A")
    noms = " ".join(x["props"]["communes_noms"] for x in t)
    assert "Commune B" not in noms and "Commune C" not in noms
    assert "Commune E" in noms
    assert all(x["props"]["pente_max_500m_pct"] <= 7.0 for x in t)


def test_changements_de_route_et_virages_penalises():
    # deux routes de A vers B : un escalier (virages et changements de voie a chaque maille) et une voie droite un peu plus longue
    coords, aretes = exemples.aretes_osm(reseau_grille(7))
    alt = {n: 0.0 for n in coords}
    # on rend la ligne j=0 une seule route nommee : continuite, pas de changement de route
    aretes2 = [(u, v, L, cat, "D7" if (u - 1000) % 100 == 0 and (v - 1000) % 100 == 0 else r) for u, v, L, cat, r in aretes]
    G = exemples.construire_graphe(coords, aretes2, alt)
    t = exemples.traces_epci(communes_test()[lambda d: d.code.isin(["A", "B"])], G, coords, alt, "A")
    assert t and t[0]["props"]["changements_route"] <= 1 and t[0]["props"]["sinuosite"] <= 1.1
    assert exemples.Graphe(coords, aretes2, alt).penalite(0, 0) >= 0


def test_relier_un_maximum_de_communes_au_pole():
    coords, aretes = exemples.aretes_osm(reseau_grille())
    alt = {n: 0.0 for n in coords}
    G = exemples.construire_graphe(coords, aretes, alt)
    t = exemples.traces_epci(communes_test(), G, coords, alt, "A")
    codes = set().union(*[x["codes"] for x in t])
    assert {"B", "C", "D", "E"} <= codes
    assert len(t) <= exemples.NB_TRACES


def test_lissage_altitudes():
    aretes = [(i, i + 1, 20.0, "calme", "r") for i in range(10)]
    alt = {i: (100.0 if i == 5 else 0.0) for i in range(11)}  # un pic de bruit sur un noeud
    l = exemples.lisser_altitudes(alt, aretes)
    assert max(l.values()) < 60 and abs(sum(l.values()) - 100) < 1e-6 + 40


def test_rejoindre_une_piste_existante():
    sp = {(i, 6, "h"): "cycleway" for i in (3, 4, 5)}  # 3,6 km de piste a l'autre bout, a hauteur de la ligne j=6
    coords, aretes = exemples.aretes_osm(reseau_grille(7, sp))
    alt = {n: 0.0 for n in coords}
    G = exemples.construire_graphe(coords, aretes, alt)
    comp, km = exemples.pistes_existantes(G)
    assert len(km) == 1 and 3.5 < list(km.values())[0] < 3.7
    coms = communes_test()[lambda d: d.code.isin(["A", "E"])]
    t = exemples.traces_epci(coms, G, coords, alt, "A")
    assert any(x["props"]["pistes_rejointes"] == 1 for x in t)
    assert exemples.categorie("residential", {"cycleway:right": "track"}) == "existant"
    assert exemples.categorie("residential", {"cycleway": "lane"}) == "calme"


def test_cinq_branches_au_plus():
    coords, aretes = exemples.aretes_osm(reseau_grille())
    alt = {n: 0.0 for n in coords}
    t = exemples.traces_epci(communes_test(), exemples.construire_graphe(coords, aretes, alt), coords, alt, "A")
    assert 1 <= len(t) <= 5


def test_choisir_departement():
    c = pd.DataFrame({"code": list("abcdefghij"), "dep": ["03"] * 6 + ["63"] * 2 + ["03", "63"],
                      "epci": ["E1"] * 6 + ["E2"] * 3 + ["E3"], "pop": 100})
    assert exemples.choisir_departement(c, "03") == ["E1"]  # E2 : 1 commune sur 3 seulement ; E3 : trop petit


def test_bourgs_et_normalisation():
    assert exemples.normaliser("Saint-Étienne-de-Lisse") == exemples.normaliser("St Etienne de Lisse")
    coms = pd.DataFrame({"code": ["1", "2", "3"], "nom": ["Saint-Pourçain", "Lieu", "Rien"], "pop": 1, "lon": [3.0, 3.2, 3.4], "lat": [46.0, 46.0, 46.0]})
    lieux = gpd.GeoDataFrame({"name": ["Saint Pourcain", "Hameau X", "Autre"], "place": ["town", "village", "hamlet"],
                              "geometry": [Point(3.003, 46.002), Point(3.201, 46.001), Point(3.6, 46.0)]}, crs=4326)
    b = exemples.bourgs(coms, lieux)
    assert (b.lon.iat[0], b.lat.iat[0]) == (3.003, 46.002)       # meme nom
    assert (b.lon.iat[1], b.lat.iat[1]) == (3.201, 46.001)       # a defaut, un village proche
    assert (b.lon.iat[2], b.lat.iat[2]) == (3.4, 46.0)           # rien de proche : point interieur conserve


def test_mst_liaisons():
    hubs = {"A": (3.0, 46.0), "B": (3.3, 46.0), "C": (3.6, 46.0), "D": (8.0, 46.0)}
    liens = exemples.mst_liaisons(hubs)
    assert sorted(tuple(sorted(x)) for x in liens) == [("A", "B"), ("B", "C")]  # D trop loin


def test_traversee_du_bourg():
    # deux routes de A vers B de longueur voisine : celle qui traverse le bourg intermediaire est preferee
    coords, aretes = exemples.aretes_osm(reseau_grille())
    alt = {n: 0.0 for n in coords}
    G0 = exemples.construire_graphe(coords, aretes, alt)
    u, v = aretes[0][:2]
    milieu = ((coords[u][0] + coords[v][0]) / 2, (coords[u][1] + coords[v][1]) / 2)
    G1 = exemples.construire_graphe(coords, aretes, alt, [milieu])
    assert sum(G1.cout) < sum(G0.cout)


def test_liaison_entre_deux_poles():
    from shapely.geometry import LineString
    els = reseau_grille(7)
    lignes = gpd.GeoDataFrame({"highway": [e["tags"]["highway"] for e in els], "other_tags": [None] * len(els),
                               "geometry": [LineString([(p["lon"], p["lat"]) for p in e["geometry"]]) for e in els]}, crs=4326)
    coms = communes_test()
    ha, hb = coms[coms.code == "A"].iloc[0], coms[coms.code == "B"].iloc[0]
    t = exemples.liaison(coms, lignes, ha, hb, tuile_png=lambda x, y, z: None)
    assert t and t["props"]["liaison"] and t["props"]["longueur_km"] > 5


def test_liens_gros_villages():
    pts = {"A": (3.0, 46.0), "B": (3.1, 46.0), "C": (3.2, 46.0), "D": (3.3, 46.0), "Z": (8.0, 46.0)}
    liens = exemples.liens_gros_villages(pts)
    assert ("A", "B") in liens and ("B", "C") in liens and ("C", "D") in liens  # arbre couvrant
    assert ("A", "C") in liens                                              # + 2 plus proches voisins (A : B et C)
    assert all("Z" not in x for x in liens)                                 # trop loin de tout


def test_priorite_au_plus_gros_village():
    coms = communes_test()
    coms.loc[coms.code == "D", "pop"] = 2500
    coords, aretes = exemples.aretes_osm(reseau_grille())
    alt = {n: 0.0 for n in coords}
    G = exemples.construire_graphe(coords, aretes, alt)
    t = exemples.traces_epci(coms, G, coords, alt, "A", k=1)
    assert len(t) == 1 and "Commune D" in t[0]["props"]["communes_noms"]
