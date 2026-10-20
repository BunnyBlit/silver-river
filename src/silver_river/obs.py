import obsws_python as obs
from pydantic import BaseModel
from typing import Any, cast
from silver_river.results import ObsSample
from pathlib import Path
import tomllib

class TransformSpec(BaseModel):
    """Scene-item geometry specification"""
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
    enabled: bool

class SceneSpec(BaseModel):
    """A scene in obs"""
    name: str
    sources: list[SourceSpec] = []

class SceneConfig(BaseModel):
    """The root -- we can have many scenes in a configuration"""
    current_scene: str
    scenes: list[SceneSpec]

def load(path:Path) -> SceneConfig:
    return SceneConfig.model_validate(path.read_bytes())

def apply(client:obs.ReqClient, config:SceneConfig) -> None:
    _validate_config(client, config)
    for scene in config.scenes:
        client.create_scene(scene.name)
        for source, index in zip(scene.sources, range(len(scene.sources) - 1, 0, -1)):
            client.create_scene_item(scene.name, source.name, source.enabled)
            id = client.get_scene_item_id(scene.name, source.name, offset=None)
            client.set_scene_item_index(scene.name, id, index) # z axis bs -- we want first in being the bottom, not the top
            if source.transform:
                client.set_scene_item_transform(scene.name, id, dict(source.transform))


def _validate_config(client:obs.ReqClient, config:SceneConfig):
    available_inputs = cast(list, client.get_input_kind_list(False)) # the types on the obs stuff are _awful_
    for scene in config.scenes:
        for source in scene.sources:
            assert source.kind in available_inputs, f"{source.name}({source.kind}) wasn't an available inputs"
            extra = set(source.settings) - set(cast(dict, client.get_input_default_settings(source.kind)))
            assert len(extra) == 0, f"{source.name} set settings that weren't available {list(extra)}"


###### THE OTHER HALF ######
def create_obs_client(args):
    """Create a websocket client for an obs instance
        TODO: break args into a small obs client config object, so we can type it and pass it around
        a little nicer
    """

    client = obs.ReqClient(host="localhost", port=args.obs_ws_port, password=args.obs_password, timeout=5)
    client.set_stream_service_settings(
        "rtmp_custom",
        {"server": args.rtmp_url, "key": args.stream_key or ""},
    )
    return client

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