"""Relief : pente moyenne par commune (%), calculee sur le MNT Terrarium (tuiles PNG AWS, ~100 m a z10).
Pente faible = favorable au velo. Resultat mis en cache dans relief_pente.csv (les tuiles ne sont pas conservees)."""
import io
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from outils import log, percentile

ZOOM = 10
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
SEUIL_RAIDE = 6.0  # % : part de la surface plus raide que ce seuil (info de log)
CIRCONF = 40075016.686
ECHECS = []  # tuiles definitivement en echec


def num_tuile(lon, lat, z=ZOOM):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def emprise_3857(x, y, z=ZOOM):
    t = CIRCONF / 2 ** z
    return (-CIRCONF / 2 + x * t, CIRCONF / 2 - (y + 1) * t, -CIRCONF / 2 + (x + 1) * t, CIRCONF / 2 - y * t)


def telecharger_tuile(x, y, z=ZOOM):
    import requests
    for essai in range(4):
        try:
            r = requests.get(URL.format(z=z, x=x, y=y), timeout=60)
            if r.status_code == 404:
                return None  # tuile hors couverture (mer)
            r.raise_for_status()
            return r.content
        except Exception:  # noqa: BLE001
            if essai == 3:
                ECHECS.append((x, y))
    return None


def decoder(png):
    from PIL import Image
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype="float64")
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


def pente_pct(alt, x, y, z=ZOOM):
    """Pente (%) par pixel ; bordure de 1 pixel = NaN (pas de voisin)."""
    n = alt.shape[0]
    lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * (y + (np.arange(n) + 0.5) / n) / 2 ** z))))
    sol = CIRCONF / 2 ** z / n * np.cos(np.radians(lat))[:, None]  # metres par pixel (sol), par ligne
    dy, dx = np.gradient(alt)
    p = 100 * np.hypot(dx, dy) / sol
    p[[0, -1], :] = np.nan
    p[:, [0, -1]] = np.nan
    return p


def pente_par_commune(communes, tuile_png):
    """communes : GeoDataFrame [code, geometry] (EPSG:4326) ; tuile_png(x, y) -> bytes | None. Retourne Serie code -> pente moyenne (%)."""
    import rasterio.features
    from rasterio.transform import from_bounds
    from shapely.geometry import box
    g = communes[["code", "geometry"]].reset_index(drop=True).to_crs(3857)
    n = len(g)
    somme, nb, raide = np.zeros(n + 1), np.zeros(n + 1), np.zeros(n + 1)
    xmin, ymin, xmax, ymax = communes.total_bounds
    x0, y1 = num_tuile(xmin, ymin)
    x1, y0 = num_tuile(xmax, ymax)
    tuiles = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    sindex = g.sindex
    utiles = []
    for x, y in tuiles:
        if len(sindex.query(box(*emprise_3857(x, y)))):
            utiles.append((x, y))
    log(f"  {len(utiles)} tuiles MNT (z{ZOOM})")
    with ThreadPoolExecutor(12) as pool:
        for k, ((x, y), png) in enumerate(zip(utiles, pool.map(lambda t: tuile_png(*t), utiles))):
            if png is None:
                continue
            alt = decoder(png)
            p = pente_pct(alt, y=y, x=x)
            e = emprise_3857(x, y)
            idx = sindex.query(box(*e))
            ras = rasterio.features.rasterize(
                ((g.geometry.iloc[i], int(i) + 1) for i in idx), out_shape=p.shape, transform=from_bounds(*e, p.shape[1], p.shape[0]), fill=0, dtype="int32")
            ok = (ras > 0) & np.isfinite(p)
            ids, v = ras[ok], p[ok]
            somme += np.bincount(ids, weights=v, minlength=n + 1)
            nb += np.bincount(ids, minlength=n + 1)
            raide += np.bincount(ids, weights=(v >= SEUIL_RAIDE).astype(float), minlength=n + 1)
            if (k + 1) % 200 == 0:
                log(f"  {k + 1}/{len(utiles)} tuiles")
    if len(ECHECS) > 0.02 * max(1, len(utiles)):
        raise RuntimeError(f"{len(ECHECS)} tuiles MNT sur {len(utiles)} en echec : indicateur abandonne")
    if ECHECS:
        log(f"  [!] {len(ECHECS)} tuiles en echec (communes concernees : pente partielle)")
    nb[0] = np.nan
    res = pd.DataFrame({"code": g["code"], "pente": (somme / nb)[1:], "raide": (100 * raide / nb)[1:], "pixels": nb[1:]})
    return res[res["pixels"] >= 20].set_index("code")


def indicateur_relief(communes, dossier):
    """-> (Serie i_relief indexee par code, detail). Pente moyenne faible = score eleve."""
    cache = Path(dossier) / "relief_pente.csv"
    if cache.exists() and cache.stat().st_size > 0:
        res = pd.read_csv(cache, dtype={"code": str}).set_index("code")
        log(f"  relief : cache {cache.name}")
    else:
        res = pente_par_commune(communes, telecharger_tuile)
        res.to_csv(cache)
    s = percentile(-res["pente"]).rename("i_relief")
    return s, f"{len(res)} communes ; pente moyenne mediane {res['pente'].median():.1f} %, p90 {res['pente'].quantile(.9):.1f} %, part >= {SEUIL_RAIDE:.0f} % mediane {res['raide'].median():.0f} %"
