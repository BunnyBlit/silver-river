import psutil
import platform
import cpuinfo
import json
from pathlib import Path
from csv import DictWriter
from pydantic import BaseModel
from datetime import datetime
from typing import Callable, get_args

FAIL_THRESHOLD = 0.1

def read_cpu_quota() -> float | None:
    """Effective CPU core limit from the cgroup, or None if unlimited/unreadable.
    """
    # cgroup v2 -- "<quota> <period>", or "max <period>" when uncapped
    try:
        quota_str, period_str = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota_str != "max":
            period = float(period_str)
            return float(quota_str) / period if period else None
        return None
    except (OSError, ValueError):
        pass

    # cgroup v1 -- separate files; a quota of -1 means uncapped
    try:
        quota = float(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text().strip())
        period = float(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text().strip())
        if quota > 0 and period > 0:
            return quota / period
    except (OSError, ValueError):
        pass

    return None


class HostInfo(BaseModel):
    kernel: str
    arch: str
    cpu_model: str | None
    cpu_count_logical: int | None
    cpu_count_physical: int | None
    cpu_quota: float | None = None  # effective core limit; None means uncapped
    mem_total_bytes: int
    emulated: bool

    @staticmethod
    def build_info(emulated:bool) -> HostInfo:
        return HostInfo(
            kernel=platform.uname().release,
            arch=platform.uname().machine,
            cpu_model=(cpuinfo.get_cpu_info() or {}).get("brand_raw", None),
            cpu_count_logical=psutil.cpu_count(logical=True),
            cpu_count_physical=psutil.cpu_count(logical=False),
            cpu_quota=read_cpu_quota(),
            mem_total_bytes=psutil.virtual_memory().total,
            emulated=emulated
        )

class GpuSample(BaseModel):
    vendor: str
    util_pct: float
    mem_used_pct: float | None = None

class ObsSample(BaseModel):
    cpu_usage_pct: float
    memory_usage_mb: float
    active_fps: float
    avg_frame_render_time_ms: float
    render_skipped_frames: float
    render_total_frames: float
    output_skipped_frames: float
    output_total_frames: float
    free_disk_space_mb: float

class BenchmarkSample(BaseModel):
    timestamp: datetime
    elapsed_s: float
    host_cpu_pct: float
    host_mem_pct: float
    gpu: GpuSample | None = None
    obs: ObsSample | None = None
    error: str | None

class BenchmarkManifest(BaseModel):
    requested: dict #formalize this
    resolved: dict #formalize this
    built_at: datetime | None
    host: HostInfo
    agd_commit: str

    @staticmethod
    def from_file(path:Path, commit:str, emulated:bool) -> BenchmarkManifest:
        host_info = HostInfo.build_info(emulated)
        with path.open("r") as f:
            raw:dict = json.load(f)
            return BenchmarkManifest(
                requested=raw.get("requested", {}),
                resolved=raw.get("resolved", {}),
                built_at=raw.get("built_at", None),
                host=host_info,
                agd_commit=commit
            )

class BenchmarkMetadata(BaseModel):
    run_id: str
    label: str
    started_at: datetime
    ended_at: datetime
    duration_s: float
    interval_s: float
    width: int
    height: int
    rendering_driver: str
    rtmp_url: str
    godot_env: dict[str, str]
    # these results are run-level, so they don't need to be recomputed on the analysis side
    output_skipped_pct: float
    render_dropped_pct: float
    threshold_pct: float
    outcome: str
    aborted_reason: str | None = None

    @staticmethod
    def from_args_and_rows(args, rows:list[BenchmarkSample], timing, aborted, aborted_message, run_id) -> BenchmarkMetadata:
        skipped_pct = calc_output_drop_pct(rows)
        render_drop_pct = calc_render_drop_pct(rows)

        # outcome is annoying to figure out:
        # aborted if aborted then
        # no_data if len(rows) = 0 then
        # pass if skipped_pct <= FAIL_THRESHOLD else
        # fail
        outcome=""
        if aborted:
            outcome="aborted"
        elif len(rows) == 0:
            outcome="no_data"
        elif skipped_pct <= FAIL_THRESHOLD:
            outcome="pass"
        else:
            outcome="fail"

        return BenchmarkMetadata(
            run_id=run_id,
            label=args.label,
            width=args.width,
            height=args.height,
            rtmp_url=args.rtmp_url,
            interval_s=args.interval,
            duration_s=args.duration,
            rendering_driver=args.godot_rendering_driver,
            godot_env=dict(args.godot_env),
            started_at=timing["start"], #TODO
            ended_at=timing["end"], #TODO
            output_skipped_pct=skipped_pct,
            render_dropped_pct=render_drop_pct,
            threshold_pct=FAIL_THRESHOLD,
            outcome=outcome,
            aborted_reason=aborted_message
        )

class BenchmarkResult(BaseModel):
    schema_version:int
    manifest: BenchmarkManifest
    metadata: BenchmarkMetadata
    samples: list[BenchmarkSample]


def _series[T](rows:list[BenchmarkSample], get: Callable[[BenchmarkSample], T | None]) -> list[T]:
    """ Given a list of rows and an accessor function, create a series of just the values
    from the accessor
    """
    return [value for row in rows if (value := get(row)) is not None]

