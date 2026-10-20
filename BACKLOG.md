# Backlog

Deferred work, deliberately not blocking forward progress. The pipeline needs to
actually run end-to-end before any of this is worth doing — a test suite around
code whose shape is still changing is a liability, and refactoring for readability
before the first real benchmark means polishing a design that hasn't met reality yet.

Revisit after the first containerized run produces a result file with real Godot
pixels in the stream.

## Next up

Both of the first two are *false-pass* guards. They share a root cause worth
stating plainly: the pass/fail metric is a ratio over encoder frames, and every
degenerate input to that ratio currently resolves to "0.0% dropped" — which is
also what a perfect run looks like. A benchmark that cannot distinguish "flawless"
from "never ran" is worse than no benchmark, because it produces a confident wrong
answer to the one question (CPU vs GPU, $15/mo vs $400/mo) the project exists to
settle.

- [ ] **`calc_output_drop_pct` must distinguish "no frames" from "no drops."**
      `return (dropped / total) * 100 if total else 0.0` returns `0.0` when the
      encoder produced zero frames, which the outcome ladder then reads as a pass.
      Observed for real: a container run collected 10 valid samples, every one
      with `output_total_frames == 0`, and the result file said `"outcome": "pass"`
      with `0.00%` drops. Return `None` for `total == 0` and have the ladder map it
      to `no_data`. The existing `len(rows) == 0` guard does not cover this —
      ten samples of nothing pass straight through it.
- [ ] **Verify the stream is actually live, don't infer it.** Call
      `GetStreamStatus` over obs-websocket after connecting (and ideally per
      sample) and check `outputActive`. In the run above, `--startstreaming` fired
      *before* the harness configured the RTMP target via
      `set_stream_service_settings`, so OBS tried to stream to nothing, failed,
      and was never told to start again — with no indication anywhere in the
      result. Checking output state directly turns that into a named failure
      instead of a silent zero. Also fix the ordering: configure the service
      first, then start streaming.
- [ ] **Bounded retry on OBS websocket connect.** Replace the fixed
      `--obs-warmup` sleep with a retry loop that reports what it was waiting
      for. Currently a single attempt after a blind sleep, so *any* failure to
      reach the websocket looks like a timing problem. It cost real debugging
      time: the actual cause was obs-websocket's server being disabled by
      default, and a 20s warmup "failing" the same way as a 2s one was the only
      hint that timing wasn't the issue. Every container run depends on this
      connection, so a failure here should name itself. Note the asymmetry it
      fixes: a websocket that dies at minute 30 already degrades gracefully via
      per-sample `error`, while one that's slow at second 8 kills the whole run.

## Tests

Highest value first. The ordering isn't arbitrary: the top three are each a bug
that actually shipped during development and was caught by luck or by review
rather than by a test.

- [ ] **`calc_output_drop_pct` / `calc_render_drop_pct` against known fixtures.**
      Two samples with hand-computed drop counts, asserting an exact percentage.
      A missing `not` in the guard clause once made these return `0.0` whenever
      OBS data was present — i.e. every benchmark passed. This is the one number
      the whole project turns on, and the one place where being wrong is
      indistinguishable from success.
- [ ] **GPU probes against stubbed vendor CLIs.** Put a fake `nvidia-smi` on
      `PATH` that echoes a known line, assert a populated `GpuSample`. A field
      rename silently broke all three probes; because each wraps its body in
      `except Exception: return None`, the failure looked exactly like "no GPU
      present" and would only have surfaced on a paid GPU box.
- [ ] **`flat_columns` / `flatten_row` on heterogeneous samples.** First sample
      with no `obs` and no `gpu`, later ones with both; assert identical key sets
      across rows and that the CSV parses back to a constant field count.
- [ ] **`read_cpu_quota` against fixture cgroup files** — v2 `"max 100000"`, v2
      `"150000 100000"`, v1 split files, and a malformed file. Needs the paths
      injectable; they're currently hardcoded.
- [ ] **`--godot-env` parsing** — `KEY=VALUE`, values containing `:` (`ai:7`),
      values containing `=`, and a malformed arg with no `=` at all.
- [ ] **Outcome derivation at the boundary** — drop rate exactly at
      `FAIL_THRESHOLD`, just over, just under, plus the aborted path.
