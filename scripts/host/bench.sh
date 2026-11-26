#!/usr/bin/env bash
# this is our benchmarking script. It's run outside of a container, on the host, to build and run the benchmark
# args:
# $1 -- the target we're benchmarking
set -euo pipefail

# ensure that we're gonna run from where we think we should run, making all our relative paths work
cd "$(dirname "$0")/../.."

# ensure that we have the correct target
export TARGET="${1:-}"
[[ -z "${TARGET}" ]] && { printf "target not set, usage: bench.sh TARGET MODE\n" >&2; exit 1; }
[[ -f "targets/$TARGET.env" ]] || { printf "no targets/%s.env;available:\n%s\n" "$TARGET" "$(ls targets)" >&2; exit 1; }

#drop the $1 reference so we can pass the other vars down
shift 1

# load build pins and secrets
set -a; . ./versions.env; . ./.env; set +a

# set the SR_AGD_COMMIT
export SR_AGD_COMMIT="$(git -C "$AGD_REPO" describe --always --dirty --exclude='*')"

# create the results directory
mkdir -p benchmark_results

# docker compose time
exec docker compose run --build --rm benchmark "$@"