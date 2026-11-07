#!/bin/bash
# Download valmikiramayan.net Devanagari+meaning pages. Usage: fetch_net.sh <ramayan_dir> <kanda_key> <site_dir> <file_prefix> <sargas> [path_prefix]
# e.g. fetch_net.sh . ayodhya ayodhya ayodhya 119
R="$1"; K="$2"; D="$3"; P="$4"; N="$5"; U="${6:-}"
mkdir -p "$R/raw/net/$K"
for n in $(seq 1 "$N"); do
  f="$R/raw/net/$K/sans$n.htm"
  [ -s "$f" ] || curl -sfL -m 60 "https://www.valmikiramayan.net/${U}${D}/sarga$n/${P}sans$n.htm" -o "$f" || echo "net fail $K $n"
  sleep 0.4
done
echo "done $K"
