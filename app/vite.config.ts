import { resolve } from "node:path";
import { defineConfig } from "vite";

// base relative : l'app peut etre deployee dans un sous-dossier (partage, intranet)
// deux pages : la carte (index.html, avec la fenetre des seuils) et le tableau de resultats (resultats.html)
export default defineConfig({
  base: "./",
  build: { rollupOptions: { input: { index: resolve(__dirname, "index.html"), resultats: resolve(__dirname, "resultats.html") } } },
});
