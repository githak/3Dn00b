## Which file do I need?

| Your computer | Download | Install |
|---|---|---|
| PC with Debian 12 or 13, Ubuntu 22.04 or newer, Linux Mint 21 or 22 | `3dn00b_{version}-1_amd64.deb` | `sudo apt install ./3dn00b_{version}-1_amd64.deb` |
| Raspberry Pi 4 or 5, other ARM computers (Raspberry Pi OS Trixie, Debian 13, Ubuntu 24.04 or newer) | `3dn00b_{version}-1_arm64.deb` | `sudo apt install ./3dn00b_{version}-1_arm64.deb` |
| Fedora 40 or newer, openSUSE Tumbleweed | `3dn00b-{version}-1.x86_64.rpm` | `sudo dnf install ./3dn00b-{version}-1.x86_64.rpm` (openSUSE: `sudo zypper install`) |
| Any other Linux PC from the last few years (glibc 2.34 or newer) | `3Dn00b-{version}-x86_64.AppImage` | `chmod +x 3Dn00b-{version}-x86_64.AppImage`, then run it; nothing to install |

Each file carries the libraries 3Dn00b needs; nothing is downloaded while installing.
Every file was installed and started on clean systems before this release was published.
