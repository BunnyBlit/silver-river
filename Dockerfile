# Benchmark container: Xvfb + Godot + OBS + the Python harness.
ARG UBUNTU_TAG
FROM ubuntu:${UBUNTU_TAG}

# from versions.env
ARG GODOT_VERSION
ARG GODOT_RELEASE
ARG DOTNET_SDK
ARG PYTHON_VERSION
ARG UV_VERSION
ARG OBS_APT_VERSION
ENV DEBIAN_FRONTEND=noninteractive

# Base tooling, Xvfb, and software-rendering (llvmpipe) 
# intel-gpu-tools is included for GPU monitoring on Intel
# hosts; it's a no-op on boxes without an Intel GPU
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        wget curl unzip ca-certificates gnupg software-properties-common \
        mesa-utils libgl1 libglu1-mesa libgl1-mesa-dri \
        intel-gpu-tools \
        dotnet-sdk-${DOTNET_SDK} \
    && rm -rf /var/lib/apt/lists/*

# OBS Studio -- obs-websocket v5 is bundled in OBS >= 28, no separate install.
RUN add-apt-repository -y ppa:obsproject/obs-studio && \
    apt-get update && \
    apt-get install -y --no-install-recommends obs-studio${OBS_APT_VERSION:+=$OBS_APT_VERSION} && \
    rm -rf /var/lib/apt/lists/*

# AMD GPU monitoring (rocm-smi) is deliberately NOT installed here -- it
# requires adding AMD's own apt repo pinned to match the host driver
# version. If needed, add ROCm's repo + `apt-get install rocm-smi-lib`,
# matched to that host's driver version.

# --- TODO: bake a pre-built OBS scene collection into the image ---
# Build the scene interactively somewhere, then from that machine:
#   pip install obs-scene-transporter
#   obs-scene-transporter export <your-scene-collection-name> scene-export.zip
# Drop scene-export.zip next to this
# Dockerfile, then uncomment:
#
# RUN pip3 install --break-system-packages --no-cache-dir obs-scene-transporter
# COPY scene-export.zip /tmp/scene-export.zip
# RUN obs-scene-transporter import /tmp/scene-export.zip && rm /tmp/scene-export.zip

# Godot Engine
# symlink rather than copy, due to needing adjacency to GodotSharp, using find ... rather than
# trying to remember the somewhat fiddly executable name
RUN set -eux; \
    curl -fSL "https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}-${GODOT_RELEASE}/Godot_v${GODOT_VERSION}-${GODOT_RELEASE}_mono_linux_x86_64.zip" -o /tmp/godot.zip; \
    unzip -q /tmp/godot.zip -d /tmp/godot-extract; \
    mv /tmp/godot-extract/*/ /opt/godot; \
    rm -rf /tmp/godot.zip /tmp/godot-extract; \
    bin="$(find /opt/godot -maxdepth 1 -type f -name 'Godot_v*_mono_linux*' -print -quit)"; \
    test -n "$bin"; \
    chmod +x "$bin"; \
    ln -s "$bin" /usr/local/bin/godot4; \
    chmod +x /usr/local/bin/godot4

# finally, python + uv
COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /usr/local/bin/uv
RUN uv python install ${PYTHON_VERSION}

# installs are done, lets actually run some shit
WORKDIR /bench
COPY scripts ./scripts
RUN bash /bench/scripts/generate_manifest.sh

# python project stuff
COPY pyproject.toml uv.lock .
RUN uv sync --locked --no-install-project
COPY README.md .
COPY src ./src
RUN uv sync --locked

ENTRYPOINT ["uv", "run", "silver-river-bench"]
