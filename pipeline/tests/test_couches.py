import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import couches  # noqa: E402
import routes_calmes  # noqa: E402
import securite  # noqa: E402
from outils import percentile_presence  # noqa: E402


@pytest.fixture
def communes():
    # deux carres voisins de ~0,1 deg (~8 x 11 km) en Auvergne
    return gpd.GeoDataFrame(
        {"code": ["03001", "03002"], "nom": ["A", "B"], "pop": [1000.0, 250.0],
         "geometry": [box(3.0, 46.0, 3.1, 46.1), box(3.1, 46.0, 3.2, 46.1)]}, crs=4326)


def test_percentile_presence():
    p = percentile_presence(pd.Series([0.0, 0.0, 5.0, 10.0, np.nan]))
    assert np.isnan(p.iloc[0]) and np.isnan(p.iloc[1]) and 50 < p.iloc[2] < p.iloc[3] == 100 and np.isnan(p.iloc[4])


def test_longueur_decoupee_par_commune(communes):
    # ligne E-O a mi-hauteur : 0,1 deg dans A et 0,1 deg dans B, plus un morceau hors des deux communes
    l = gpd.GeoDataFrame(geometry=[LineString([(3.0, 46.05), (3.2, 46.05)]), LineString([(5, 47), (5.1, 47)])], crs=4326)
    km = couches.longueur_par_commune(l, communes)
    assert set(km.index) == {"03001", "03002"}
    assert km["03001"] == pytest.approx(km["03002"], rel=0.02) and 7 < km["03001"] < 9  # 0,1 deg a 46 N ~ 7,7 km


def test_comptage_par_code_puis_spatial(communes):
    pts = gpd.GeoDataFrame({"insee": ["03001", "03001", "03002"]}, geometry=[Point(3.05, 46.05)] * 2 + [Point(3.15, 46.05)], crs=4326)
    assert couches.compter_par_commune(pts, communes, "insee").to_dict() == {"03001": 2, "03002": 1}
    pts["insee"] = ["99999"] * 3  # code non fiable -> jointure spatiale
    assert couches.compter_par_commune(pts, communes, "insee").to_dict() == {"03001": 2, "03002": 1}


def test_indicateur_couche_de_bout_en_bout(communes, tmp_path, monkeypatch):
    f = tmp_path / "bnac.geojson"
    gpd.GeoDataFrame({"statut": ["Fermee", "Exploitee"]},
                     geometry=[LineString([(3.0, 46.05), (3.1, 46.05)]), LineString([(3.1, 46.05), (3.2, 46.05)])], crs=4326).to_file(f, driver="GeoJSON")
    monkeypatch.setattr(couches, "resoudre_url", lambda c: ("http://x/bnac.geojson", "bnac.geojson"))
    monkeypatch.setattr(couches, "telecharger", lambda url, dest: f)
    c = dict(mode="longueur", transfo="presence", filtre=("statut", "ferm|declass"))
    s, detail = couches.indicateur_couche("i_emprises_ferrees", c, communes, tmp_path)
    assert s["03001"] == 100.0 and np.isnan(s["03002"]) and "1 objets lus" in detail   # seule la ligne fermee est retenue
    # sans filtre, ~7,7 km dans chaque commune : par habitant, A (1000 hab) en a 4x moins que B (250 hab) => deficit maximal pour A
    c2 = dict(mode="longueur", transfo="bas", par_habitant=True)
    s2, _ = couches.indicateur_couche("i_deficit_lineaire", c2, communes, tmp_path)
    assert s2["03001"] == 100.0 and s2["03002"] == 50.0


def test_couche_en_echec_ignoree(communes, tmp_path, monkeypatch):
    def echec(c):
        raise RuntimeError("introuvable")
    monkeypatch.setattr(couches, "resoudre_url", echec)
    table, rapport = couches.construire_couches({"i_x": dict(mode="points", transfo="haut")}, communes, tmp_path)
    assert table.empty and rapport[0][:2] == ("i_x", "IGNORE")


def test_fusion_remplace_la_colonne_tbmd():
    base = pd.DataFrame({"code": ["a", "b", "c"], "i_deficit_lineaire": [10.0, 20.0, 30.0], "i_x": [1.0, 2.0, 3.0]})
    geo = pd.DataFrame({"code": ["a", "b", "d"], "i_deficit_lineaire": [90.0, np.nan, 50.0], "i_nouveau": [5.0, 6.0, 7.0]})
    t = couches.fusionner(base, geo).set_index("code")
    assert t.loc["a", "i_deficit_lineaire"] == 90.0 and t.loc["b", "i_deficit_lineaire"] == 20.0  # NaN -> on garde TBMD
    assert t.loc["c", "i_nouveau"] != t.loc["c", "i_nouveau"] and t.loc["a", "i_nouveau"] == 5.0
    assert "d" in t.index and t.loc["d", "i_deficit_lineaire"] == 50.0


def test_securite_codes_et_comptage():
    recent = pd.DataFrame({"dep": ["01", "01", "2A"], "com": ["01001", "01001", "2A004"]})
    ancien = pd.DataFrame({"dep": ["010", "590"], "com": ["002", "350"]})  # anciens millesimes : dep sur 3 car., com sur 3
    assert securite.code_commune(ancien).tolist() == ["01002", "59350"]
    assert securite.accidents_par_commune([recent, ancien]).to_dict() == {"01001": 2, "2A004": 1, "01002": 1, "59350": 1}


