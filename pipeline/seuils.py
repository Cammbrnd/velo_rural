"""Catalogue des seuils du pipeline -> app/public/data/seuils.json (page seuils.html). Valeurs lues dans le code : jamais recopiees."""
import json

import config as cfg
import exemples as ex
import relief
import routes_calmes as rc
from outils import log


def it(nom, valeur, role, fichier, unite=""):
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    return dict(nom=nom, valeur=str(valeur), unite=unite, role=role, fichier=fichier)


def virages():
    t = [f"{a}° et + : " + ("interdit" if p == float("inf") else f"{p:g} m") for a, p in ex.PENALITE_VIRAGE]
    return " ; ".join(t)


def catalogue():
    return [
        dict(titre="Indicateurs communaux", intro="Chaque indicateur est converti en rang percentile national (0 à 100, 100 = favorable).", items=[
            it("Gisement de trajets courts", cfg.INDICATEURS_TBMD["i_gisement"]["classes_max_km"], "Part des actifs dont le trajet domicile-travail est inférieur à cette distance.", "config.py", "km"),
            it("Vitesse maximale d'une route calme", rc.VITESSE_MAX, "Voie résidentielle, non classée ou tertiaire limitée à cette vitesse au plus.", "routes_calmes.py", "km/h"),
            it("Pistes (track) retenues", "grade1-2 ou revêtues", "Chemin agricole retenu seulement s'il est de bonne tenue.", "routes_calmes.py"),
            it("Indicateurs « présence »", "50 à 100", "Lignes SNCF désaffectées, canaux, covoiturage : 0 = commune non concernée (ignorée), sinon note de 50 à 100.", "outils.py"),
            it("Sécurité : période", cfg.BAAC["annees"], "Accidents corporels cumulés sur les dernières années disponibles.", "config.py", "ans"),
            it("Sécurité : population plancher", cfg.BAAC["pop_min"], "Les communes plus petites sont comptées avec cette population (taux pour 1 000 hab.).", "config.py", "hab."),
            it("Part de surface raide (info de log)", relief.SEUIL_RAIDE, "Part de la surface communale plus raide que ce seuil ; indicateur de diagnostic, hors score.", "relief.py", "%"),
        ]),
        dict(titre="Choix des EPCI d'exemple", intro="20 EPCI ruraux répartis sur le territoire, plus tous les EPCI de l'Allier.", items=[
            it("Nombre d'EPCI ruraux", ex.NB_EPCI, "Choisis un par département, en maximisant l'éloignement.", "exemples.py"),
            it("Communes par EPCI", f"{ex.EPCI_COMMUNES[0]} à {ex.EPCI_COMMUNES[1]}", "Taille raisonnable pour un réseau d'exemple.", "exemples.py", "communes"),
            it("Part de communes rurales", f"≥ {ex.RURAL_MIN:.0%}", "Grille de densité 5 à 7.", "exemples.py"),
            it("Étendue maximale", ex.EPCI_ETENDUE_MAX_KM, "Diagonale de l'EPCI.", "exemples.py", "km"),
            it("Population du pôle", f"{ex.HUB_MIN:,} à {ex.HUB_MAX:,}".replace(",", " "), "Commune la plus peuplée : un bourg, pas une ville.", "exemples.py", "hab."),
            it("Population de l'EPCI", f"≥ {ex.EPCI_POP_MIN:,}".replace(",", " "), "", "exemples.py", "hab."),
            it("Relief moyen", f"≥ {ex.RELIEF_MIN:g}", "Indicateur de relief (100 = plat) : exclut la haute montagne.", "exemples.py", "/100"),
            it("Département traité en entier", f"> {ex.DEP_PART_MIN:.0%} des communes dans le département, ≥ {ex.DEP_COMMUNES_MIN} communes", "Allier (03).", "exemples.py"),
        ]),
        dict(titre="Coût d'un chemin (tracés)", intro="Les tracés sont les plus courts chemins selon un coût, pas selon la distance.", items=[
            it("Facteur de coût par type de voie", ", ".join(f"{k} ×{v:g}" for k, v in ex.FACTEUR.items()), "Aménagement existant moins cher, route à sécuriser plus chère.", "exemples.py"),
            it("Coût de la montée", ex.COUT_MONTEE, "Mètres de coût par mètre de dénivelé positif.", "exemples.py", "m/m"),
            it("Pente de référence", f"{ex.PENTE_REF:.0%}", "Au-delà, le coût d'une portion double, puis croît au carré.", "exemples.py"),
            it("Pente maximale d'une portion", f"{ex.PENTE_MAX_ARETE:.0%}", "Portion plus raide (sur ≥ %d m) : exclue." % ex.L_MIN_PENTE, "exemples.py"),
            it("Changement de route", ex.PENALITE_CHANGEMENT, "Pénalité à chaque changement de nom / numéro de voie : évite les zigzags.", "exemples.py", "m"),
            it("Changement lié à un aménagement existant", ex.PENALITE_CHANGEMENT_PISTE, "Raccord à une piste existante : pénalité réduite.", "exemples.py", "m"),
            it("Virages", virages(), "Angle de changement de direction.", "exemples.py"),
            it("Centre-bourg", f"rayon {ex.RAYON_BOURG_M} m, coût ×{ex.FACTEUR_BOURG:g}", "Les tracés traversent les villages.", "exemples.py"),
            it("Partage d'un tronc", f"coût ×{ex.FACTEUR_PARTAGE:g}, {ex.PASSES_PARTAGE} passes", "Les branches empruntent le même tronc plutôt que de longer en parallèle.", "exemples.py"),
        ]),
        dict(titre="Acceptation d'un tracé", intro="Un chemin vers une commune est rejeté s'il dépasse l'un de ces seuils.", items=[
            it("Longueur maximale", ex.LONGUEUR_MAX_M / 1000, "Par la route, depuis le pôle.", "exemples.py", "km"),
            it("Détour maximal", ex.DETOUR_MAX, "Longueur par la route / distance à vol d'oiseau.", "exemples.py"),
            it("Pente maximale sur 500 m", f"{ex.PENTE_MAX_500M:.0%}", "Plus forte pente moyenne sur 500 m glissants.", "exemples.py"),
            it("Montée cumulée maximale", ex.MONTEE_MAX_M_KM, "", "exemples.py", "m/km"),
            it("Changements de route maximum", ex.CHANGEMENTS_MAX_KM, "", "exemples.py", "par km"),
            it("Rayon de desserte", ex.RAYON_DESSERTE_M, "Une commune est desservie si le tracé passe à moins de cette distance de son centre-bourg.", "exemples.py", "m"),
            it("Accrochage au réseau", ex.SNAP_MAX_M, "Distance maximale entre le centre-bourg et la voie la plus proche.", "exemples.py", "m"),
        ]),
        dict(titre="Priorités et liaisons", intro="Combien de tracés, vers quoi, et comment les villages sont reliés entre eux.", items=[
            it("Branches par EPCI", ex.NB_TRACES, "Les branches les plus pertinentes du réseau.", "exemples.py"),
            it("Longueur nouvelle minimale d'une branche", ex.LONGUEUR_MIN_M, "", "exemples.py", "m"),
            it("Gros villages prioritaires par EPCI", ex.NB_GROS_EPCI, "Servis par les premières branches retenues.", "exemples.py", "villages"),
            it("Poids d'une commune", "population × score/100 × max(1 ; pop/1000)", "Les gros villages pèsent plus que proportionnellement.", "exemples.py"),
            it("Piste existante à rejoindre", f"≥ {ex.PISTE_MIN_M / 1000:g} km", f"Poids {ex.POIDS_PISTE_PAR_KM:g} par km, plafonné à 10 km.", "exemples.py"),
            it("Gros village (liaisons)", f"≥ {ex.GROS_VILLAGE_HAB:,}".replace(",", " "), "Villages et pôles d'EPCI reliés entre eux dans le département traité.", "exemples.py", "hab."),
            it("Voisins reliés", f"2 plus proches à moins de {ex.VOISIN_GROS_KM:g} km", "En plus de l'arbre couvrant minimal.", "exemples.py"),
            it("Longueur maximale d'une liaison", ex.LIAISON_MAX_KM, "Détour jusqu'à 2,0 pour une liaison.", "exemples.py", "km"),
        ]),
    ]


def main():
    try:
        cfg.DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)
        f = cfg.DOSSIER_SORTIE / "seuils.json"
        f.write_text(json.dumps(catalogue(), ensure_ascii=False), encoding="utf-8")
        log(f"ecrit {f}")
    except Exception as e:  # noqa: BLE001
        log(f"[!] seuils.json non ecrit : {type(e).__name__} {e}")


if __name__ == "__main__":
    main()
