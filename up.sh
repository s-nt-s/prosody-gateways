#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "Missing .env file. Please create it first."
    exit 1
fi

. .env

python3 generate-config.py

sudo mkdir -p \
    ./prosody/certs/ \
    ./prosody/data/ \
    ./slidge/telegram/ \
    ./slidge/whatsapp/ \
    ./slidge/steam/

if [ -v XMPP_CRT ] && [ -v XMPP_KEY ]; then
if sudo test -f "$XMPP_CRT"; then
if sudo test -f "$XMPP_KEY"; then
    echo "Copying XMPP certificate and key to prosody/certs/"
    echo "  $XMPP_CRT"
    echo "  $XMPP_KEY"
    sudo cp "$XMPP_CRT" ./prosody/certs/
    sudo cp "$XMPP_KEY" ./prosody/certs/
fi
fi
fi

HOST_USER="$(whoami)"
HOST_GROUP="$(id -gn "$HOST_USER")"
sudo chown -R "$HOST_USER":"$HOST_GROUP" \
    ./prosody/certs/ \
    ./prosody/data/
sudo chmod 750 \
    ./prosody/certs/ \
    ./prosody/data/

sudo chown -R 10000:10000 \
    ./slidge/telegram/ \
    ./slidge/whatsapp/ \
    ./slidge/steam/
sudo chmod 700 \
    ./slidge/telegram/ \
    ./slidge/whatsapp/ \
    ./slidge/steam/
sudo chmod 644 \
    ./slidge/*.conf

if docker compose ps -q >/dev/null 2>&1; then
    echo "Stopping existing compose services..."
    docker compose down
fi

docker compose up "$@"