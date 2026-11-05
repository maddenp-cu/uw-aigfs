#!/bin/bash

set -euo pipefail

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y curl nfs-kernel-server podman
mkdir -p /opt/rtaigfs
chmod 0777 /opt/rtaigfs
curl --fail --silent --show-error -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/rtaigfs-user-yaml --output /opt/rtaigfs/user.yaml
echo '/opt/rtaigfs 192.168.1.0/24(rw,sync,no_subtree_check,fsid=0)' >/etc/exports.d/rtaigfs.exports
exportfs -ra
systemctl enable --now nfs-kernel-server
#podman pull ghcr.io/maddenp-cu/aigfs:latest
