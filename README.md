# Potentiel vélo en milieu rural

App web (TypeScript + MapLibre) qui croise trois dimensions par commune :

| Axe | Question | Exemples d'indicateurs |
|---|---|---|
| **Usage** | Où le vélo peut-il être adopté ? | trajets courts, emploi local, compacité, relief, climat |
| **Faisabilité** | Où est-ce simple/sûr à aménager ? | routes calmes, lignes SNCF désaffectées, canaux, intermodalité, covoiturage, sécurité |
| **Déficit** | Où le réseau est-il en retard ? | linéaire cyclable et stationnement pour 1000 hab. |

Score = moyenne pondérée (poids réglables dans l'interface, de 0 à 5). Chaque indicateur est un rang percentile national 0-100, orienté « 100 = favorable ». Un indicateur absent des données est ignoré.

**Répartition du calcul** : le pré-calcul lourd (téléchargements, percentiles, contours, tuiles) tourne en Python dans GitHub Actions ; le score pondéré est calculé dans le navigateur (curseurs instantanés).

## Mise en ligne sur GitHub (dépôt public)

1. Créer le dépôt, y pousser ce dossier.
2. *Settings → Pages → Build and deployment → Source : **GitHub Actions***.
3. Onglet *Actions → pipeline-et-deploiement → Run workflow*.
4. Lire le résultat dans le **résumé du job** (état de chaque indicateur) et dans l'artefact `inspection-pipeline`.

**Premier lancement : prévoir un ajustement.** Les colonnes des fichiers du Tableau de bord des mobilités durables n'ont pas pu être vérifiées en amont. Un indicateur dont la colonne n'est pas trouvée est ignoré (signalé dans le résumé) ; si aucun n'est lu, le job échoue. Corriger alors les regex dans `pipeline/config.py` à partir de `inspection.txt`.

Le workflow : tests Python → pipeline → tuiles PMTiles (tippecanoe, compilé une fois puis mis en cache) → tests + build de l'app → déploiement. Il se relance chaque mois, à chaque push sur `main` touchant `app/`, `pipeline/` ou le workflow, ou à la main. Les données brutes sont mises en cache par mois.

## Lancer en local

```bash
# app (données de démonstration synthétiques fournies)
cd app && npm install && npm run dev      # http://localhost:5173
npm test                                  # moteur de score : calcul JS == expression MapLibre

# pipeline (Python 3.12+)
cd pipeline && pip install -r requirements.txt
python -m pytest -q                       # tests sur fichiers fictifs
python lancer.py                          # ou --etape telecharger | assembler | exporter
```

En local le pipeline produit `communes.geojson` (l'app l'utilise directement). Le mode PMTiles (national) est produit par le workflow ; localement, tippecanoe + un serveur compatible requêtes Range (`vite preview`, pas `python -m http.server`).

## Sources de données

- Tableau de bord des mobilités durables (Ecolab/CGDD, data.gouv.fr) : linéaire cyclable, stationnement vélo, distances et flux domicile-travail, emploi, densité, stations TC.
- Grille communale de densité INSEE à 7 niveaux (data.gouv.fr, jeu `6745d9ae4524d845d2138193`) : filtre « rural » (niveaux 5 à 7).
- Contours communaux : API geo.api.gouv.fr (ou fichier local via `CHEMIN_COMMUNES`).
- **Couches géographiques** (`pipeline/couches.py`, réglées dans `config.COUCHES`, agrégées par commune par découpage exact des lignes par les contours) :
  - lignes SNCF fermées / déclassées (SNCF Réseau, « Lignes par statut ») → km par commune ;
  - canaux et voies navigables → km par commune (jeu à confirmer au premier lancement) ;
  - aires de covoiturage (BNLC) → nombre par commune ;
  - BNAC (aménagements cyclables) et stationnements OSM (PVELO) → **remplacent** les agrégats TBMD de linéaire et de stationnement dès qu'ils sont lus (par 1000 hab.).
- **Sécurité** (`securite.py`) : accidents corporels BAAC des 5 dernières années pour 1000 hab. (plancher de population de 500 pour limiter le bruit des petites communes).
- **Routes calmes** (`routes_calmes.py`, OSM / extraits Geofabrik) : km de voies résidentielles, non classées, chemins et tertiaires ≤ 50 km/h par km². **Désactivé par défaut** car lourd : case `routes_calmes` du workflow, ou `ROUTES_CALMES=1` en local.
- Non encore couverts : relief (MNT, volontairement reporté), climat (SAFRAN), ménages par nombre de voitures.
- Les indicateurs « présence » (SNCF, canaux, covoiturage) valent 0 là où il n'y a rien, et de 20 à 100 selon la quantité ailleurs.
- Le premier lancement écrit `catalogue_couches.txt` (candidats data.gouv par couche) : s'en servir pour fixer `url` ou `dataset_id` dans `config.COUCHES` si une recherche automatique tombe sur le mauvais jeu.

## État et limites

- Vérifié : tests Python (13) et TypeScript (7), build, workflow validé par actionlint, rendu headless en modes GeoJSON et PMTiles.
- **Non vérifié** : schémas réels des nouvelles couches (noms de colonnes, statuts SNCF, identifiants de jeux), exécution sur les vraies données data.gouv.fr (réseau indisponible en développement) et déploiement GitHub Pages réel.
- Fond de carte : Plan IGN (Géoplateforme), nom de couche à vérifier ; modifiable via `fond` dans `config.json`.
- `i_gisement` utilise provisoirement la distance moyenne domicile-travail (à remplacer par la part des trajets < 5 km).
- Taille : GitHub Pages limite chaque fichier à 100 Mo ; le workflow échoue explicitement au-delà de 95 Mo pour les tuiles.
- Pas encore d'agrégation par EPCI. Seuils de lecture du « profil » (`score.ts`) indicatifs.
