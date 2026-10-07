import shutil
import json
import subprocess
import csv
import io

from silver_river.results import GpuSample

def gpu_utilization():
    for probe in (_nvidia_gpu_stats, _amd_gpu_stats, _intel_gpu_stats):
        result = probe()
        if result:
            return result
    return None


def _nvidia_gpu_stats():
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            timeout=2,
        ).decode().strip()
        gpu_util, mem_used, mem_total = out.split(", ")
        return GpuSample(
            gpu_vendor="nvidia",
            gpu_util_pct=float(gpu_util),
            gpu_mem_used_pct=round(float(mem_used) / float(mem_total), 2),
        )
    except Exception:
        return None


def _amd_gpu_stats():
    """Best-effort via rocm-smi. Requires ROCm's apt repo added to the
    image -- not installed by default (see Dockerfile comment)."""
    if not shutil.which("rocm-smi"):
        return None
    try:
        out = subprocess.check_output(
            ["rocm-smi", "--showuse", "--showmemuse", "--csv"], timeout=3,
        ).decode().strip()
        row = next(csv.DictReader(io.StringIO(out)), None)
        if not row:
            return None
        util = row.get("GPU use (%)") or row.get("GPU_use_pct") or 0
        mem = row.get("GPU memory use (%)") or row.get("GPU_mem_use_pct") or 0
        return GpuSample(
            gpu_vendor="amd",
            gpu_util_pct=float(util),
            gpu_mem_used_pct=float(mem),
        )
    except Exception:
        return None


def _intel_gpu_stats():
    """Best-effort single-sample read via intel_gpu_top's JSON stream mode.
    Requires intel-gpu-tools and usually the 'video'/'render' group."""
    if not shutil.which("intel_gpu_top"):
        return None
    try:
        out = subprocess.check_output(
            ["timeout", "1.2", "intel_gpu_top", "-J", "-s", "1000"],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode().strip()
        obj = _extract_json(out)
        if not obj:
            return None
        parsed = json.loads(obj)
        render_busy = parsed.get("engines", {}).get("Render/3D/0", {}).get("busy")
        if render_busy:
            return GpuSample(
            gpu_vendor="intel",
            gpu_util_pct=float(render_busy),
            gpu_mem_used_pct=None
        )
        else:
            return None
    except Exception:
        return None

def _extract_json(blob) -> str | None:
    depth, buf, first_obj = 0, "", None
    for ch in blob:
        buf += ch
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and buf.strip():
                first_obj = buf
                break
    if not first_obj:
        return None
    return first_obj