"""Etape 2 : assemble les indicateurs par commune, les oriente (100 = favorable), normalise en percentiles."""
import pandas as pd

import config as cfg
import couches
import exporter
import routes_calmes
import securite
from outils import choisir_ressource, lire_csv, log, percentile, telecharger, trouver_col, vers_nombre

REGEX_CODE = r"^(code_?commune|codgeo|code_?insee|insee_?com|geo_?code|code)$|code.*(geo|commune|insee)"


def lire_indicateur(chemin, c):
    """Retourne un DataFrame [code, v] (v numerique brut) pour un fichier TBMD."""
    df = lire_csv(chemin)
    col_code = trouver_col(df, REGEX_CODE, "code commune")
    if c.get("filtre"):
        col_f = trouver_col(df, c["filtre"][0], "filtre")
        df = df[df[col_f].astype(str).str.contains(c["filtre"][1], case=False, regex=True, na=False)]
    df = df[df[col_code].astype(str).str.len() == 5]  # niveau commune uniquement
    col_v = trouver_col(df, c["valeur"], "valeur")
    log(f"  colonne '{col_v}' ({len(df)} communes)")
    out = pd.DataFrame({"code": df[col_code].astype(str), "v": vers_nombre(df[col_v])})
    return out.drop_duplicates("code")


def construire(indicateurs, dossier):
    """Lit chaque indicateur disponible ; retourne (table, rapport). Un indicateur en echec est ignore."""
    tables, rapport = [], []
    for nom, c in indicateurs.items():
        f = dossier / f"{nom}.csv"
        try:
            if not f.exists():
                raise FileNotFoundError(f"fichier absent : {f.name}")
            log(nom)
            t = lire_indicateur(f, c)
            brut = -t["v"] if c["transfo"] == "bas" else t["v"]
            t[nom] = percentile(brut)
            tables.append(t[["code", nom]])
            rapport.append((nom, "ok", f"{t['v'].notna().sum()} communes renseignees"))
        except Exception as e:  # noqa: BLE001
            log(f"[!] {nom} ignore : {e}")
            rapport.append((nom, "IGNORE", str(e)))
    if not tables:
        raise RuntimeError("aucun indicateur lu : voir donnees_brutes/inspection.txt et config.py")
    table = tables[0]
    for t in tables[1:]:
        table = table.merge(t, on="code", how="outer")
    return table, rapport


def grille_densite():
    """Grille communale de densite INSEE a 7 niveaux -> DataFrame [code, grille] (derniere annee), ou None."""
    try:
        src = cfg.SURCHARGE_GRILLE
        if src and src.startswith("http"):
            f = telecharger(src, cfg.DOSSIER_BRUT / "grille_densite_surcharge")
        elif src:
            f = src
        else:
            res = choisir_ressource(cfg.ID_DATASET_GRILLE, formats=("csv", "csv.gz"))
            f = telecharger(res["url"], cfg.DOSSIER_BRUT / "grille_densite.csv")
        df = pd.read_excel(f, dtype=str) if str(f).endswith((".xlsx", ".xls")) else lire_csv(f)
        col_code = trouver_col(df, REGEX_CODE, "code commune")
        col_g = trouver_col(df, r"^grille_densite$|grille.*(7|niveau)|^grille", "grille")
        try:  # plusieurs millesimes : garder le plus recent
            col_a = trouver_col(df, r"^(annee|millesime|year)$", "annee")
            df = df[df[col_a] == df[col_a].max()]
        except KeyError:
            pass
        out = pd.DataFrame({"code": df[col_code].astype(str).str.zfill(5), "grille": vers_nombre(df[col_g])})
        out = out[out["grille"].between(1, 7)].drop_duplicates("code")
        out["grille"] = out["grille"].astype(int)
        log(f"grille de densite : {len(out)} communes")
        return out
    except Exception as e:  # noqa: BLE001
        log(f"[!] grille de densite indisponible ({e}) : le filtre rural sera desactive")
        return None


def indicateurs_geo(communes, dossier):
    """Couches geographiques + securite (+ routes calmes si active) -> (table [code, indicateurs], rapport)."""
    table, rapport = couches.construire_couches(cfg.COUCHES, communes, dossier)
    extras = [("i_securite", lambda: securite.indicateur_securite(communes, dossier))]
    if cfg.ROUTES_CALMES:
        extras.append(("i_routes_calmes", lambda: routes_calmes.indicateur_routes_calmes(communes, dossier)))
    else:
        rapport.append(("i_routes_calmes", "DESACTIVE", "lourd (OSM) : lancer avec ROUTES_CALMES=1"))
    series = []
    for nom, f in extras:
        try:
            log(nom)
            s, detail = f()
            series.append(s)
            rapport.append((nom, "ok", detail))
        except Exception as e:  # noqa: BLE001
            log(f"[!] {nom} ignore : {e}")
            rapport.append((nom, "IGNORE", str(e)[:300]))
    if series:
        s = pd.concat(series, axis=1)
        s.index.name = "code"
        table = s.reset_index() if table.empty else table.merge(s.reset_index(), on="code", how="outer")
    return table, rapport


def main():
    try:
        table, rapport = construire(cfg.INDICATEURS_TBMD, cfg.DOSSIER_BRUT)
    except RuntimeError as e:  # aucun indicateur TBMD : on tente quand meme les couches geographiques
        table, rapport = pd.DataFrame({"code": []}), [("tbmd", "IGNORE", str(e)[:300])]
    try:
        geo, rapport_geo = indicateurs_geo(exporter.charger_communes(), cfg.DOSSIER_BRUT)
        table = couches.fusionner(table, geo)
        rapport += rapport_geo
    except Exception as e:  # noqa: BLE001 - les couches ne doivent jamais bloquer les indicateurs TBMD
        log(f"[!] couches geographiques ignorees : {e}")
        rapport.append(("couches", "IGNORE", str(e)[:300]))
    if table.empty:
        raise RuntimeError("aucun indicateur produit (TBMD et couches) : voir rapport.md et inspection.txt")
    g = grille_densite()
    rapport.append(("grille", "ok" if g is not None else "IGNORE", "filtre rural " + ("actif" if g is not None else "desactive")))
    if g is not None:
        table = table.merge(g, on="code", how="left")
    table.to_parquet(cfg.DOSSIER_BRUT / "indicateurs_communes.parquet")
    lignes = ["# Rapport du pipeline", "", "| indicateur | etat | detail |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in rapport]
    (cfg.DOSSIER_BRUT / "rapport.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    log(f"{len(table)} communes, {table.shape[1] - 1} colonnes")


if __name__ == "__main__":
    main()
