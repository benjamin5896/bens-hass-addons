FROM ghcr.io/home-assistant/aarch64-base-debian:bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ola \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -r -G root -s /sbin/nologin -c "OLA daemon" ola \
    && mkdir -p /var/lib/ola /run/ola

COPY rootfs /

RUN chmod +x /etc/s6-overlay/s6-rc.d/ola/run

EXPOSE 6454/udp