def calc_output_drop_pct(rows) -> float:
    """Calculate the drop rate for samples"""
    if not rows:
        return 0.0
    output_total = _series(rows, lambda sample: sample.obs and sample.obs.output_total_frames)
    output_skipped = _series(rows, lambda sample: sample.obs and sample.obs.output_skipped_frames)

    if not output_total or not output_skipped:
        return 0.0
    
    dropped, total = max(output_skipped[-1] - output_skipped[0], 0.0), max(output_total[-1] - output_total[0], 0.0)
    return (dropped / total) * 100 if total else 0.0

def calc_render_drop_pct(rows:list[BenchmarkSample]) -> float:
    if not rows:
        return 0.0
    
    render_total = _series(rows, lambda sample: sample.obs and sample.obs.render_total_frames)
    render_skipped  = _series(rows, lambda sample: sample.obs and sample.obs.render_skipped_frames)
    if not render_total or not render_skipped:
        return 0.0
    
    dropped, total = max(render_skipped[-1] - render_skipped[0], 0.0), max(render_total[-1] - render_total[0], 0.0)
    return (dropped / total) * 100 if total else 0.0


def summarize(result: BenchmarkResult) -> None:
    """Print the run's headline numbers.

    Takes the finished result rather than recomputing the rates: the console and
    the result file must never be able to disagree about a verdict.
    """
    rows, meta = result.samples, result.metadata
    if not rows:
        print("No samples collected -- check that OBS/websocket started correctly.")
        return

    fps = _series(rows, lambda sample: sample.obs and sample.obs.active_fps)
    cpu = _series(rows, lambda sample: sample.host_cpu_pct)

    gpu_util = _series(rows, lambda sample: sample.gpu and sample.gpu.util_pct)
    # FIXME: kinda a janky way to do this, but it does work
    gpu_vendor = next(iter(_series(rows, lambda sample: sample.gpu and sample.gpu.vendor)), None)

    print(f"\n=== Summary: {meta.label} ===")
    print(f"Samples collected: {len(rows)}")
    if fps:
        print(f"Active FPS: min={min(fps):.1f} avg={sum(fps)/len(fps):.1f} max={max(fps):.1f}")
    if cpu:
        print(f"Host CPU%: min={min(cpu):.1f} avg={sum(cpu)/len(cpu):.1f} max={max(cpu):.1f}")
    if gpu_util:
        print(f"GPU ({gpu_vendor}) util%: min={min(gpu_util):.1f} avg={sum(gpu_util)/len(gpu_util):.1f} max={max(gpu_util):.1f}")
    print(f"Render frames skipped during run: {meta.render_dropped_pct:.2f}%")
    print(f"Output (encode) frames skipped during run: {meta.output_skipped_pct:.2f}%")
    print(f"Outcome: {meta.outcome.upper()} (fail above {meta.threshold_pct:.2f}%)")
    if meta.outcome == "fail":
        print("  ^ This is the number that decides pass/fail. Encode drops are what")
        print("    viewers actually see as stutter. >0.1% sustained = this config fails.")
    if meta.aborted_reason:
        print(f"  Aborted: {meta.aborted_reason}")

def write_output(result: BenchmarkResult, output_dir:Path):
    file_name = f"{result.metadata.label}_{result.metadata.run_id}"
    with open(output_dir / f"{file_name}.json", "w") as f:
        f.write(result.model_dump_json(indent=2))
        print(f"Raw results written to {file_name}.json")

    if result.samples:
        with open(output_dir / f"{file_name}.csv", "w", newline="") as f:
            writer = DictWriter(f, fieldnames=["run_id", "label"] + flat_columns(BenchmarkSample))
            writer.writeheader()
            writer.writerows(
                [{
                    "run_id": result.metadata.run_id,
                    "label": result.metadata.label,
                    **flatten_row(sample)
                } for sample in result.samples])
            print(f"Raw results written to {file_name}.csv")
    
   
def _nested_model(annotation) -> type[BaseModel] | None:
    """The BaseModel inside an annotation, unwrapping optionals
    `GpuSample | None` -> GpuSample; `float | None` -> None.
    """
    for candidate in (get_args(annotation) or (annotation,)):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


def flat_columns(model_cls: type[BaseModel], parent_key: str = "", sep: str = "_") -> list[str]:
    """CSV column names for a model, derived from a mode's fields"""
    columns: list[str] = []
    for name, field in model_cls.model_fields.items():
        key = f"{parent_key}{sep}{name}" if parent_key else name
        nested = _nested_model(field.annotation)
        if nested is not None:
            columns.extend(flat_columns(nested, key, sep=sep))
        else:
            columns.append(key)
    return columns


def flatten_row(model: BaseModel, sep: str = "_") -> dict:
    """One flat, JSON-scalar row for a model instance, keyed to match
    flat_columns(type(model))."""
    return _flatten(model.model_dump(mode="json"), type(model), sep=sep)


def _flatten(data: dict, model_cls: type[BaseModel], parent_key: str = "", sep: str = "_") -> dict:
    items: dict = {}
    for name, field in model_cls.model_fields.items():
        key = f"{parent_key}{sep}{name}" if parent_key else name
        value = data.get(name)
        nested = _nested_model(field.annotation)
        if nested is not None:
            # An absent sub-model still contributes its columns, all empty --
            # recursing on {} makes every nested lookup resolve to None.
            items.update(_flatten(value or {}, nested, key, sep=sep))
        else:
            items[key] = value
    return items
