"""Apercus PNG des exemples (un par EPCI) pour verification visuelle : python apercu.py <dossier de sortie>"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import config as cfg  # noqa: E402
import exporter  # noqa: E402
from exemples import table_epci  # noqa: E402

COUL = {"existant": "#1a9850", "calme": "#f2a900", "a_securiser": "#d7191c"}


def main(sortie):
    sortie = Path(sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    gj = json.loads((cfg.DOSSIER_SORTIE / "exemples.geojson").read_text(encoding="utf-8"))
    ex = gpd.GeoDataFrame.from_features(gj["features"], crs=4326).to_crs(2154)
    carte = exporter.charger_communes()
    carte["code"] = carte["code"].astype(str)
    carte = carte.merge(table_epci(), on="code", how="left").to_crs(2154)
    f = cfg.DOSSIER_BRUT / "pistes.geojson"
    pistes = gpd.read_file(f).to_crs(2154) if f.exists() else None
    for epci, t in ex.groupby("epci"):
        coms = carte[carte.epci == epci]
        x0, y0, x1, y1 = coms.total_bounds
        m = 2500
        fig, ax = plt.subplots(figsize=(10, 10 * (y1 - y0 + 2 * m) / (x1 - x0 + 2 * m)), dpi=90)
        carte.cx[x0 - m:x1 + m, y0 - m:y1 + m].plot(ax=ax, color="#ece8dc", edgecolor="#bbbbbb", linewidth=0.4)
        coms.plot(ax=ax, color="#f6f3ea", edgecolor="#777777", linewidth=0.8)
        if pistes is not None:
            p = pistes.cx[x0 - m:x1 + m, y0 - m:y1 + m]
            p[p["type"] == "bande"].plot(ax=ax, color="#c9a3d6", linewidth=1.0)
            p[p["type"] == "piste"].plot(ax=ax, color="#7b2d8e", linewidth=1.6)
        for cat, col in COUL.items():
            s = t[(t["type"] == "trace") & (t["categorie"] == cat)]
            if len(s):
                s.plot(ax=ax, color=col, linewidth=3.2)
        for r in coms.itertuples():
            pt = r.geometry.representative_point()
            ax.annotate(r.nom, (pt.x, pt.y), fontsize=6, ha="center", color="#333333")
        pole = t[t["type"] == "pole"]
        pole.plot(ax=ax, color="black", marker="*", markersize=180, zorder=5)
        info = t[t["type"] == "pole"].iloc[0]
        ax.set_title(f"{info['epci_nom']} - pole {info['pole']} - {info['communes_reliees']}/{info['communes_epci']} communes reliees", fontsize=9)
        ax.set_xlim(x0 - m, x1 + m)
        ax.set_ylim(y0 - m, y1 + m)
        ax.set_axis_off()
        fig.savefig(sortie / f"{epci}.png", bbox_inches="tight")
        plt.close(fig)
        print("apercu", epci)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "apercu")
