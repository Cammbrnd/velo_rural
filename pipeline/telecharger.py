"""Etape 1 : telecharge les ressources csv des jeux TBMD retenus + ecrit un fichier d'inspection."""
import re

import config as cfg
from outils import choisir_ressource, lire_csv, lister_datasets_org, log, rechercher_datasets, telecharger


def catalogue_couches():
    """Candidats data.gouv pour chaque couche sans url fixee (titre, organisation, formats) : aide a regler config.COUCHES."""
    lignes = []
    requetes = {n: c["recherche"] for n, c in cfg.COUCHES.items() if c.get("recherche") and not c.get("url")}
    requetes["baac"] = "bases de donnees annuelles des accidents corporels de la circulation routiere"
    requetes["voies_vertes_sncf"] = "lignes ferroviaires desaffectees voies vertes"
    for nom, q in requetes.items():
        lignes.append(f"=== {nom} : recherche '{q}'")
        try:
            for d in rechercher_datasets(q, n=6):
                fm = ", ".join(sorted({r["format"] for r in d["ressources"] if r["format"]}))
                lignes.append(f"- {d['titre']} | {d['org']} | id {d['id']} | formats : {fm}")
        except Exception as e:  # noqa: BLE001
            lignes.append(f"  ECHEC : {e}")
        lignes.append("")
    (cfg.DOSSIER_BRUT / "catalogue_couches.txt").write_text("\n".join(lignes), encoding="utf-8")
    log("catalogue des couches ecrit : donnees_brutes/catalogue_couches.txt")


def main():
    cfg.DOSSIER_BRUT.mkdir(exist_ok=True)
    catalogue_couches()
    catalogue = lister_datasets_org(cfg.ORG_TBMD)
    log(f"{len(catalogue)} jeux de donnees dans l'organisation TBMD")
    (cfg.DOSSIER_BRUT / "catalogue_tbmd.txt").write_text("\n".join(d["titre"] for d in catalogue), encoding="utf-8")

    inspection = []
    for nom, c in cfg.INDICATEURS_TBMD.items():
        ds = [d for d in catalogue if re.search(c["dataset"], d["titre"], re.I)]
        if not ds:
            log(f"[!] {nom} : aucun jeu ne correspond a '{c['dataset']}'")
            inspection.append(f"=== {nom} : AUCUN JEU pour '{c['dataset']}'\n")
            continue
        if len(ds) > 1:
            log(f"    {nom} : {len(ds)} jeux correspondent, utilisation de '{ds[0]['titre']}'")
        log(f"-> {nom} : {ds[0]['titre']}")
        try:
            res = choisir_ressource(ds[0]["id"], c.get("ressource"))
            f = telecharger(res["url"], cfg.DOSSIER_BRUT / f"{nom}.csv")
            df = lire_csv(f)
        except Exception as e:  # noqa: BLE001 - on continue avec les autres indicateurs
            log(f"[!] {nom} : {e}")
            inspection.append(f"=== {nom} : ECHEC {e}\n")
            continue
        inspection += [f"=== {nom} | {ds[0]['titre']} | {len(df)} lignes", "colonnes : " + " | ".join(df.columns), df.head(3).to_string(), ""]
    (cfg.DOSSIER_BRUT / "inspection.txt").write_text("\n".join(inspection), encoding="utf-8")
    log("inspection ecrite : donnees_brutes/inspection.txt")


if __name__ == "__main__":
    main()
