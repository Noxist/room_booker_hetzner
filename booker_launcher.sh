#!/bin/bash
cd ~/auto_reserve
# -u erzwingt unbuffered Output, damit man sofort was sieht
# -W ignore unterdrückt die nervige Google-Warnung
python3 -W ignore -u auto_booker.py "$@"
