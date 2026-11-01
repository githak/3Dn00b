#!/bin/sh
# Install the .deb on clean Debian/Ubuntu systems (in Docker) and run 3Dn00b's smoke test.
#   packaging/test_deb.sh dist/3dn00b_*.deb [debian:12 ubuntu:22.04 ...]
set -e
DEB=$(realpath "$1"); shift
# An arm64 package is tested in ARM containers (on a PC that needs qemu-user-static).
case "$DEB" in
    *_arm64.deb) PLATFORM="--platform linux/arm64"
                 IMAGES=${*:-"debian:13 ubuntu:24.04 ubuntu:26.04"} ;;
    *)           PLATFORM=""
                 IMAGES=${*:-"debian:12 debian:13 ubuntu:22.04 ubuntu:24.04 ubuntu:26.04"} ;;
esac
# Behind an HTTPS-only proxy: APT_PROXY=http://host:port (and APT_CA=/path/ca.crt if it
# re-signs TLS) make apt in the containers use HTTPS mirrors through it.
# DOCKER_NETWORK=host shares the host's network (when containers have none of their own).
EXTRA=${DOCKER_NETWORK:+--network $DOCKER_NETWORK}
if [ -n "$APT_PROXY" ]; then EXTRA="--network host"; fi
if [ -n "$APT_CA" ]; then EXTRA="$EXTRA -v $(realpath "$APT_CA"):/tmp/proxy-ca.crt:ro"; fi
for image in $IMAGES; do
    echo "=== $image"
    docker run --rm $PLATFORM $EXTRA -e APT_PROXY="$APT_PROXY" -v "$DEB:/tmp/3dn00b.deb:ro" "$image" sh -ec '
        export DEBIAN_FRONTEND=noninteractive
        if [ -n "$APT_PROXY" ]; then
            sed -i "s#http://#https://#g" /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
            echo "Acquire::https::Proxy \"$APT_PROXY\";" > /etc/apt/apt.conf.d/01proxy
            if [ -f /tmp/proxy-ca.crt ]; then
                echo "Acquire::https::CAInfo \"/tmp/proxy-ca.crt\";" >> /etc/apt/apt.conf.d/01proxy
            fi
        fi
        apt-get update -qq >/dev/null
        apt-get install -y -qq /tmp/3dn00b.deb xvfb xauth >/dev/null
        echo "Python: $(python3 --version) on $(uname -m)"
        # Every bundled library must find its system libraries (GTK is only used on GTK desktops).
        missing=$(find /usr/lib/3dn00b -name "*.so*" -type f -exec ldd {} + 2>/dev/null \
                  | grep "not found" | grep -v -E "libgtk|libgdk|libpango|libcairo|libatk|libharfbuzz" \
                  | sort -u || true)
        if [ -n "$missing" ]; then echo "Missing libraries:"; echo "$missing"; exit 1; fi
        test -f /usr/share/applications/3dn00b.desktop
        test -f /usr/share/icons/hicolor/scalable/apps/3dn00b.svg
        # Keep the exit code: a pipe into grep would hide a failing smoke test.
        if ! xvfb-run -a 3dn00b --smoke-test >/tmp/smoke.log 2>&1 \
                || ! grep -q "smoke test: OK" /tmp/smoke.log; then
            cat /tmp/smoke.log; echo "smoke test failed"; exit 1
        fi
        grep "smoke test" /tmp/smoke.log
        apt-get remove -y -qq 3dn00b >/dev/null
        test ! -e /usr/lib/3dn00b/app || { echo "files left behind"; exit 1; }
        echo "removed cleanly"
    '
done
