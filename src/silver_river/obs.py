import obsws_python as obs
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from typing import Any
from silver_river.results import ObsSample
from pathlib import Path
import tomllib
import time

class TransformSpec(BaseModel):
    """Scene-item geometry specification"""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )
    position_x: float | None = None
    position_y: float | None = None
    scale_x: float | None = None
    scale_y: float | None = None
    rotation: float | None = None
    bounds_width: float | None = None
    bounds_height: float | None = None
    crop_left: float | None = None
    crop_right: float | None = None
    crop_top: float | None = None
    crop_bottom: float | None = None

class SourceSpec(BaseModel):
    """An input into an obs scene"""
    name: str
    kind: str
    settings: dict[str, Any] = {}
    transform: TransformSpec | None = None
    enabled: bool = True

class SceneSpec(BaseModel):
    """A scene in obs"""
    name: str
    sources: list[SourceSpec] = []

class SceneConfig(BaseModel):
    """The root -- we can have many scenes in a configuration"""
    current_scene: str
    scenes: list[SceneSpec]

def load_scene_config(path:Path) -> SceneConfig:
    with open(path, "rb") as f:
        toml = tomllib.load(f)
        return SceneConfig.model_validate(toml)

def apply_scene(client:obs.ReqClient, config:SceneConfig) -> None:
    _validate_config(client, config)
    for scene in config.scenes:
        client.create_scene(scene.name)
        for source in scene.sources:
            client.create_input(scene.name, source.name, source.kind, source.settings, source.enabled)
            item_id = _scene_item_id(client, scene.name, source.name)
            if source.transform:
                client.set_scene_item_transform(scene.name, item_id, source.transform.model_dump(by_alias=True, exclude_none=True))
    client.set_current_program_scene(config.current_scene)


def _validate_config(client:obs.ReqClient, config:SceneConfig):
    available_inputs = _input_kinds(client)
    if config.current_scene not in [scene.name for scene in config.scenes]:
        raise RuntimeError(f"{config.current_scene} does not name a known scene")
    for scene in config.scenes:
        for source in scene.sources:
            if source.kind not in available_inputs:
                raise RuntimeError(f"{source.name}({source.kind}) wasn't an available inputs")
            extra = set(source.settings) - set(_default_settings(client, source.kind))
            if len(extra) != 0:
                raise RuntimeError(f"{source.name} set settings that weren't available {list(extra)}")

# Wrapper functions around various obs.ReqClient functions because their typing is 
# awful
def _input_kinds(client: obs.ReqClient) -> list[str]:
    resp = client.get_input_kind_list(False)
    kinds = getattr(resp, "input_kinds", None)
    if not isinstance(kinds, list):
        raise RuntimeError(f"unexpected GetInputKindList response: {resp!r}")
    return kinds


def _default_settings(client: obs.ReqClient, kind: str) -> dict[str, Any]:
    resp = client.get_input_default_settings(kind)
    settings = getattr(resp, "default_input_settings", None)
    if not isinstance(settings, dict):
        raise RuntimeError(f"unexpected GetInputDefaultSettings response: {resp!r}")
    return settings


def _scene_item_id(client: obs.ReqClient, scene_name: str, source_name:str) -> int:
    resp = client.get_scene_item_id(scene_name, source_name)
    item_id = getattr(resp, "scene_item_id", None)
    if not isinstance(item_id, int):
        raise RuntimeError(f"no scene_item_id for {source_name!r} in {scene_name!r}: {resp!r}")
    return item_id

def _get_stream_status(client: obs.ReqClient) -> bool:
    resp = client.get_stream_status()
    status = getattr(resp, "output_active", None)
    if not isinstance(status, bool):
        raise RuntimeError(f"no output_active on get_stream_status: {resp!r}")
    return status 

###### THE OTHER HALF ######
def create_obs_client(args):
    """Create a websocket client for an obs instance
        TODO: break args into a small obs client config object, so we can type it and pass it around
        a little nicer
    """

    client = obs.ReqClient(host="localhost", port=args.obs_ws_port, password=args.obs_password, timeout=5)
    
    return client

def prepare_stream(client:obs.ReqClient, args, scene_config:SceneConfig):
    """Set up the client for streaming to an rtmp sink, kick off streaming and verify
    we're good to go"""
    client.set_stream_service_settings(
        "rtmp_custom",
        {"server": args.rtmp_url, "key": args.stream_key or ""},
    )
    client.set_video_settings(args.fps, 1, args.width, args.height, args.width, args.height)
    apply_scene(client, scene_config)
    client.start_stream()

    active = False
    for _ in range(0, 5):
        time.sleep(2)
        up = _get_stream_status(client)
        if up:
            active = True
            break
    
    if not active:
        raise RuntimeError("Timed out waiting for stream to start")


def poll_obs_stats(client):
    """The fields we care about for pipeline health
       not typing the client because the typedefs for it are janky"""
    stats = client.get_stats()

    return ObsSample(
        cpu_usage_pct=stats.cpu_usage,
        memory_usage_mb=stats.memory_usage,
        active_fps=stats.active_fps,
        avg_frame_render_time_ms=stats.average_frame_render_time,
        render_skipped_frames=stats.render_skipped_frames,
        render_total_frames=stats.render_total_frames,
        output_skipped_frames=stats.output_skipped_frames,
        output_total_frames=stats.output_total_frames,
        free_disk_space_mb=stats.available_disk_space,
    )