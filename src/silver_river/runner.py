from datetime import datetime, timezone
import time, sys
import psutil
import os
from silver_river.gpu import gpu_utilization
from silver_river.obs import create_obs_client, poll_obs_stats, load_scene_config, apply_scene, prepare_stream
from silver_river.processes import ChildProcessHandle, XvfbHandle
from silver_river.results import BenchmarkManifest, BenchmarkMetadata, BenchmarkSample, BenchmarkResult, summarize, write_output
from typing import Any

def run_benchmark(args):
    # formalize the args into something easier to work with?
    if not args.godot_env and not args.allow_idle_workload:
        raise RuntimeError("Idle workload without --allow-idle-workload set!")
    
    if not args.obs_password:
        raise RuntimeError("No OBS Websocket Password provided, the obs server won't run!")

    os.makedirs(args.output_dir, exist_ok=True)

    run_id = f"{int(time.time())}"
    rows, timing, aborted, aborted_msg = _run_and_collect(args, run_id)
    meta = BenchmarkMetadata.from_args_and_rows(args, rows, timing, aborted, aborted_msg, run_id)
    result = BenchmarkResult(
        schema_version=1,
        manifest=BenchmarkManifest.from_file(args.manifest_path, args.agd_commit, args.emulated), #TODO: create the manifest
        metadata=meta,
        samples=rows
    )
    summarize(result)
    write_output(result, args.output_dir)
    

def _run_and_collect(args, run_id:str) -> tuple[list[BenchmarkSample], dict, bool, str | None]:
    timing:dict[str, Any] = {
        'start': None,
        'end': None
    }
    aborted = False
    abort_reason = None
    xvfb_godot_proc = XvfbHandle(
        display=":99",
        name="xvfb_godot",
        width=args.width,
        height=args.height
    )
    xvfb_obs_proc = XvfbHandle(
        display=":98",
        name="xvfb_obs",
        width=args.width,
        height=args.height
    )
    godot_proc = ChildProcessHandle(
        name="godot",
        cmd=[
            args.godot_binary, f"--path", f"{args.godot_project}",
            "--windowed", f"--resolution", f"{args.width}x{args.height}",
            f"--rendering-driver" , f"{args.godot_rendering_driver}"
        ],
        env={"DISPLAY": ":99"} | dict(args.godot_env))
    obs_proc = ChildProcessHandle(
        name="obs",
        cmd=[
            args.obs_binary, "--minimize-to-tray",
            f"--websocket_port={args.obs_ws_port}",
            f"--websocket_password={args.obs_password}"
        ],
        env={"DISPLAY": ":98"})
    rows:list[BenchmarkSample] = []
    client = None
    # load the scene config now, we can think about it as independent of starting up
    # the various processes
    scene_config = load_scene_config(args.scene_config_path)

    print(f"[{args.label}] starting Xvfb ({args.width}x{args.height})")
    try:
        xvfb_godot_proc.start(args.output_dir, args.label, run_id)
        xvfb_obs_proc.start(args.output_dir, args.label, run_id)
        print(f"[{args.label}] launching Godot")
        godot_proc.start(args.output_dir, args.label, run_id)
        #sleep here to wait for the godot process to start up
        time.sleep(args.godot_warmup)
        if not godot_proc.alive():
            print(f"[{args.label}] Godot exited during warm-up -- check --godot-binary/--godot-project", file=sys.stderr)
            raise RuntimeError("Unable to start Godot")

        print(f"[{args.label}] launching OBS")
        obs_proc.start(args.output_dir, args.label, run_id)
        time.sleep(args.obs_warmup)
        if not obs_proc.alive():
            print(f"[{args.label}] OBS exited during warm-up", file=sys.stderr)
            raise RuntimeError("Unable to start OBS")
        client = create_obs_client(args)

        print(f"[{args.label}] setting up OBS stream")
        capture_path = args.output_dir / f"{args.label}_{run_id}_capture.png"
        prepare_stream(client, args, scene_config, capture_path)        

        # sampling loop
        print(f"[{args.label}] sampling for {args.duration:.0f}s every {args.interval:.0f}s")
        psutil.cpu_percent(interval=None) # prime for sampling -- otherwise the first sample will always read 0.0
        
        timing['start'] = datetime.now(timezone.utc)
        while (datetime.now(timezone.utc) - timing['start']).total_seconds() < args.duration:
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
            time.sleep(args.interval)
    except Exception as e:
        aborted = True
        abort_reason = f"{e}"
        print(f"{e}", file=sys.stderr)
    finally:
        timing['end'] = datetime.now(timezone.utc)
        print(f"[{args.label}] tearing down")
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