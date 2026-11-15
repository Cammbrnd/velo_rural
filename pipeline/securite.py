"""Securite routiere : accidents corporels (BAAC, ONISR) par commune sur les N dernieres annees, pour 1000 habitants."""
import re

import pandas as pd

import config as cfg
from outils import API, api_get, lire_csv, log, percentile, telecharger, trouver_col, vers_nombre


def code_commune(df):
    """Code INSEE sur 5 caracteres : colonne `com` complete, ou departement + 3 derniers chiffres (anciens millesimes)."""
    com = df[trouver_col(df, r"^com$", "com")].astype(str).str.strip()
    dep = df[trouver_col(df, r"^dep$", "dep")].astype(str).str.strip()
    complet = com.str.len() >= 5
    dep2 = dep.str.zfill(2).str.replace(r"^(\d{2})0$", r"\1", regex=True)  # '010' -> '01' (anciens millesimes)
    return com.where(complet, dep2 + com.str.zfill(3).str[-3:])


def accidents_par_commune(tables):
    """tables : liste de DataFrames `caracteristiques` -> Serie nb d'accidents par code commune."""
    codes = pd.concat([code_commune(t) for t in tables])
    return codes[codes.str.len() == 5].value_counts()


def ressources_caracteristiques(dataset_id):
    d = api_get(f"{API}/datasets/{dataset_id}/")
    out = []
    for r in d.get("resources", []):
        m = re.search(r"caract[ée]ristiques.*?(20\d{2})", (r.get("title") or "") + " " + (r.get("url") or ""), re.I)
        if m and (r.get("format") or "").lower() == "csv":
            out.append((int(m.group(1)), r["url"]))
    return sorted(set(out), reverse=True)


def indicateur_securite(communes, dossier, c=None):
    c = c or cfg.BAAC
    res = ressources_caracteristiques(c["dataset_id"])[: c["annees"]]
    if not res:
        raise RuntimeError("aucune ressource 'caracteristiques-AAAA' trouvee dans le jeu BAAC")
    log(f"  BAAC annees : {[a for a, _ in res]}")
    tables = [lire_csv(telecharger(u, dossier / f"baac_caracteristiques_{a}.csv")) for a, u in res]
    n = accidents_par_commune(tables).reindex(communes["code"].values).fillna(0.0)
    pop = pd.Series(communes["pop"].values, index=communes["code"].values).clip(lower=c["pop_min"])
    taux = n / (pop / 1000.0)
    s = percentile(-taux).rename("i_securite")  # peu d'accidents = score eleve
    return s, f"{int(n.sum())} accidents sur {len(res)} annees, {int((n > 0).sum())} communes concernees"
