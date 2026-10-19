#!/bin/bash
# Entrypoint script for benchmarking the AGD Brawler streaming harness
set -euo pipefail

AGD_SRC=${AGD_SRC:-/bench/godot-project}   # the :ro mount
AGD_WORK=${AGD_WORK:-/bench/work}

# better be a godot directory at our source or we're in big trouble lmao
[[ -d "$AGD_SRC/godot" ]] || { echo "AGD source not mounted at $AGD_SRC" >&2; exit 1; }

# kinda hacky way to get files into the working directory w/o copying things like .git over
# creates a ziped archive of the project w/o what we don't want, and unzips it where we want it.
mkdir -p "$AGD_WORK"
tar -C "$AGD_SRC" -c --exclude=.git --exclude=.godot --exclude=bin --exclude=obj . \
  | tar -C "$AGD_WORK" -x

DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 dotnet build "$AGD_WORK/godot/BrawlerGodot.csproj" -c Debug

# only import everything _now_ so we're not stalled on warmup later
godot4 --headless --import --path "$AGD_WORK/godot"
exec uv run --no-sync silver-river bench --godot-project="$AGD_WORK/godot" "$@"