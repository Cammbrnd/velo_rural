import io
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from PIL import Image
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import relief  # noqa: E402


def png_plan(pente_x, x, y):
    """Tuile Terrarium dont l'altitude monte de `pente_x` (m/m) vers l'est."""
    sol = relief.CIRCONF / 2 ** relief.ZOOM / 256 * np.cos(np.radians(46.0))
    alt = pente_x * sol * np.arange(256)[None, :] * np.ones((256, 1)) + 500
    v = alt + 32768
    rgb = np.stack([np.floor(v / 256), np.floor(v) % 256, np.floor((v - np.floor(v)) * 256)], axis=-1).astype("uint8")
    b = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(b, format="PNG")
    return b.getvalue()


def test_pente_par_commune_plan_incline():
    x, y = relief.num_tuile(3.0, 46.0)
    e = relief.emprise_3857(x, y)
    from pyproj import Transformer
    t = Transformer.from_crs(3857, 4326, always_xy=True)
    cx, cy = t.transform((e[0] + e[2]) / 2, (e[1] + e[3]) / 2)
    communes = gpd.GeoDataFrame({"code": ["A"], "geometry": [box(cx - 0.05, cy - 0.03, cx + 0.05, cy + 0.03)]}, crs=4326)
    res = relief.pente_par_commune(communes, lambda xx, yy: png_plan(0.05, xx, yy) if (xx, yy) == (x, y) else None)
    assert res.loc["A", "pente"] == pytest.approx(5.0, rel=0.08)
    assert res.loc["A", "raide"] < 5  # pente 5 % < seuil 6 %
