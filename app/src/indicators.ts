// Catalogue des indicateurs. Chaque indicateur est normalise 0-100 par le pipeline
// (rang percentile national), ORIENTE : 100 = situation la plus favorable pour l'axe.
// Un indicateur absent des donnees est simplement ignore dans le calcul.

export type Axe = "usage" | "faisabilite" | "deficit";

export interface Indicateur {
  id: string;
  axe: Axe;
  label: string;
  poids: number; // poids par defaut (0 = desactive)
  description: string;
  source: string;
}

export const AXES: { id: Axe; label: string; poids: number; description: string }[] = [
  {
    id: "usage",
    label: "Potentiel d'usage",
    poids: 3,
    description: "Gisement de déplacements réalisables à vélo (distances, emploi local, relief, climat).",
  },
  {
    id: "faisabilite",
    label: "Faisabilité d'aménagement",
    poids: 2,
    description: "Facilité à équiper ou sécuriser le territoire (routes calmes, emprises ferrées et canaux, intermodalité, sécurité).",
  },
  {
    id: "deficit",
    label: "Déficit d'équipement",
    poids: 2,
    description: "Retard de la commune en linéaire cyclable et stationnement : plus il est fort, plus le besoin est élevé.",
  },
];

export const INDICATEURS: Indicateur[] = [
  // --- usage ---
  { id: "i_gisement", axe: "usage", label: "Gisement de trajets courts", poids: 3,
    description: "Part des actifs dont le trajet domicile-travail fait moins de 5 km", source: "TBMD / INSEE RP" },
  { id: "i_emploi_local", axe: "usage", label: "Emploi local", poids: 2,
    description: "Indice de concentration de l'emploi (emplois pour 100 actifs résidents)", source: "TBMD / INSEE" },
  { id: "i_compacite", axe: "usage", label: "Compacité du peuplement", poids: 2,
    description: "Densité de population", source: "TBMD / INSEE" },
  { id: "i_peu_motorises", axe: "usage", label: "Ménages peu motorisés", poids: 1,
    description: "Part des ménages avec 0 ou 1 voiture", source: "TBMD / INSEE" },
  { id: "i_relief", axe: "usage", label: "Relief favorable", poids: 2,
    description: "Pente moyenne communale (faible pente = favorable)", source: "MNT IGN (RGE ALTI)" },
  { id: "i_climat", axe: "usage", label: "Climat favorable", poids: 1,
    description: "Nombre de jours de pluie et de gel (faible = favorable)", source: "Meteo-France / SAFRAN" },
  // --- faisabilite ---
  { id: "i_routes_calmes", axe: "faisabilite", label: "Routes secondaires calmes", poids: 3,
    description: "Kilomètres de voies secondaires peu rapides par km² (résidentielles, non classées, tertiaires ≤ 50 km/h)", source: "OSM (Geofabrik)" },
  { id: "i_emprises_ferrees", axe: "faisabilite", label: "Lignes SNCF désaffectées", poids: 2,
    description: "Kilomètres de lignes fermées ou déclassées dans la commune (voie verte potentielle)", source: "SNCF Réseau" },
  { id: "i_canaux", axe: "faisabilite", label: "Canaux et voies navigables", poids: 1,
    description: "Kilomètres de canaux dans la commune (chemin de halage potentiel)", source: "VNF / data.gouv" },
  { id: "i_intermodalite", axe: "faisabilite", label: "Intermodalité", poids: 2,
    description: "Stations de transport en commun pour 1000 habitants (rabattement vélo)", source: "TBMD" },
  { id: "i_covoiturage", axe: "faisabilite", label: "Aires de covoiturage", poids: 1,
    description: "Nombre d'aires de covoiturage dans la commune (rabattement vélo + covoiturage)", source: "BNLC" },
  { id: "i_securite", axe: "faisabilite", label: "Sécurité routière", poids: 2,
    description: "Accidents corporels des 5 dernières années pour 1000 habitants (peu = favorable)", source: "BAAC (ONISR)" },
  // --- deficit ---
  { id: "i_deficit_lineaire", axe: "deficit", label: "Déficit de linéaire cyclable", poids: 3,
    description: "Inverse du linéaire cyclable pour 1000 habitants (BNAC si disponible, sinon TBMD)", source: "BNAC / TBMD" },
  { id: "i_deficit_stationnement", axe: "deficit", label: "Déficit de stationnement vélo", poids: 1,
    description: "Inverse du nombre de stationnements pour 1000 habitants (OSM si disponible, sinon TBMD)", source: "PVELO / TBMD" },
];

// Grille communale de densite INSEE : 5 bourgs ruraux, 6 rural dispersé, 7 rural très dispersé
export const GRILLE_RURAL_MIN = 5;
