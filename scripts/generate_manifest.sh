#!/bin/bash
set -eux

obs_ver="$(dpkg-query -W -f='${Version}' obs-studio)"
godot_ver="$(godot4 --version 2>/dev/null)"
dotnet_ver="$(dotnet --version)"

cat > /bench/manifest.json <<JSON
{
  "requested": {
    "ubuntu": "${UBUNTU_TAG}",
    "godot": "${GODOT_VERSION}-${GODOT_RELEASE}",
    "dotnet_sdk": "${DOTNET_SDK}",
    "obs_apt_version": "${OBS_APT_VERSION}"
  },
  "resolved": {
    "godot": "${godot_ver}",
    "dotnet_sdk": "${dotnet_ver}",
    "obs_studio": "${obs_ver}"
  },
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON