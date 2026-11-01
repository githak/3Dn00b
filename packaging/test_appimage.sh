#!/bin/sh
# Run the AppImage on clean Linux systems (in Docker) that have only what any desktop
# has (OpenGL, fonts, X11, D-Bus), none of the libraries Qt or Python need, and run
# 3Dn00b's smoke test.
#   packaging/test_appimage.sh dist/3Dn00b-*-x86_64.AppImage [ubuntu:22.04 fedora:43 ...]
# Behind an HTTPS-only proxy, set APT_PROXY (and APT_CA) as for test_deb.sh (also for
# Fedora images).
set -e
APP=$(realpath "$1"); shift
case "$APP" in
    *aarch64*) PLATFORM="--platform linux/arm64"
               IMAGES=${*:-"ubuntu:24.04 ubuntu:26.04"} ;;
    *)         PLATFORM=""
               IMAGES=${*:-"ubuntu:22.04 ubuntu:24.04 ubuntu:26.04"} ;;
esac
EXTRA=${DOCKER_NETWORK:+--network $DOCKER_NETWORK}
if [ -n "$APT_PROXY" ]; then EXTRA="--network host"; fi
if [ -n "$APT_CA" ]; then EXTRA="$EXTRA -v $(realpath "$APT_CA"):/tmp/proxy-ca.crt:ro"; fi
for image in $IMAGES; do
    echo "=== $image"
    docker run --rm $PLATFORM $EXTRA -e APT_PROXY="$APT_PROXY" -v "$APP:/tmp/3Dn00b.AppImage:ro" \
        "$image" sh -ec '
        if command -v dnf >/dev/null; then              # Fedora
            if [ -n "$APT_PROXY" ]; then
                echo "proxy=$APT_PROXY" >> /etc/dnf/dnf.conf
                [ -f /tmp/proxy-ca.crt ] && echo "sslcacert=/tmp/proxy-ca.crt" >> /etc/dnf/dnf.conf
            fi
            # What every desktop has, and the virtual screen for the test. No Python, no Qt.
            dnf install -y -q --setopt=install_weak_deps=False xorg-x11-server-Xvfb \
                xorg-x11-xauth which findutils mesa-libGL mesa-libEGL fontconfig dbus-libs \
                glib2 libX11-xcb libxcb >/dev/null 2>&1
        else                                            # Debian and Ubuntu
            export DEBIAN_FRONTEND=noninteractive
            if [ -n "$APT_PROXY" ]; then
                sed -i "s#http://#https://#g" /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
                echo "Acquire::https::Proxy \"$APT_PROXY\";" > /etc/apt/apt.conf.d/01proxy
                if [ -f /tmp/proxy-ca.crt ]; then
                    echo "Acquire::https::CAInfo \"/tmp/proxy-ca.crt\";" >> /etc/apt/apt.conf.d/01proxy
                fi
            fi
            apt-get update -qq >/dev/null
            apt-get install -y -qq --no-install-recommends xvfb xauth libgl1 libegl1 libopengl0 \
                libfontconfig1 libdbus-1-3 libglib2.0-0 libx11-xcb1 libxcb-glx0 libxcb-randr0 \
                libxcb-render0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 >/dev/null
        fi
        if command -v python3 >/dev/null; then echo "python3 is installed: the test is not clean"; exit 1; fi
        cd /tmp && /tmp/3Dn00b.AppImage --appimage-extract >/dev/null
        export LD_LIBRARY_PATH=/tmp/squashfs-root/usr/lib
        missing=$(find /tmp/squashfs-root -name "*.so*" -type f -exec ldd {} + 2>/dev/null \
                  | grep "not found" | grep -v -E "libgtk|libgdk|libpango|libcairo|libatk|libharfbuzz|libwayland" \
                  | sort -u || true)
        if [ -n "$missing" ]; then echo "Missing libraries:"; echo "$missing"; exit 1; fi
        unset LD_LIBRARY_PATH
        if ! APPIMAGE_EXTRACT_AND_RUN=1 xvfb-run -a /tmp/3Dn00b.AppImage --smoke-test \
                >/tmp/smoke.log 2>&1 || ! grep -q "smoke test: OK" /tmp/smoke.log; then
            cat /tmp/smoke.log; echo "smoke test failed"; exit 1
        fi
        echo "$(uname -m): $(grep "smoke test" /tmp/smoke.log)"
    '
done
