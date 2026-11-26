from pydantic import model_validator, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal
from pathlib import Path
import os

# can't express fly's dedicated tier, AWS/GCP on-demand only
MEASURE_PROVIDERS = frozenset(["hetzner", "digitalocean", "fly", "aws", "gcp", "runpod-secure", "lambda"])

class BenchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SR_", extra="forbid",
        hide_input_in_errors=True)
    label:str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    role: Literal["debug", "measure"]
    agd_commit: str = Field(pattern=r"^[0-9a-f]{7,40}(-dirty)?$")
    obs_password: SecretStr = Field(min_length=1)
    provider: str | None = None
    emulated: bool = False
    width: int = Field(1280, gt=0)
    height: int = Field(720, gt=0)
    fps: int = Field(30, gt=0)
    duration: int = Field(1800, gt=0)
    interval: int = Field(2, gt=0)
    godot_env: dict[str, str] = {}
    godot_warmup: int = Field(12, gt=0)
    obs_warmup: int = Field(28, gt=0)
    allow_idle_workload: bool = False
    rtmp_url: str = "rtmp://mediamtx:1935/benchmark"
    stream_key: SecretStr = SecretStr("")
    output_dir: Path = Path("/bench/benchmark_results")
    scene_config_path: Path = Path("/bench/config/benchmark_scene.toml")
    manifest_path: Path = Path("/bench/manifest.json")
    obs_ws_port: int = Field(4455, ge=1, le=65535)
    godot_binary: str = "godot4"
    obs_binary: str = "obs"
    godot_rendering_driver: Literal["opengl3", "vulkan"] = "opengl3"
    godot_project: Path = Path("/bench/work/godot")
    

    @model_validator(mode="after")
    def _trust_rules(self):
        if self.role == "measure":
            if self.agd_commit.endswith("-dirty"):
                raise ValueError("a measure run needs a clean AGD checkout")
            if self.emulated:
                raise ValueError("a measure run cannot be emulated")
            if self.provider not in MEASURE_PROVIDERS:
                raise ValueError(f"provider {self.provider!r} is not on the list of providers to measure")
        return self
    
    @model_validator(mode="after")
    def _workload_rules(self):
        if not self.godot_env:
            if self.role == "measure":
                raise ValueError("a measure run needs a BRAWLER_* workload")
            if self.allow_idle_workload is False:
                raise ValueError("no BRAWLER_* workload set; pass SR_ALLOW_IDLE_WORKLOAD=true to run idle")
            return self

        rules = self.godot_env.get("BRAWLER_RULES")
        if not rules:
            raise ValueError(f"BRAWLER_RULES must be provided as 'timed' or 'timed:<seconds>'")
        if not rules.startswith("timed"):
            raise ValueError(f"BRAWLER_RULES must be provided as 'timed' or 'timed:<seconds>'")
        try:
            provided_time = int(rules.split(":")[1]) if ":" in rules else 120.0
        except ValueError as e:
            raise ValueError(f"{rules.split(":")[1]} is not valid, BRAWLER_RULES must be set with 'timed:<seconds>'") from e
        if provided_time < self.duration + self.godot_warmup + self.obs_warmup:
                raise ValueError(f"provided time needs to be longer than {self.duration + self.godot_warmup + self.obs_warmup}s")
        return self
    
    @model_validator(mode="after")
    def _settings_rules(self):
        if self.interval >= self.duration:
            raise ValueError(f"interval {self.interval} must be less than duration {self.duration}")
        return self
    
def load_settings() -> BenchSettings:
    known = set(f"SR_{name.upper()}" for name in BenchSettings.model_fields) - {"SR_GODOT_ENV"}
    unknown = set(k for k in os.environ if k.startswith("SR_") and k not in known)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")

    brawler_settings = {k: v for k, v in os.environ.items() if k.startswith("BRAWLER_")}
    return BenchSettings(godot_env=brawler_settings)  # pyright: ignore[reportCallIssue]  -- fields come from the environment

