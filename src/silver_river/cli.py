"""CLI for Silver River"""
from argparse import ArgumentParser
from pydantic import ValidationError
from silver_river.runner import run_benchmark
from silver_river.settings import BenchSettings, load_settings
import sys

def bench(settings: BenchSettings):
    """run a benchmark"""
    run_benchmark(settings)

def check(settings: BenchSettings):
    """Validate the environment and print settings"""
    print(settings.model_dump_json(indent=2))

def build_cli() -> ArgumentParser:
    """Create the CLI we're going to use"""
    p = ArgumentParser(description="24/7 Streaming Harness for BrawlerAGD")
    sub = p.add_subparsers(dest="command", required=True, help="Subcommands")
    sub.add_parser("bench", help="Run a streaming benchmark").set_defaults(func=bench)
    sub.add_parser("check", help="Validate settings from the environment and print them").set_defaults(func=check)
    return p

def main():
    cli = build_cli()
    args = cli.parse_args()
    try:
        settings = load_settings()
    except (ValidationError, ValueError) as e:
        print(f"invalid settings:\n{e}", file=sys.stderr)
        sys.exit(2)
    args.func(settings)