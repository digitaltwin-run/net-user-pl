#!/usr/bin/env bash
# Generate an isolated root CA and leaf certs for the virtual internet domains.
#
# SAFETY: this root CA is trusted ONLY inside the desktop container image. It is
# never installed on your host. Do not add out/rootCA.pem to your host trust
# store — it can issue certs for real domains (mbank.pl, gov.pl) and would let
# anyone MITM the real sites you actually use.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/out"
DOMAINS=("mbank.pl" "phone.jan.pl" "login.gov.pl" "poczta.jan.pl")

mkdir -p "$OUT"
cd "$OUT"

if [ ! -f rootCA.pem ]; then
  openssl genrsa -out rootCA.key 4096
  openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 3650 \
    -subj "/C=PL/O=net-user-pl Virtual Internet/CN=net-user-pl Root CA" \
    -out rootCA.pem
  echo "root CA created"
fi

for d in "${DOMAINS[@]}"; do
  [ -f "$d.pem" ] && continue
  openssl genrsa -out "$d.key" 2048
  openssl req -new -key "$d.key" -subj "/C=PL/O=Virtual/CN=$d" -out "$d.csr"
  cat > "$d.ext" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
subjectAltName=DNS:$d,DNS:www.$d
EOF
  openssl x509 -req -in "$d.csr" -CA rootCA.pem -CAkey rootCA.key -CAcreateserial \
    -out "$d.pem" -days 825 -sha256 -extfile "$d.ext"
  rm -f "$d.csr" "$d.ext"
  echo "leaf cert: $d"
done
echo "done -> $OUT"
