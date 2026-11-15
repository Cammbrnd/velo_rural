"""Configuration du pipeline. Noms de fichiers en minuscules, sans accents dans le code."""
import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent
DOSSIER_BRUT = RACINE / "donnees_brutes"
DOSSIER_SORTIE = RACINE.parent / "app" / "public" / "data"
FICHIER_CONFIG_APP = RACINE.parent / "app" / "public" / "config.json"

# Organisation data.gouv.fr "Tableau de bord des mobilites durables" (pilotee par l'Ecolab)
ORG_TBMD = "67c5ea43c8e7b1f1830d4739"

# Contours communaux : fichier local (gpkg/shp/geojson) ou None -> geo.api.gouv.fr
CHEMIN_COMMUNES = os.environ.get("CHEMIN_COMMUNES") or None

# Grille communale de densite INSEE (7 niveaux) : jeu data.gouv.fr (colonnes grille_densite, annee...)
ID_DATASET_GRILLE = "6745d9ae4524d845d2138193"
# Surcharge possible : URL ou chemin local d'un csv/xlsx (colonnes code commune + grille)
SURCHARGE_GRILLE = os.environ.get("GRILLE_DENSITE") or None

# Tolerance de simplification des contours (degres ; 0.0004 ~ 45 m)
SIMPLIFICATION_DEG = 0.0004

# dataset   : regex sur le titre du jeu (organisation TBMD)
# ressource : regex sur le titre de la ressource (None = premiere ressource csv)
# valeur    : regex du nom de la colonne de valeur (la premiere qui correspond)
# filtre    : (regex nom de colonne, regex valeur) pour isoler un sous-ensemble de lignes
# transfo   : "haut" = valeur elevee => score eleve ; "bas" = valeur faible => score eleve
# NB : a valider avec donnees_brutes/inspection.txt apres le 1er telechargement.
INDICATEURS_TBMD = {
    "i_deficit_lineaire": dict(dataset=r"Lin[ée]aire cyclable", valeur=r"total|ensemble|lineaire", transfo="bas"),
    "i_deficit_stationnement": dict(dataset=r"stationnement v[ée]lo", valeur=r"places|stationnement|nb", transfo="bas"),
    "i_compacite": dict(dataset=r"Densit[ée] de population", valeur=r"densit", transfo="haut"),
    "i_emploi_local": dict(dataset=r"concentration de l.emploi", valeur=r"indice|concentration|icem", transfo="haut"),
    "i_intermodalite": dict(dataset=r"stations de transports en commun", valeur=r"total|ensemble|nb|stations", transfo="haut"),
    # Proxy provisoire du "gisement" : distance domicile-travail moyenne tous modes (courte = favorable).
    # A remplacer par la part des trajets < 5 km (jeu "classe de distance") apres inspection.
    "i_gisement": dict(dataset=r"Distance moyenne domicile-travail", valeur=r"distance|moyenne|dist",
                       filtre=(r"mode", r"ensemble|tous|total"), transfo="bas"),
}
# Prevus mais non produits ici : i_relief (MNT), i_climat (SAFRAN), i_routes_calmes (BD TOPO/OSM),
# i_securite (BAAC), i_peu_motorises. L'application ignore tout indicateur absent.


# ---------------------------------------------------------------------------------------------
# Couches geographiques agregees par commune (couches.py). Cle = nom de l'indicateur produit.
# Source : `url` (prioritaire) > `dataset_id` data.gouv > recherche plein texte (`recherche`, titre filtre par `titre`).
# mode    : "longueur" (km de lignes dans la commune) | "points" (nombre d'objets)
# transfo : "presence" (0 reste 0, >0 classe de 20 a 100) | "haut" | "bas" (percentile oriente)
# par_habitant : divise par la population (pour 1000 hab, plancher `pop_min`)
# Les schemas reels ne sont pas verifies : lire donnees_brutes/catalogue_couches.txt et rapport.md apres le 1er run.
# Une couche qui porte le nom d'un indicateur TBMD (i_deficit_*) le REMPLACE lorsqu'elle est lue.
# ---------------------------------------------------------------------------------------------
COUCHES = {
    # Lignes ferroviaires desaffectees / declassees : emprises mobilisables en voie verte
    "i_emprises_ferrees": dict(
        url=os.environ.get("URL_SNCF_STATUT") or "https://data.sncf.com/api/explore/v2.1/catalog/datasets/lignes-par-statut/exports/geojson",
        mode="longueur", transfo="presence",
        filtre=(r"statut|etat|situation", r"ferm|d[ée]class|d[ée]saffect|neutralis|non.?exploit|d[ée]pos"),
    ),
    # Canaux et rivieres navigables : chemins de halage (potentiel voie verte). Reseau VNF : a confirmer au 1er run.
    "i_canaux": dict(
        url=os.environ.get("URL_CANAUX") or None,
        recherche=r"voies? navigables? voies? d.eau", titre=r"navigable|canaux|canal|VNF",
        mode="longueur", transfo="presence",
    ),
    # Base nationale des lieux de covoiturage (BNLC) : intermodalite velo + covoiturage
    "i_covoiturage": dict(
        dataset_id="5d6eaffc8b4c417cdc452ac3", formats=("csv",), mode="points", col_code=r"insee", transfo="presence",
    ),
    # BNAC : amenagements cyclables reels -> remplace le lineaire TBMD (km pour 1000 hab, peu = deficit eleve)
    "i_deficit_lineaire": dict(
        url=os.environ.get("URL_BNAC") or None,
        recherche=r"amenagements cyclables france metropolitaine", titre=r"am[ée]nagements? cyclables?",
        mode="longueur", transfo="bas", par_habitant=True,
    ),
    # Stationnements velo OSM (PVELO) : remplace le stationnement TBMD (places pour 1000 hab)
    "i_deficit_stationnement": dict(
        url=os.environ.get("URL_STATIONNEMENT") or None,
        recherche=r"stationnements cyclables", titre=r"stationnements? (cyclables?|v[ée]los?)",
        formats=("geojson", "json", "gpkg", "csv", "zip"), mode="points", transfo="bas", par_habitant=True,
    ),
}

# Securite routiere (BAAC, ONISR) : accidents corporels sur les N dernieres annees pour 1000 habitants
BAAC = dict(dataset_id="53698f4ca3a729239d2036df", annees=5, pop_min=500)

# Routes calmes (OSM, extraits regionaux Geofabrik) : lourd (plusieurs Go) -> desactive par defaut.
# Activer avec ROUTES_CALMES=1 (workflow : entree `routes_calmes`).
ROUTES_CALMES = os.environ.get("ROUTES_CALMES") == "1"
GEOFABRIK = "https://download.geofabrik.de/europe/france"
REGIONS_GEOFABRIK = [
    "alsace", "aquitaine", "auvergne", "basse-normandie", "bourgogne", "bretagne", "centre", "champagne-ardenne",
    "corse", "franche-comte", "haute-normandie", "ile-de-france", "languedoc-roussillon", "limousin", "lorraine",
    "midi-pyrenees", "nord-pas-de-calais", "pays-de-la-loire", "picardie", "poitou-charentes",
    "provence-alpes-cote-d-azur", "rhone-alpes",
]
