# iPhone backup: usbmuxd (USB) + netmuxd (adds Wi-Fi devices) + libimobiledevice (does the backup)
# Arch base because it ships libimobiledevice 1.4 (Debian still has 1.3, too old for recent iOS).
FROM archlinux:base

RUN pacman -Syu --noconfirm --needed libimobiledevice usbmuxd uv curl util-linux coreutils \
    && pacman -Scc --noconfirm

# pymobiledevice3 is only used once, to switch on "Wi-Fi connections" on the iPhone
# (libimobiledevice has no command for that lockdown setting).
ENV UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv tool install --python 3.12 pymobiledevice3==11.48.0

# netmuxd: usbmuxd replacement that also sees devices on the network (mDNS)
ARG NETMUXD_VERSION=v0.4.3
ARG NETMUXD_SHA256=85b6598284fc639f2a282584461d05e2090b79bdf3ec949d2a5e5d3dc655dde4
RUN curl -fsSL -o /tmp/netmuxd.tgz \
      https://github.com/jkcoxson/netmuxd/releases/download/${NETMUXD_VERSION}/netmuxd-x86_64-unknown-linux-gnu.tar.gz \
    && echo "${NETMUXD_SHA256}  /tmp/netmuxd.tgz" | sha256sum -c - \
    && tar -xzf /tmp/netmuxd.tgz -C /usr/local/bin netmuxd && rm /tmp/netmuxd.tgz

# All libimobiledevice tools talk to netmuxd, which forwards USB devices to usbmuxd
# and adds the ones it finds on Wi-Fi.
ENV USBMUXD_SOCKET_ADDRESS=UNIX:/var/run/netmuxd

COPY bin/ /usr/local/bin/
RUN chmod +x /usr/local/bin/*

ENTRYPOINT ["/usr/local/bin/entrypoint"]
