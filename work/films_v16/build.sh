#!/bin/sh
# Films v16 (FINDINGS §33): v15 + MultiAxial hue sectors for every film (fits from refit16.py; Cinema = GR IV sets).
# Run from re-tools/ with a Python that has capstone/unicorn/numpy/PIL and gr-custom-tool on disk; PY overrides it.
set -e
PY=${PY:-python3}
F=work/films_v16/fits
FILMS="portra=$F/portra.json ektar=$F/ektar.json gold=$F/gold.json pro400h=$F/pro400h.json vision3=$F/vision3.json classicneg=$F/classicneg.json cinema_yellow@18=$F/cinema_yellow.json cinema_green@19=$F/cinema_green.json vision3500t@21=$F/vision3500t.json"
$PY make_slots16.py --raw-nr-above 8000 work/films_v16/fwdc239b.bin $FILMS > work/films_v16/build.log
$PY verify_slots16.py ../fwdc239b.bin work/films_v16/fwdc239b.bin $FILMS > work/films_v16/verify.log
tail -1 work/films_v16/verify.log
