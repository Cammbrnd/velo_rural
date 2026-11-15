"""Execution complete : python lancer.py [--etape telecharger|assembler|exporter]"""
import argparse

import assembler
import exporter
import telecharger

ETAPES = {"telecharger": telecharger.main, "assembler": assembler.main, "exporter": exporter.main}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--etape", choices=ETAPES)
    a = p.parse_args()
    for nom, fn in ETAPES.items():
        if a.etape in (None, nom):
            fn()
