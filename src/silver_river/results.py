import json
import os
import time
from pathlib import Path
from csv import DictWriter
from dataclasses import dataclass
from pydantic import BaseModel
from datetime import datetime

class BenchmarkSample(BaseModel):
    timestamp: datetime
    elapsed_s: float
    host_cpu_pct: float
    host_mem_pct: float
    gpu: GpuSample | None
    obs: ObsSample | None
    error: str | None

class GpuSample(BaseModel):
    gpu_vendor: str
    gpu_util_pct: float
    gpu_mem_used_pct: float | None

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

class BenchmarkManifest(BaseModel):
    requested: dict #formalize this
    resolved: dict #formalize this
    built_at: datetime
    host: dict #TODO: formalize this
    agd_commit: str

class BenchmarkMetadata(BaseModel):
    label: str
    started_at: datetime
    ended_at: datetime
    duration_s: int
    interval_s: int
    width: int
    height: int
    rendering_driver: str
    rtmp_url: str
    godot_env: dict[str, str]
    # these results are run-level, so they don't need to be recomputed on the analysis side
    output_skipped_pct: float
    threshold_pct: float
    outcome: str

@dataclass
class BenchmarkResult(BaseModel):
    schema_version:int
    manifest: BenchmarkManifest
    metadata: BenchmarkMetadata
    samples: list[BenchmarkSample]


def summarize(rows, label) -> None:
    if not rows:
        print("No samples collected -- check that OBS/websocket started correctly.")
        return

    def series(key):
        return [r[key] for r in rows if key in r and r[key] is not None]

    fps, cpu = series("active_fps"), series("host_cpu_pct")
    render_total, render_skipped = series("render_total_frames"), series("render_skipped_frames")
    output_total, output_skipped = series("output_total_frames"), series("output_skipped_frames")
    gpu_util = series("gpu_util_pct")
    gpu_vendor = next((r["gpu_vendor"] for r in rows if "gpu_vendor" in r), None)

    print(f"\n=== Summary: {label} ===")
    print(f"Samples collected: {len(rows)}")
    if fps:
        print(f"Active FPS: min={min(fps):.1f} avg={sum(fps)/len(fps):.1f} max={max(fps):.1f}")
    if cpu:
        print(f"Host CPU%: min={min(cpu):.1f} avg={sum(cpu)/len(cpu):.1f} max={max(cpu):.1f}")
    if gpu_util:
        print(f"GPU ({gpu_vendor}) util%: min={min(gpu_util):.1f} avg={sum(gpu_util)/len(gpu_util):.1f} max={max(gpu_util):.1f}")
    if render_total and render_skipped:
        dropped, total = render_skipped[-1] - render_skipped[0], render_total[-1] - render_total[0]
        pct = (dropped / total * 100) if total else 0
        print(f"Render frames skipped during run: {dropped}/{total} ({pct:.2f}%)")
    if output_total and output_skipped:
        dropped, total = output_skipped[-1] - output_skipped[0], output_total[-1] - output_total[0]
        pct = (dropped / total * 100) if total else 0
        print(f"Output (encode) frames skipped during run: {dropped}/{total} ({pct:.2f}%)")
        if pct > 0.1:
            print("  ^ This is the number that decides pass/fail. Encode drops are what")
            print("    viewers actually see as stutter. >0.1% sustained = this config fails.")

def write_output(rows, output_dir:Path, label:str):
    file_name = f"{label}_{int(time.time())}"
    with open(output_dir / f"{file_name}.json", "w") as f:
        json.dump(rows, f, indent=2)
    if rows:
        with open(output_dir / f"{file_name}.csv", "w", newline="") as f:
            writer = DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
            writer.writeheader()
            writer.writerows(rows)
    print(f"Raw results written to {file_name}.json / {file_name}.csv")