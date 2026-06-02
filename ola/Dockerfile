FROM ghcr.io/home-assistant/aarch64-base-debian:bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ola \
    && rm -rf /var/lib/apt/lists/*

# Create the ola user. Adding it to the 'root' group gives it read/write access
# to USB device nodes, which inside the HA addon container are always owned
# root:root 0664 and cannot be chowned at runtime.
RUN useradd -r -G root -s /sbin/nologin -c "OLA daemon" ola \
    && mkdir -p /var/lib/ola /run/ola

COPY rootfs /

RUN chmod +x /etc/s6-overlay/s6-rc.d/ola/run

EXPOSE 6454/udp