def test_routes_calmes_classification():
    h = pd.Series(["residential", "tertiary", "tertiary", "unclassified", "primary", "residential"])
    tags = pd.Series([None, '"maxspeed"=>"50"', '"surface"=>"asphalt","maxspeed"=>"80"', None, None, '"maxspeed"=>"90"'])
    assert routes_calmes.est_calme(h, tags).tolist() == [True, True, False, True, False, False]


def test_points_csv_coordonneesxy(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("id,capacite,coordonneesxy\n1,4,\"3.05,46.05\"\n2,2,\"[3.15, 46.05]\"\n3,1,\"50,10\"\n", encoding="utf-8")
    g = couches.lire_points_csv(f, {})
    assert len(g) == 2 and g.geometry.iloc[0].x == pytest.approx(3.05)


def test_lire_couche_zip_sous_dossier(tmp_path):
    import zipfile
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("dossier/p.geojson", '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"a":1},"geometry":{"type":"Point","coordinates":[3.05,46.05]}}]}')
    g = couches.lire_couche(z, {}, "zip")
    assert len(g) == 1 and g.crs.to_epsg() == 4326


def test_baac_noms_de_fichiers(monkeypatch):
    titres = ["Caract_2025.csv", "caract-2023.csv", "carcteristiques-2022.csv", "caracteristiques-2020.csv", "Lieux_2025.csv", "usagers-2023.csv"]
    ress = [{"title": t, "url": f"https://x/{t}", "format": "csv"} for t in titres]
    monkeypatch.setattr(securite, "api_get", lambda *a, **k: {"resources": ress})
    assert [a for a, _ in securite.ressources_caracteristiques("x")] == [2025, 2023, 2022, 2020]


def test_choisir_ressource_tous_formats(monkeypatch):
    import outils
    res = [dict(title="DPF wfs", format="ogc:wfs", url="http://x/wfs", filesize=1),
           dict(title="DPF shp", format="shp", url="http://x/a", filesize=50),
           dict(title="DPF geojson", format="geojson", url="http://x/b", filesize=10),
           dict(title="Description des champs", format="csv", url="http://x/c")]
    monkeypatch.setattr(outils, "api_get", lambda *a, **k: {"resources": res})
    r = outils.choisir_ressource("id", formats=None, ordre=("geojson", "gpkg", "shp"), plus_grosse=True)
    assert r["url"] == "http://x/b"
    with pytest.raises(RuntimeError, match="Ressources"):
        outils.choisir_ressource("id", formats=("gpkg",))


def test_ext_reelle(tmp_path):
    for contenu, attendu in [(b"PK\x03\x04abc", "zip"), (b"SQLite format 3\x00", "gpkg"), (b'{"type":"FeatureCollection"}', "geojson"), (b"<?xml version", "gml"), (b"a,b\n1,2", "csv")]:
        f = tmp_path / "x"
        f.write_bytes(contenu)
        assert couches.ext_reelle(f, "csv") == attendu


def test_longueur_sur_surfaces_utilise_le_contour(communes, tmp_path, monkeypatch):
    f = tmp_path / "surf.geojson"
    gpd.GeoDataFrame(geometry=[box(3.02, 46.02, 3.08, 46.08)], crs=4326).to_file(f, driver="GeoJSON")
    monkeypatch.setattr(couches, "resoudre_url", lambda c: ("http://x/s.geojson", "s.geojson"))
    monkeypatch.setattr(couches, "telecharger", lambda url, dest: f)
    s, _ = couches.indicateur_couche("i_canaux", dict(mode="longueur", transfo="presence"), communes, tmp_path)
    assert s["03001"] == 100.0 and pd.isna(s["03002"])


def test_routes_calmes_regles_etiquettes():
    cas = [("track", '"tracktype"=>"grade1"'), ("track", '"tracktype"=>"grade4"'), ("track", '"surface"=>"asphalt"'),
           ("residential", '"bicycle"=>"no"'), ("unclassified", '"access"=>"private"'), ("living_street", None),
           ("unclassified", '"maxspeed"=>"80"'), ("tertiary", None), ("path", '"bicycle"=>"yes"')]
    h = pd.Series([c[0] for c in cas])
    tags = pd.Series([c[1] for c in cas])
    assert routes_calmes.est_calme(h, tags).tolist() == [True, False, True, False, False, True, False, False, False]


def test_routes_calmes_lecture_osm_et_densite(tmp_path):
    """Lit un vrai fichier .osm (pilote GDAL) : seules les voies calmes comptent dans la commune."""
    osm = tmp_path / "t.osm"
    noeuds = {1: (3.02, 46.05), 2: (3.08, 46.05), 3: (3.02, 46.06), 4: (3.08, 46.06), 5: (3.02, 46.07), 6: (3.08, 46.07)}
    xml = ['<?xml version="1.0"?>', '<osm version="0.6">']
    xml += [f'<node id="{i}" lat="{la}" lon="{lo}"/>' for i, (lo, la) in noeuds.items()]
    voies = [(10, 1, 2, [("highway", "residential")]), (11, 3, 4, [("highway", "primary")]),
             (12, 5, 6, [("highway", "tertiary"), ("maxspeed", "80")])]
    for wid, a, b, tags in voies:
        xml.append(f'<way id="{wid}"><nd ref="{a}"/><nd ref="{b}"/>' + "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags) + "</way>")
    xml.append("</osm>")
    osm.write_text("\n".join(xml), encoding="utf-8")
    communes = gpd.GeoDataFrame({"code": ["03001", "03002"], "geometry": [box(3.0, 46.0, 3.1, 46.1), box(3.2, 46.0, 3.3, 46.1)]}, crs=4326)
    km = routes_calmes.routes_calmes_region(osm, communes)
    assert 4.0 < km["03001"] < 5.0
    assert km.get("03002", 0) == 0
