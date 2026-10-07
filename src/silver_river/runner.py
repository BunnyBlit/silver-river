from datetime import datetime, timezone
import time, sys
import obsws_python as obs
import psutil
from dataclasses import asdict
from silver_river.gpu import gpu_utilization
from silver_river.obs import create_obs_client, poll_obs_stats
from silver_river.processes import ChildProcessHandle, XvfbHandle
from silver_river.results import BenchmarkSample, summarize, write_output

def run_benchmark(args):
    # formalize the args into something easier to work with?
    rows = _run_and_collect(args)
    summarize(rows, args.label)
    write_output(rows, args.output_dir, args.label)

def _run_and_collect(args) -> list:
    xvfb_proc = XvfbHandle(display=args.display, width=args.width, height=args.height)
    godot_proc = ChildProcessHandle(
        name="godot",
        cmd=[
            args.godot_binary, f"--path={args.godot_project}",
            "--windowed", f"--resolution={args.width}x{args.height}",
            f"--rendering-driver={args.godot_rendering_driver}"
        ],
        env={"DISPLAY":xvfb_proc.display} | args.godot_env)
    obs_proc = ChildProcessHandle(
        name="obs",
        cmd=[
            args.obs_binary, "--minimize-to-tray", "--startstreaming",
            f"--websocket_port={args.obs_ws_port}",
            f"--websocket_password={args.obs_password}"
        ],
        env={"DISPLAY":xvfb_proc.display})
    rows = []
    print(f"[{args.label}] starting Xvfb on {args.display} ({args.width}x{args.height})")
    client = None

    run_id = f"{int(time.time())}"
    try:
        xvfb_proc.start(args.output_dir, args.label, run_id)

        #FIXME / TODO: we should probably fix this? We can factor in the wait time for these processes
        # at the end
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

        print(f"[{args.label}] sampling for {args.duration:.0f}s every {args.interval:.0f}s")
        # sampling loop
        start = time.time()
        while time.time() - start < args.duration:
            if not godot_proc.alive(): raise RuntimeError("...Godot died mid-run")

            sample = BenchmarkSample(
                timestamp=datetime.now(timezone.utc),
                elapsed_s=round(time.time() - start, 1),
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
    finally:
        print(f"[{args.label}] tearing down")
        if client:
            try:
                client.disconnect()
            except Exception:
                pass
        obs_proc.stop()
        godot_proc.stop()
        xvfb_proc.stop()

    return rows