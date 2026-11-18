import { resolve } from "node:path";
import { defineConfig } from "vite";

// base relative : l'app peut etre deployee dans un sous-dossier (partage, intranet)
// trois pages : la carte (index.html), le tableau de resultats (resultats.html) et les seuils (seuils.html)
export default defineConfig({
  base: "./",
  build: { rollupOptions: { input: { index: resolve(__dirname, "index.html"), resultats: resolve(__dirname, "resultats.html"), seuils: resolve(__dirname, "seuils.html") } } },
});
