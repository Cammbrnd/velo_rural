import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assembler  # noqa: E402
import config as cfg  # noqa: E402
import exporter  # noqa: E402
from outils import percentile, trouver_col, vers_nombre  # noqa: E402


def test_percentile_et_nombres():
    p = percentile(pd.Series([10.0, 20.0, 30.0, np.nan]))
    assert p.iloc[2] == 100.0 and p.iloc[0] < p.iloc[1] and np.isnan(p.iloc[3])
    assert vers_nombre(pd.Series(["1 234,5", "x", "2.5"])).tolist()[0] == 1234.5
    with pytest.raises(KeyError, match="Colonnes disponibles"):
        trouver_col(pd.DataFrame({"a": [1]}), "zzz", "test")


def ecrire(dossier, nom, texte, enc="utf-8"):
    (dossier / f"{nom}.csv").write_bytes(texte.encode(enc))


def test_construire(tmp_path):
    # separateur ';', virgule decimale, encodage latin-1, ligne EPCI melangee aux communes
    ecrire(tmp_path, "i_a", "CODGEO;LIBGEO;Total linéaire\n01001;Abergement;12,5\n01002;Autre;3,0\n01003;Troisieme;8,0\n200012345;EPCI;99\n", "latin-1")
    ecrire(tmp_path, "i_b", "code_commune,mode,distance moyenne\n01001,Ensemble,9.5\n01001,Velo,2.0\n01002,Ensemble,20\n01003,Ensemble,5\n")
    inds = {
        "i_a": dict(valeur=r"lin[ée]aire", transfo="bas"),
        "i_b": dict(valeur=r"distance", filtre=(r"mode", r"ensemble"), transfo="bas"),
        "i_manquant": dict(valeur=r"x", transfo="haut"),
    }
    table, rapport = assembler.construire(inds, tmp_path)
    assert len(table) == 3 and "200012345" not in set(table["code"])          # EPCI exclue
    t = table.set_index("code")
    assert t.loc["01002", "i_a"] == 100.0 and t.loc["01001", "i_a"] < t.loc["01003", "i_a"]  # 'bas' => petit = score eleve
    assert t.loc["01003", "i_b"] == 100.0                                       # filtre mode=Ensemble applique
    etats = {n: e for n, e, _ in rapport}
    assert etats == {"i_a": "ok", "i_b": "ok", "i_manquant": "IGNORE"}
    with pytest.raises(RuntimeError):
        assembler.construire({"i_manquant": inds["i_manquant"]}, tmp_path)


def test_grille_derniere_annee(tmp_path, monkeypatch):
    f = tmp_path / "grille.csv"
    f.write_text("code_commune;annee;grille_densite;grille_densite_texte\n01001;2024;3;Petites villes\n01001;2026;6;Rural dispersé\n01002;2026;9;invalide\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "SURCHARGE_GRILLE", str(f))
    g = assembler.grille_densite().set_index("code")
    assert g.loc["01001", "grille"] == 6 and "01002" not in g.index


def test_grille_indisponible_ne_bloque_pas(monkeypatch):
    monkeypatch.setattr(cfg, "SURCHARGE_GRILLE", "/chemin/inexistant.csv")
    assert assembler.grille_densite() is None


def test_exporter(tmp_path):
    communes = gpd.GeoDataFrame(
        {"code": ["01001", "01002"], "nom": ["A", "B"], "dep": ["01", "01"],
         "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)]}, crs=4326)
    indic = pd.DataFrame({"code": ["01001", "01002"], "i_a": [80.0, np.nan], "grille": [6, 7]})
    f = exporter.exporter(communes, indic, tmp_path / "data", tmp_path / "config.json")
    fc = json.loads(f.read_text())
    assert len(fc["features"]) == 2
    p = {x["properties"]["code"]: x["properties"] for x in fc["features"]}
    assert p["01001"]["i_a"] == 80.0 and p["01002"]["i_a"] is None            # NaN -> null (ignore cote app)
    tab = json.loads((tmp_path / "data" / "indicateurs.json").read_text())
    assert tab[1]["i_a"] is None and tab[0]["nom"] == "A"
    assert json.loads((tmp_path / "config.json").read_text())["demo"] is False


def test_lire_indicateur_format_long(tmp_path):
    import assembler
    f = tmp_path / "i.csv"
    f.write_text("annee,geocode_commune,type_accroche,valeur\n2024,03001,a,1.5\n2024,03001,b,2\n2024,2A004,a,4\n2023,03001,a,99\n", encoding="utf-8")
    t = assembler.lire_indicateur(f, dict(valeur=r"^valeur$")).set_index("code")["v"]
    assert t["03001"] == 3.5 and t["2A004"] == 4


def test_controle_score_et_poids_ts():
    import controle
    ind, axes = controle.poids_ts()
    assert ind["i_gisement"] == ("usage", 3) and axes == {"usage": 3, "faisabilite": 2, "deficit": 2}
    import numpy as np
    import pandas as pd
    df = pd.DataFrame({"i_compacite": [80.0, np.nan], "i_emploi_local": [20.0, np.nan], "i_securite": [50.0, 40.0]}, index=["a", "b"])
    g, sa = controle.score_global(df, ind, axes)
    assert sa.loc["a", "usage"] == 50.0 and np.isnan(sa.loc["b", "usage"])  # (2*80+2*20)/4
    assert g["a"] == (3 * 50 + 2 * 50) / 5 and g["b"] == 40.0  # axe usage absent pour b : ignore
    # synthetique complet : le rapport se construit sans erreur
    rng = np.random.default_rng(0)
    codes = [f"{i:05d}" for i in range(300)]
    t = pd.DataFrame({k: rng.uniform(0, 100, 300) for k in ind}, index=codes)
    t["grille"] = 5
    out = controle.rapport_controle(t.reset_index(names="code"), pd.Series(rng.integers(50, 5000, 300), index=codes))
    assert any("Sensibilite" in l for l in out)
