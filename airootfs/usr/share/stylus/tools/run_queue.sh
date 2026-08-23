#!/usr/bin/env bash
# Generic sequential Qobuz queue runner + auto-integrator.
#
# Reads "url|artist|album" lines from a queue file, downloads them one at a
# time (the GUI API only permits one active download), and integrates each
# into the library as soon as it lands rather than batching at the end — so a
# crash or a dead battery mid-run still leaves finished albums properly filed.
set -uo pipefail

QUEUE_FILE=${1:?usage: run_queue.sh <queue-file>}
# The GUI backend's log is the reliable per-album "Completed" signal.
# Overridable because the log location depends on how the backend was
# started (stylus serve puts it in /tmp).
LOG=${QOBUZ_GUI_LOG:-/tmp/qobuz-gui.log}
TMP=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
API=http://127.0.0.1:8765/api/download

# `grep -c` imprime "0" E devolve 1 quando não casa nada, então
# `$(grep -c ... || echo 0)` devolvia "0\n0" e o `$(( ))` seguinte estourava
# com "erro de sintaxe aritmética" — abortando a fila INTEIRA na primeira
# volta, com um "QUEUE COMPLETE" que parecia sucesso. Só acontecia quando o
# log ainda não tinha nenhuma linha "Completed", ou seja: sempre que se
# começava do zero, que é justamente quando a fila importa.
completos() {
    local n
    n=$(grep -c "^Completed$" "$LOG" 2>/dev/null) || n=0
    [[ $n =~ ^[0-9]+$ ]] || n=0
    printf '%s' "$n"
}

while IFS='|' read -r url artist album; do
  [[ -z ${url:-} ]] && continue
  [[ $url == \#* ]] && continue

  before=$(completos)
  target=$((before + 1))
  echo "=== [$(date +%H:%M:%S)] queueing: $artist - $album"

  ok=0
  for _ in $(seq 1 120); do
    resp=$(curl -s "$API" -X POST -H "Content-Type: application/json" \
             -d "{\"urls\": \"$url\"}")
    if echo "$resp" | grep -q '"ok":true'; then ok=1; break; fi
    sleep 3
  done
  if [[ $ok -eq 0 ]]; then
    echo "!!! could not queue: $artist - $album ($resp)"
    continue
  fi

  # Wait for one more "Completed" line — the reliable per-album finish signal.
  done_it=0
  for _ in $(seq 1 600); do
    now=$(completos)
    if [[ $now -ge $target ]]; then done_it=1; break; fi
    sleep 3
  done
  if [[ $done_it -eq 0 ]]; then
    echo "!!! timed out waiting for: $artist - $album"
    continue
  fi

  # A linha "Completed" do backend chega ANTES de os arquivos terminarem de
  # ser escritos. Integrando nesse instante, a pasta ainda está pela metade —
  # e antes do conserto do integrate_album isso apagava o download inteiro.
  # Espera assentar: nenhum .tmp sobrando e a contagem de arquivos parada por
  # duas medidas seguidas.
  assentar() {
    local dir=$1 ant=-1 atual tmps
    for _ in $(seq 1 90); do
      tmps=$(find "$dir" -name '*.tmp*' 2>/dev/null | wc -l)
      atual=$(find "$dir" -type f 2>/dev/null | wc -l)
      if [[ $tmps -eq 0 && $atual -eq $ant && $atual -gt 0 ]]; then return 0; fi
      ant=$atual
      sleep 2
    done
    return 1
  }

  # Find the folder qobuz-dl just created for it. Match on the artist prefix
  # and take the newest, since its naming template includes year+quality which
  # we don't know ahead of time.
  # A casa de quem está rodando, não a de quem escreveu isto.
  folder=$(ls -1dt "${STYLUS_QOBUZ_DIR:-$HOME/Qobuz Downloads}/"*/ 2>/dev/null | head -1)
  folder=$(basename "$folder")
  if [[ -n $folder ]]; then
    assentar "${STYLUS_QOBUZ_DIR:-$HOME/Qobuz Downloads}/$folder" ||
      echo "    aviso: $folder não parou de mudar; integrando assim mesmo"
    echo "    integrating from: $folder"
    (cd "$TMP" && python3 integrate_album.py "$folder" "$artist" "$album" 2>&1 | tail -2)
  fi
  echo "=== finished: $artist - $album"
done < "$QUEUE_FILE"

echo "QUEUE COMPLETE: $QUEUE_FILE"
