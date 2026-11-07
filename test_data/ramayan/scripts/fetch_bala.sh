#!/bin/bash
# Pilot: download Bala Kanda raw files. Usage: fetch_bala.sh <ramayan_dir>
R="$1"
curl -sfL -m 60 https://bombay.indology.info/ramayana/text/UD/Ram01.txt -o "$R/raw/smith/Ram01.txt"
for n in $(seq 1 77); do
  [ -s "$R/raw/net/baala/sans$n.htm" ] || curl -sfL -m 60 "https://www.valmikiramayan.net/baala/sarga$n/balasans$n.htm" -o "$R/raw/net/baala/sans$n.htm" || echo "net fail $n"
  [ -s "$R/raw/in/baala/sarga$n.html" ] || curl -sfL -m 60 "https://www.valmikiramayan.in/p/balakand-sarg-$n-shrimad-valmiki-ramayan.html" -o "$R/raw/in/baala/sarga$n.html" || echo "in fail $n"
  sleep 0.5
done
echo done
