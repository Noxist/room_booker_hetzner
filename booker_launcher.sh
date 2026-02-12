#!/bin/bash
cd ~/auto_reserve
# -u erzwingt unbuffered Output, damit man sofort was sieht
python3 -u auto_booker.py "$@"