- [ ] **Manifest loading failure modes** — missing file, missing keys, unparseable
      `built_at`.
- [ ] **Counter reset mid-run.** OBS's frame counters reset if the stream
      reconnects, producing a negative delta. Currently clamped with `max(..., 0.0)`,
      which silently reports 0% for a run that may have been terrible.

## Refactor for readability

- [ ] **Stop passing `argparse.Namespace` everywhere.** `runner`, `obs`, and
      `results` all reach into `args` for unrelated fields, so every function's
      real signature is invisible and nothing is type-checked. A typed config
      object (or a few small ones — `ObsConfig`, `GodotConfig`, `RunConfig`) would
      make the dependencies explicit. `obs.py:6` already has a TODO saying exactly
      this. Biggest readability win available.
- [ ] **Narrow the blanket `except Exception` in `gpu.py`.** Catch
      `TimeoutExpired`, `CalledProcessError`, and `ValueError` — the failures that
      genuinely mean "no usable GPU data" — so real bugs propagate instead of
      masquerading as absent hardware.
- [ ] **Split `create_obs_client`.** It connects *and* configures the stream
      service; those are two concerns and the second will grow (scene creation,
      encoder settings via `SetProfileParameter`).
- [ ] **Factor the repeated `_series` accessors.** `lambda s: s.obs and s.obs.X`
      appears five times. A tiny helper would read better and make the None-safety
      idiom explicit rather than incidental.
- [ ] **`summarize` is doing too much** — build a list of stat lines and print
      them, rather than seven near-identical conditional print blocks.
- [ ] **Make `XvfbHandle`'s binary configurable.** The `"Xvfb"` literal means
      local testing needs a PATH shim; a `--xvfb-binary` flag matches how
      `--godot-binary` and `--obs-binary` already work.

## Correctness / completeness, deferred

- [ ] **Record `child_exit_codes`.** A Godot that died at minute 3 invalidates
      every later sample and nothing in the result says so.
- [ ] **`abort_reason` should be `None`, not `""`**, on a successful run — it
      currently serializes as an empty string.
- [ ] **Formalize `BenchmarkManifest.requested` / `resolved`** — still bare
      `dict`s with "formalize this" comments. `host` is already a real model.
- [ ] **Pin `OBS_APT_VERSION`.** Now known to resolve to
      `32.2.0-0obsproject1~noble`. Until it's pinned, two boxes built a week apart
      silently run different OBS versions, which invalidates cross-box comparison.
- [ ] **`rocm-smi` isn't in the image** — needs AMD's apt repo pinned to the host
      driver. Only matters if an AMD box enters the suite.
- [ ] **Log rotation.** OBS is verbose; a 24h run's stdout log will be large.
- [ ] **Stale `#TODO`s** on `started_at` / `ended_at` in `from_args_and_rows` —
      those work now.

## Build-time vs run-time work

The entrypoint currently copies the AGD repo, runs `dotnet build`, and imports
Godot's assets on every container start. That costs a 110M copy, a NuGet restore
over the network, and an import of 95M of sprite atlases — paid once per run, per
box. Deliberate for now: baking it would mean building under QEMU on Apple
Silicon, which is the slow path precisely while iterating.

- [ ] **Cache NuGet across runs.** Mount a named volume at
      `/root/.nuget/packages` so restore happens once per box instead of once per
      run, dropping the network dependency to first-run-only. Two lines in
      compose, no build-context machinery — the cheap 80% of the win below.
- [ ] **Bake the project into the image (multi-stage, SDK in builder only).** The
      correct end state: stage the AGD repo into the build context (a `git archive`
      into a gitignored `.build/agd/`, driven by the suite runner), then COPY +
      build + `--import` as layers. The image becomes the complete artifact —
      identical bits on every box, no outbound network at run time, and the final
      stage carries only the Godot runtime rather than a whole .NET SDK. Note this
      requires **dropping the runtime project mount**: a mount at the project path
      would shadow the baked `.godot/` import cache, discarding the thing you just
      built. The two steps can't be split from the mount decision — it's one
      design switch, not an incremental optimization.
      Especially right for production: a 24/7 streaming box should not be running
      an SDK or reaching out to nuget.org.
