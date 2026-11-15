// MapLibre 6 charge son worker par URL relative : une fois l'app bundlee, ce fichier n'existe plus.
// On le copie dans public/ pour qu'il soit servi tel quel (fonctionne aussi sous CSP stricte).
import { copyFileSync, mkdirSync } from "node:fs";
mkdirSync("public/maplibre", { recursive: true });
copyFileSync("node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs", "public/maplibre/maplibre-gl-worker.mjs");
console.log("worker maplibre copie dans public/maplibre/");
