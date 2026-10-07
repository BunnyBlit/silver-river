import obsws_python as obs

from silver_river.results import ObsSample

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