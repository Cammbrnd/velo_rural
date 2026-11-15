"""Controle qualite des indicateurs (lecture seule) : couverture, distributions, correlations, sensibilite aux poids.
Imprime dans le log et complete rapport.md (donc le resume du job). Ne bloque jamais le pipeline."""
import re

import numpy as np
import pandas as pd

import config as cfg
import exporter
from outils import log

TS = cfg.RACINE.parent / "app" / "src" / "indicators.ts"


def poids_ts():
    """Lit axes et poids par defaut dans app/src/indicators.ts (source unique) -> ({id: (axe, poids)}, {axe: poids})."""
    s = TS.read_text(encoding="utf-8")
    ind = {m[0]: (m[1], int(m[2])) for m in re.findall(r'id: "(i_\w+)", axe: "(\w+)".*?poids: (\d+)', s)}
    axes = {m[0]: int(m[1]) for m in re.findall(r'id: "(usage|faisabilite|deficit)",\s*label: "[^"]*",\s*poids: (\d+)', s)}
    return ind, axes


def moy_ponderee(X, w):
    """Moyenne ponderee ligne a ligne ; une valeur absente est ignoree (meme logique que score.ts)."""
    cols = [c for c in X.columns if w.get(c, 0) > 0]
    if not cols:
        return pd.Series(np.nan, index=X.index)
    W = pd.Series({c: float(w[c]) for c in cols})
    V = X[cols]
    den = V.notna().mul(W).sum(axis=1)
    num = V.fillna(0).mul(W).sum(axis=1)
    return (num / den).where(den > 0)


def score_global(df, ind, axes, wi=None, wa=None):
    wi = wi or {k: v[1] for k, v in ind.items()}
    wa = wa or axes
    sa = {a: moy_ponderee(df[[k for k, v in ind.items() if v[0] == a and k in df.columns]], wi) for a in axes}
    sa = pd.DataFrame(sa, index=df.index)
    return moy_ponderee(sa, wa), sa


def md(t):
    t = t.reset_index()
    lignes = ["| " + " | ".join(map(str, t.columns)) + " |", "|" + "---|" * len(t.columns)]
    lignes += ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in t.itertuples(index=False)]
    return "\n".join(lignes)


def rapport_controle(table, pop):
    ind, axes = poids_ts()
    cols = [k for k in ind if k in table.columns]
    t = table.set_index("code")
    rural = t[t["grille"].between(5, 7)] if "grille" in t.columns else t
    nom_pop = "grille 5-7" if "grille" in t.columns else "toutes (grille absente)"
    out = [f"## Controle des indicateurs (communes rurales : {nom_pop}, {len(rural)} sur {len(t)})", ""]
    lp = np.log10(pop.reindex(rural.index).clip(lower=1))
    r = rural[cols]
    q = pd.DataFrame({
        "axe": [ind[c][0] for c in cols], "poids": [ind[c][1] for c in cols],
        "%renseigne": (r.notna().mean() * 100).round(0).values,
        "%a_0": ((r == 0).sum() / r.notna().sum() * 100).round(0).values,
        "moy": r.mean().round(1).values, "p10": r.quantile(.1).round(0).values, "p50": r.quantile(.5).round(0).values,
        "p90": r.quantile(.9).round(0).values, "corr_logpop": [round(r[c].rank().corr(lp.rank()), 2) for c in cols],
    }, index=cols)
    out += ["### Couverture et distribution (echelle percentile nationale, communes rurales)", md(q), ""]
    out += ["### Correlations de rang entre indicateurs (rurales)", md(r.rank().corr().round(2)), ""]
    g, sa = score_global(rural, ind, axes)
    ax = pd.DataFrame({"p10": sa.quantile(.1), "p50": sa.quantile(.5), "p90": sa.quantile(.9), "%renseigne": sa.notna().mean() * 100}).round(1)
    out += ["### Scores d'axe (poids par defaut)", md(ax), "", "Correlations de rang entre axes et score global :",
            md(pd.concat([sa, g.rename("global")], axis=1).rank().corr().round(2)), ""]
    sens = {"poids egaux": score_global(rural, ind, axes, {k: 1 for k in ind}, {a: 1 for a in axes})[0].rank().corr(g.rank())}
    for c in cols:
        w = {k: (0 if k == c else v[1]) for k, v in ind.items()}
        sens[f"sans {c}"] = score_global(rural, ind, axes, w)[0].rank().corr(g.rank())
    for a in axes:
        sens[f"sans axe {a}"] = score_global(rural, ind, axes, None, {k: (0 if k == a else v) for k, v in axes.items()})[0].rank().corr(g.rank())
    s = pd.Series(sens).round(3).sort_values().rename("rho_vs_defaut")
    out += ["### Sensibilite : correlation de rang du score global avec la variante (bas = indicateur influent)", md(s.to_frame()), ""]
    imp = pd.Series({c: round(r[c].rank().corr(g.rank()), 2) for c in cols}, name="rho_avec_score_global").sort_values()
    out += ["### Lien de chaque indicateur avec le score global", md(imp.to_frame()), ""]
    n = r.notna().sum(axis=1).value_counts().sort_index()
    out += ["### Nombre d'indicateurs renseignes par commune rurale", md(n.rename("communes").to_frame()), ""]
    return out


def main():
    try:
        table = pd.read_parquet(cfg.DOSSIER_BRUT / "indicateurs_communes.parquet")
        c = exporter.charger_communes()
        pop = pd.Series(c["pop"].values, index=c["code"].astype(str).values)
        lignes = rapport_controle(table, pop)
        for l in lignes:
            log(l)
        with open(cfg.DOSSIER_BRUT / "rapport.md", "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(lignes) + "\n")
    except Exception as e:  # noqa: BLE001 - le controle ne doit jamais bloquer le pipeline
        log(f"[!] controle ignore : {e}")


if __name__ == "__main__":
    main()
