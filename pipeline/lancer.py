"""Execution complete : python lancer.py [--etape telecharger|assembler|controle|exporter]"""
import argparse

import assembler
import controle
import exporter
import telecharger

ETAPES = {"telecharger": telecharger.main, "assembler": assembler.main, "controle": controle.main, "exporter": exporter.main}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--etape", choices=ETAPES)
    a = p.parse_args()
    for nom, fn in ETAPES.items():
        if a.etape in (None, nom):
            fn()
