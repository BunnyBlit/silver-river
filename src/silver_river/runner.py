from datetime import datetime, timezone
import time, sys
import psutil
import os
from silver_river.gpu import gpu_utilization
from silver_river.obs import create_obs_client, poll_obs_stats, load_scene_config, apply_scene, prepare_stream
from silver_river.processes import ChildProcessHandle, XvfbHandle
from silver_river.results import BenchmarkManifest, BenchmarkMetadata, BenchmarkSample, BenchmarkResult, summarize, write_output
from typing import Any

from silver_river.settings import BenchSettings

def run_benchmark(settings:BenchSettings):
    os.makedirs(settings.output_dir, exist_ok=True)

    run_id = f"{int(time.time())}"
    rows, timing, aborted, aborted_msg = _run_and_collect(settings, run_id)
    meta = BenchmarkMetadata.from_settings_and_rows(settings, rows, timing, aborted, aborted_msg, run_id)
    result = BenchmarkResult(
        schema_version=1,
        manifest=BenchmarkManifest.from_file(settings.manifest_path, settings.agd_commit, settings.emulated),
        metadata=meta,
        samples=rows
    )
    summarize(result)
    write_output(result, settings.output_dir)
    

def _run_and_collect(settings:BenchSettings, run_id:str) -> tuple[list[BenchmarkSample], dict, bool, str | None]:
    timing:dict[str, Any] = {
        'start': None,
        'end': None
    }
    aborted = False
    abort_reason = None
    xvfb_godot_proc = XvfbHandle(
        display=":99",
        name="xvfb_godot",
        width=settings.width,
        height=settings.height
    )
    xvfb_obs_proc = XvfbHandle(
        display=":98",
        name="xvfb_obs",
        width=settings.width,
        height=settings.height
    )
    godot_proc = ChildProcessHandle(
        name="godot",
        cmd=[
            settings.godot_binary, f"--path", f"{settings.godot_project}",
            "--windowed", f"--resolution", f"{settings.width}x{settings.height}",
            f"--rendering-driver" , f"{settings.godot_rendering_driver}"
        ],
        env={"DISPLAY": ":99"} | dict(settings.godot_env))
    obs_proc = ChildProcessHandle(
        name="obs",
        cmd=[
            settings.obs_binary, "--minimize-to-tray",
            f"--websocket_port={settings.obs_ws_port}",
            f"--websocket_password={settings.obs_password.get_secret_value()}"
        ],
        env={"DISPLAY": ":98"})
    rows:list[BenchmarkSample] = []
    client = None
    # load the scene config now, we can think about it as independent of starting up
    # the various processes
    scene_config = load_scene_config(settings.scene_config_path)

    print(f"[{settings.label}] starting Xvfb ({settings.width}x{settings.height})")
    try:
        xvfb_godot_proc.start(settings.output_dir, settings.label, run_id)
        xvfb_obs_proc.start(settings.output_dir, settings.label, run_id)
        print(f"[{settings.label}] launching Godot")
        godot_proc.start(settings.output_dir, settings.label, run_id)
        #sleep here to wait for the godot process to start up
        time.sleep(settings.godot_warmup)
        if not godot_proc.alive():
            print(f"[{settings.label}] Godot exited during warm-up -- check --godot-binary/--godot-project", file=sys.stderr)
            raise RuntimeError("Unable to start Godot")

        print(f"[{settings.label}] launching OBS")
        obs_proc.start(settings.output_dir, settings.label, run_id)
        time.sleep(settings.obs_warmup)
        if not obs_proc.alive():
            print(f"[{settings.label}] OBS exited during warm-up", file=sys.stderr)
            raise RuntimeError("Unable to start OBS")
        client = create_obs_client(settings)

        print(f"[{settings.label}] setting up OBS stream")
        capture_path = settings.output_dir / f"{settings.label}_{run_id}_capture.png"
        prepare_stream(client, settings, scene_config, capture_path)        

        # sampling loop
        print(f"[{settings.label}] sampling for {settings.duration:.0f}s every {settings.interval:.0f}s")
        psutil.cpu_percent(interval=None) # prime for sampling -- otherwise the first sample will always read 0.0
        
        timing['start'] = datetime.now(timezone.utc)
        while (datetime.now(timezone.utc) - timing['start']).total_seconds() < settings.duration:
            if not godot_proc.alive(): raise RuntimeError("...Godot died mid-run")

            sample = BenchmarkSample(
                timestamp=datetime.now(timezone.utc),
                elapsed_s=(datetime.now(timezone.utc) - timing['start']).total_seconds(),
                host_cpu_pct=psutil.cpu_percent(interval=None),
                host_mem_pct=psutil.virtual_memory().percent,
                gpu=None,
                obs=None,
                error=None
            )
            gpu = gpu_utilization()
            if gpu:
                sample.gpu = gpu
            try:
                sample.obs = poll_obs_stats(client)
            except Exception as e:
                sample.error = str(e)
            rows.append(sample)
            time.sleep(settings.interval)
    except Exception as e:
        aborted = True
        abort_reason = f"{e}"
        print(f"{e}", file=sys.stderr)
    finally:
        timing['end'] = datetime.now(timezone.utc)
        print(f"[{settings.label}] tearing down")
        if client:
            try:
                client.disconnect()
            except Exception:
                pass
        obs_proc.stop()
        godot_proc.stop()
        xvfb_godot_proc.stop()
        xvfb_obs_proc.stop()

    return rows, timing, aborted, abort_reason