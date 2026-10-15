#!/bin/bash
# films v3: refit with the warm-hue boost at several strengths
cd ~/dev/gr3-firmware/re-tools
P=python3
L=scratch/luts
for b in 1 2 4; do
  $P cube_fit.py --boost $b work/films_v3/fits/portra_b$b.json vlog $L/spektrafilm_v034_portra400_portraendura_1lut_vlog_srgb/lut_v034_portra400_portraendura.cube > work/films_v3/fits/portra_b$b.log 2>&1 &
  $P cube_fit.py --boost $b work/films_v3/fits/gold_b$b.json vlog $L/spektrafilm_v034_gold200_portraendura_1lut_vlog_srgb/lut_v034_gold200_portraendura.cube > work/films_v3/fits/gold_b$b.log 2>&1 &
  $P cube_fit.py --boost $b work/films_v3/fits/ektar_b$b.json vlog $L/spektrafilm_v034_ektar100_portraendura_1lut_vlog_srgb/lut_v034_ektar100_portraendura.cube > work/films_v3/fits/ektar_b$b.log 2>&1 &
done
wait
