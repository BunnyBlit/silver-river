"""CLI for Silver River"""
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from silver_river.runner import run_benchmark
from pathlib import Path
import os

def bench(args):
    """run a benchmark"""
    run_benchmark(args)

def build_cli() -> ArgumentParser:
    """Create the CLI we're going to use"""
    p = ArgumentParser(description="24/7 Streaming Harness for BrawlerAGD")
    sub = p.add_subparsers(dest="command", required=True, help="Subcommands")

    parser_bench = sub.add_parser("bench", help="Run a streaming benchmark")
    parser_bench.add_argument("--label", required=True, help="Name for this run, e.g. the cloud instance type being tested")
    parser_bench.add_argument("--godot-binary", default="godot4")
    parser_bench.add_argument("--godot-project", required=True)
    parser_bench.add_argument("--godot-warmup", type=float, default=5.0)
    parser_bench.add_argument("--godot-env", 
        action='append',
        default=(),
        type=lambda arg_string: tuple(arg_string.split("=", 1)),
        help="Repeatable arg for passing things to the godot process environment to define the workload"
    )
    parser_bench.add_argument("--godot-rendering-driver", type=str, default="opengl3")
    parser_bench.add_argument("--allow-idle-workload", action="store_true", help="Allow benchmarks with an idle workload, no godot-env params passed")
    parser_bench.add_argument("--obs-binary", default="obs")
    parser_bench.add_argument("--obs-warmup", type=float, default=8.0)
    parser_bench.add_argument("--obs-password", default=os.environ.get("OBS_WS_PASSWORD", ""))
    parser_bench.add_argument("--obs-ws-port", type=int, default=4455)
    parser_bench.add_argument("--rtmp-url", required=True,
                   help="RTMP sink for this test run. Use a local sink (e.g. MediaMTX)")
    parser_bench.add_argument("--stream-key", default="")
    parser_bench.add_argument("--display", default=":99")
    parser_bench.add_argument("--width", type=int, default=1280)
    parser_bench.add_argument("--height", type=int, default=720)
    parser_bench.add_argument("--duration", type=float, default=300, help="Sampling duration in seconds")
    parser_bench.add_argument("--interval", type=float, default=2.0, help="Seconds between samples")
    parser_bench.add_argument("--output-dir", type=Path, default="./benchmark_results")
    parser_bench.add_argument("--manifest-path", type=Path, default="/bench/manifest.json")
    parser_bench.add_argument("--agd-commit", type=str)
    parser_bench.add_argument("--emulated", action="store_true", help="if we were run under emulation or not")
    
    parser_bench.set_defaults(func=bench)

    return p

def main():
    cli = build_cli()
    args = cli.parse_args()
    args.func(args)