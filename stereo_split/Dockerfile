FROM alpine:3.20 AS builder

ARG SHAIRPORT_REF=5.6.2
ARG NQPTP_REF=1.2.9

RUN apk add --no-cache \
        autoconf \
        automake \
        avahi-dev \
        build-base \
        ffmpeg-dev \
        git \
        libconfig-dev \
        libffi-dev \
        libgcrypt-dev \
        libplist-dev \
        libplist-util \
        libsodium-dev \
        libtool \
        openssl-dev \
        popt-dev \
        py3-pip \
        python3-dev \
        soxr-dev \
        util-linux-dev \
        xmltoman \
        xxd

RUN git clone --depth 1 --branch "${SHAIRPORT_REF}" \
        https://github.com/mikebrady/shairport-sync.git /tmp/shairport-sync \
    && cd /tmp/shairport-sync \
    && autoreconf -fi \
    && ./configure --sysconfdir=/etc \
        --with-pipe --with-avahi --with-ssl=openssl --with-soxr --with-airplay-2 \
    && make -j"$(nproc)" \
    && make install DESTDIR=/out

RUN git clone --depth 1 --branch "${NQPTP_REF}" \
        https://github.com/mikebrady/nqptp.git /tmp/nqptp \
    && cd /tmp/nqptp \
    && autoreconf -fi \
    && ./configure \
    && make -j"$(nproc)" \
    && make install DESTDIR=/out

ARG PYATV_VERSION=0.18.0
RUN python3 -m venv /out/opt/venv \
    && /out/opt/venv/bin/pip install --no-cache-dir "pyatv==${PYATV_VERSION}" "srptools==1.0.1"

FROM ghcr.io/hassio-addons/base:16.3.3

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apk add --no-cache \
        avahi \
        avahi-libs \
        dbus \
        ffmpeg \
        libconfig \
        libffi \
        libgcrypt \
        libplist \
        libsodium \
        libuuid \
        mailcap \
        popt \
        python3 \
        soxr

COPY --from=builder /out/ /

COPY rootfs /

RUN find /etc/cont-init.d /etc/services.d /usr/local/bin -type f \
        \( -name 'run' -o -name '*.sh' -o -name '*.py' \) \
        -exec sed -i 's/\r$//' {} + \
    && chmod a+x /etc/cont-init.d/* /etc/services.d/*/run /usr/local/bin/*.py
