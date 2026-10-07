""" Subprocess management"""
from subprocess import Popen, DEVNULL, TimeoutExpired
from time import sleep, time
import os
from pathlib import Path

class ChildProcessHandle:
    """Generic launch/kill wrapper for a subprocess (Godot, OBS, ...)."""

    def __init__(self, name, cmd, env=None):
        self.name, self.cmd, self.proc = name, cmd, None
        self.env = dict(env or {})
        self.stdout_handle = None
        self.stderr_handle = None

    def start(self, output_dir:Path, label:str, run_id:str):
        base = f"{label}_{run_id}"
        self.stdout_handle = open(output_dir / f"{base}_{self.name}_stdout.log", "w")
        self.stderr_handle = open(output_dir / f"{base}_{self.name}_stderr.log", "w") 
        self.proc = Popen(
            self.cmd, 
            env=os.environ | self.env,
            stdout=self.stdout_handle, stderr=self.stderr_handle,
        )

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.stdout_handle: self.stdout_handle.close()
        if self.stderr_handle: self.stderr_handle.close()

        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except TimeoutExpired:
                self.proc.kill()

class XvfbHandle(ChildProcessHandle):
    """Get a handle to an Xvfb process"""

    def __init__(self, display=":99", width=1920, height=1080, depth=24):
        super().__init__(
            "xvfb",
            ["Xvfb", display, "-screen", "0", f"{width}x{height}x{depth}", "-nolisten", "tcp"]
        )
        self.display, self.width, self.height, self.depth = display, width, height, depth

    def start(self, output_dir:Path, label:str, run_id:str):
        super().start(output_dir, label, run_id)
        sleep(2)  # let Xvfb bind before anything else tries to connect