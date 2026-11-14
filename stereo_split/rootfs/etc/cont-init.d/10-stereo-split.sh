#!/usr/bin/with-contenv bashio
set -e

RUN=/run/stereosplit
rm -f /etc/avahi/services/*.service
mkdir -p "${RUN}" /run/dbus /run/avahi-daemon /etc/avahi/services

ROOM_A="$(bashio::config 'left_channel_name')"
ROOM_B="$(bashio::config 'right_channel_name')"
DENON="$(bashio::config 'denon_host')"

if [ -z "${DENON}" ] || [ "${DENON}" = "null" ]; then
    bashio::exit.nok "Set denon_host to the IP address of the Denon."
fi

for name in "${ROOM_A}" "${ROOM_B}"; do
    if printf '%s' "${name}" | grep -q '["\\<>&]'; then
        bashio::exit.nok "Room names must not contain quotes, backslashes, < > or &."
    fi
done
if [ "${ROOM_A}" = "${ROOM_B}" ]; then
    bashio::exit.nok "The left and right channel names need to be different."
fi
norm() { printf '%s' "$1" | tr -c 'A-Za-z0-9' '-'; }
if [ "$(norm "${ROOM_A}")" = "$(norm "${ROOM_B}")" ]; then
    bashio::exit.nok "Room names must differ by more than punctuation or spaces."
fi

LATENCY_OFFSET=-0.5

rm -f "${RUN}/roomA.pcm" "${RUN}/roomB.pcm" "${RUN}/mix.pcm"
mkfifo "${RUN}/roomA.pcm" "${RUN}/roomB.pcm" "${RUN}/mix.pcm"

cat > "${RUN}/shairport-a.conf" <<EOF
general = {
    name = "${ROOM_A}";
    output_backend = "pipe";
    port = 5000;
    audio_backend_latency_offset_in_seconds = ${LATENCY_OFFSET};
    service_type = "airplay2";
    audio_backend_buffer_desired_length_in_seconds = 0.05;
    audio_decoded_buffer_desired_length_in_seconds = 0.2;
};
pipe = {
    name = "${RUN}/roomA.pcm";
    output_format = "S16_LE";
    output_rate = 44100;
    output_channels = 2;
};
EOF

cat > "${RUN}/shairport-b.conf" <<EOF
general = {
    name = "${ROOM_B}";
    output_backend = "pipe";
    port = 5001;
    audio_backend_latency_offset_in_seconds = ${LATENCY_OFFSET};
    service_type = "airplay2";
    audio_backend_buffer_desired_length_in_seconds = 0.05;
    audio_decoded_buffer_desired_length_in_seconds = 0.2;
};
pipe = {
    name = "${RUN}/roomB.pcm";
    output_format = "S16_LE";
    output_rate = 44100;
    output_channels = 2;
};
EOF

cat > "${RUN}/avahi-daemon.conf" <<EOF
[server]
host-name=stereo-split
use-ipv4=yes
use-ipv6=no
enable-dbus=yes

[publish]
publish-hinfo=no
publish-workstation=no
EOF

bashio::log.info "Rooms: '${ROOM_A}' -> left channel, '${ROOM_B}' -> right channel"
bashio::log.info "Mixed stereo stream will be sent to ${DENON} over AirPlay."
