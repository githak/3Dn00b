#!/bin/sh
# Install the .rpm on clean Fedora systems (in Docker) and run 3Dn00b's smoke test.
#   packaging/test_rpm.sh dist/3dn00b-*.x86_64.rpm [fedora:42 fedora:43]
# Behind an HTTPS-only proxy: DNF_PROXY=http://host:port (and DNF_CA=/path/ca.crt).
# FEDORA_BASEURL=1 uses dl.fedoraproject.org directly instead of the mirror list.
set -e
RPM=$(realpath "$1"); shift
IMAGES=${*:-"fedora:42 fedora:43"}
EXTRA=""
if [ -n "$DNF_PROXY" ]; then EXTRA="--network host"; fi
if [ -n "$DNF_CA" ]; then EXTRA="$EXTRA -v $(realpath "$DNF_CA"):/tmp/proxy-ca.crt:ro"; fi
for image in $IMAGES; do
    echo "=== $image"
    docker run --rm $EXTRA -e DNF_PROXY="$DNF_PROXY" -e FEDORA_BASEURL="$FEDORA_BASEURL" \
        -v "$RPM:/tmp/3dn00b.rpm:ro" "$image" sh -ec '
        if [ -n "$DNF_PROXY" ]; then
            echo "proxy=$DNF_PROXY" >> /etc/dnf/dnf.conf
            [ -f /tmp/proxy-ca.crt ] && echo "sslcacert=/tmp/proxy-ca.crt" >> /etc/dnf/dnf.conf
        fi
        if [ -n "$FEDORA_BASEURL" ]; then
            base=https://dl.fedoraproject.org/pub/fedora/linux
            opts="--setopt=fedora.metalink= --setopt=fedora.baseurl=$base/releases/\$releasever/Everything/\$basearch/os/
                  --setopt=updates.metalink= --setopt=updates.baseurl=$base/updates/\$releasever/Everything/\$basearch/
                  --disablerepo=fedora-cisco-openh264"
        fi
        dnf install -y -q $opts /tmp/3dn00b.rpm xorg-x11-server-Xvfb xorg-x11-xauth >/dev/null
        echo "Python: $(python3 --version) on $(uname -m)"
        missing=$(find /usr/lib/3dn00b -name "*.so*" -type f -exec ldd {} + 2>/dev/null \
                  | grep "not found" | grep -v -E "libgtk|libgdk|libpango|libcairo|libatk|libharfbuzz" \
                  | sort -u || true)
        if [ -n "$missing" ]; then echo "Missing libraries:"; echo "$missing"; exit 1; fi
        test -f /usr/share/applications/3dn00b.desktop
        if ! xvfb-run -a 3dn00b --smoke-test >/tmp/smoke.log 2>&1 \
                || ! grep -q "smoke test: OK" /tmp/smoke.log; then
            cat /tmp/smoke.log; echo "smoke test failed"; exit 1
        fi
        grep "smoke test" /tmp/smoke.log
        dnf remove -y -q 3dn00b >/dev/null
        test ! -e /usr/lib/3dn00b/app || { echo "files left behind"; exit 1; }
        echo "removed cleanly"
    '
done
