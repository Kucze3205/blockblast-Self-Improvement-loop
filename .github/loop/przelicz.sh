#!/usr/bin/env bash
# Jednorazowe przeliczenie starych drzew bieżącym ewaluatorem (#48), po dwa węzły naraz; potem wznowienie pętli.
# Idempotentne: lista bierze z `main` tylko węzły bez oceny bieżącym ewaluatorem. Po ok. 5,3 h woła samo siebie.
set -u
DRZEWA="${DRZEWA:-1 2 3 4}"
START=$(date +%s)
declare -A PROBY

czekaj() {  # <id> <od>: czeka na zakończenie przebiegu `ocena <id>` uruchomionego po <od>
  local id="$1" od="$2" rid="" st="" i
  for i in $(seq 1 12); do
    rid=$(gh run list --workflow ocena.yml --limit 40 --json databaseId,displayTitle,createdAt \
      --jq "[.[]|select(.displayTitle==\"ocena $id\" and .createdAt>=\"$od\")]|first|.databaseId" 2>/dev/null || true)
    [ -n "$rid" ] && [ "$rid" != "null" ] && break
    sleep 15
  done
  [ -n "$rid" ] && [ "$rid" != "null" ] || { echo "::warning::brak przebiegu oceny $id"; return 1; }
  for i in $(seq 1 240); do   # do 2 h
    st=$(gh run view "$rid" --json status,conclusion --jq '.status+" "+(.conclusion // "")' 2>/dev/null || echo "?")
    case "$st" in completed*) echo "ocena $id: $st"; return 0 ;; esac
    sleep 30
  done
  echo "::warning::ocena $id trwa za długo"; return 1
}

while :; do
  git fetch -q origin main && git reset -q --hard origin/main || { sleep 60; continue; }
  mapfile -t L < <(python3 .github/loop/przelicz.py lista $DRZEWA)
  [ ${#L[@]} -eq 0 ] && { echo "wszystkie stare węzły przeliczone"; break; }
  if [ $(( $(date +%s) - START )) -gt 19000 ]; then
    echo "zostało ${#L[@]} węzłów; kolejny przebieg"
    gh workflow run przelicz.yml --ref "${DEFAULT_BRANCH:-main}"
    exit 0
  fi
  wybrane=()
  for w in "${L[@]}"; do
    set -- $w
    [ "${PROBY[$1-$2]:-0}" -lt 2 ] && wybrane+=("$w")
    [ ${#wybrane[@]} -ge 2 ] && break
  done
  [ ${#wybrane[@]} -eq 0 ] && { echo "::warning::${#L[@]} węzłów bez udanej oceny, pomijam"; break; }
  od=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  for w in "${wybrane[@]}"; do
    set -- $w
    PROBY[$1-$2]=$(( ${PROBY[$1-$2]:-0} + 1 ))
    gh workflow run ocena.yml --ref "${DEFAULT_BRANCH:-main}" -f wezel="$3" -f drzewo="$1" -f id="$1-$2" || true
  done
  for w in "${wybrane[@]}"; do
    set -- $w
    czekaj "$1-$2" "$od" || true
  done
done

# wznowienie pętli: węzły otwartych drzew bez działającej sesji (zaparkowane albo przerwane) i harmonogram
python3 .github/loop/przelicz.py wznow | while read -r t n k; do
  echo "wznawiam węzeł $t/$n"
  gh workflow run wezel.yml --ref "${DEFAULT_BRANCH:-main}" -f drzewo="$t" -f wezel="$n" -f kolejnosc="$k" || true
done
gh workflow run drzewo.yml --ref "${DEFAULT_BRANCH:-main}" || true
