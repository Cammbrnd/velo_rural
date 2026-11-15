"""Test navigateur (Chrome bureau, rendu logiciel) : la couche communale est-elle dessinee ?
Usage : python smoke.py URL [capture.png]. Code de sortie 1 si aucune commune n'est rendue."""
import json
import sys

from playwright.sync_api import sync_playwright

url, capture = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome",
                          args=["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: print(f"SMOKE console[{m.type}] {m.text[:200]}") if m.type == "error" and "geopf" not in m.text and "Failed to load resource" not in m.text else None)
    pg.on("pageerror", lambda e: print(f"SMOKE pageerror {str(e)[:300]}"))
    pg.on("response", lambda r: print(f"SMOKE http {r.status} {r.url.split('/')[-1][:60]} range={r.headers.get('content-range', '-')} enc={r.headers.get('content-encoding', '-')}")
          if ".pmtiles" in r.url or "indicateurs.json" in r.url else None)
    pg.goto(url, wait_until="load")
    n = 0
    for _ in range(40):  # jusqu'a 60 s
        pg.wait_for_timeout(1500)
        n = pg.evaluate("() => { const m = window.__carte; return m && m.getLayer('communes-fill') ? m.queryRenderedFeatures({layers: ['communes-fill']}).length : -1; }")
        if n > 0:
            break
    etat = pg.evaluate("() => ({alerte: document.querySelector('.alerte')?.textContent || '', zoom: window.__carte?.getZoom(), panneau: document.getElementById('panneau').innerText.slice(0, 80)})")
    print("SMOKE", json.dumps({"communes_rendues": n, **etat}, ensure_ascii=False))
    if capture:
        pg.screenshot(path=capture)
    b.close()
    sys.exit(0 if n > 0 else 1)
