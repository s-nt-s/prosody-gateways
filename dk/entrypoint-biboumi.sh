#!/bin/sh
if [ -f /etc/custom-proxy/privoxy.conf ] && [ -f /etc/custom-proxy/chains.conf ]; then
    echo "Iniciando Privoxy y proxychains..."
    # Iniciar Privoxy en segundo plano
    privoxy /etc/custom-proxy/privoxy.conf
    sleep 10
    # Ejecutar biboumi a través de proxychains
    exec proxychains4 -f /etc/custom-proxy/chains.conf /usr/bin/biboumi "$@"
else
    echo "Ejecutando biboumi sin proxy..."
    exec /usr/bin/biboumi "$@"
fi