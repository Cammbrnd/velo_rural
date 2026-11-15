import io
import re
import sys

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = "https://www.data.gouv.fr/api/1"
_session = requests.Session()
_session.headers["User-Agent"] = "velo-rural-potentiel"
_session.mount("https://", HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])))


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def api_get(url, **params):
    r = _session.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def lister_datasets_org(org_id):
    """Retourne [{id, titre}] pour tous les jeux d'une organisation data.gouv.fr."""
    out, page = [], 1
    while True:
        j = api_get(f"{API}/datasets/", organization=org_id, page_size=100, page=page)
        out += [{"id": d["id"], "titre": d["title"]} for d in j["data"]]
        if not j.get("next_page"):
            return out
        page += 1


def choisir_ressource(dataset_id, ressource=None, formats=("csv",)):
    """Premiere ressource dont le format est dans `formats` (et dont le titre correspond a `ressource`)."""
    d = api_get(f"{API}/datasets/{dataset_id}/")
    rs = [r for r in d.get("resources", []) if (r.get("format") or "").lower() in formats]
    if ressource:
        rs = [r for r in rs if re.search(ressource, r.get("title") or "", re.I)]
    if not rs:
        raise RuntimeError(f"aucune ressource {formats} pour le jeu {dataset_id}")
    if len(rs) > 1:
        log(f"  {len(rs)} ressources, utilisation de : {rs[0].get('title')}")
    return {"titre": rs[0].get("title"), "url": rs[0]["url"], "format": rs[0].get("format")}


def rechercher_datasets(q, n=8):
    """Recherche plein texte dans le catalogue data.gouv.fr -> [{id, titre, org, ressources:[{titre,format,url}]}]."""
    j = api_get(f"{API}/datasets/", q=q, page_size=n)
    out = []
    for d in j["data"]:
        org = (d.get("organization") or {}).get("name") or ""
        rs = [{"titre": r.get("title"), "format": (r.get("format") or "").lower(), "url": r.get("url")} for r in d.get("resources", [])]
        out.append({"id": d["id"], "titre": d["title"], "org": org, "ressources": rs})
    return out


def telecharger(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _session.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for bloc in r.iter_content(1 << 20):
                f.write(bloc)
    return dest


def lire_csv(chemin):
    """Lecture tolerante : separateur detecte, encodage utf-8 puis latin-1, tout en texte."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(chemin, sep=None, engine="python", dtype=str, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"encodage illisible : {chemin}")


def trouver_col(df, regex, quoi):
    for c in df.columns:
        if re.search(regex, str(c), re.I):
            return c
    raise KeyError(f"colonne '{quoi}' introuvable (regex '{regex}'). Colonnes disponibles : {', '.join(map(str, df.columns))}")


def vers_nombre(serie):
    return pd.to_numeric(serie.astype(str).str.replace(",", ".", regex=False).str.replace(r"\s", "", regex=True), errors="coerce")


def percentile_presence(serie):
    """Pour les indicateurs 'presence' (km, nombre d'objets) : 0 reste 0, les valeurs > 0 occupent 20-100.
    Evite que la masse des communes a 0 obtienne un percentile median."""
    s = serie.astype(float)
    pos = s > 0
    out = pd.Series(0.0, index=s.index)
    out[pos] = (20 + 80 * s[pos].rank(pct=True, method="average")).round(1)
    out[s.isna()] = float("nan")
    return out


def percentile(serie):
    """Rang percentile 0-100 (100 = valeur la plus elevee). NaN conserves."""
    return (serie.rank(pct=True, method="average") * 100).round(1)
