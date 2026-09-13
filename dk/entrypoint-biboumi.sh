#!/bin/sh
if [ -f /etc/custom-proxy/privoxy.conf ] && [ -f /etc/custom-proxy/chains.conf ]; then
    echo "Iniciando Privoxy y proxychains..."
    # Iniciar Privoxy en segundo plano
    privoxy /etc/custom-proxy/privoxy.conf
    sleep 2
    if ! /usr/bin/pgrep -x privoxy >/dev/null 2>&1; then
        echo "Error: Privoxy no se ha iniciado."
        cat /tmp/privoxy.log 2>/dev/null || true
        exit 1
    fi
    # Ejecutar biboumi a través de proxychains
    exec proxychains4 -f /etc/custom-proxy/chains.conf /usr/bin/biboumi "$@"
else
    echo "Ejecutando biboumi sin proxy..."
    exec /usr/bin/biboumi "$@"
fi