import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Dict, Tuple


class InstanceError(RuntimeError):
    """Raised when a per-session instance cannot be provisioned."""


@dataclass
class Instance:
    session_id: str
    username: str
    display: int
    websocket_port: int
    processes: Tuple[subprocess.Popen, ...]


class InstanceManager:
    def __init__(
        self,
        *,
        base_display: int,
        max_instances: int,
        base_websocket_port: int,
        geometry: str,
        depth: int,
        dosbox_conf: str,
        dosbox_binary: str = "dosbox",
        vnc_binary: str = "vncserver",
        websockify_binary: str = "websockify",
    ) -> None:
        self.base_display = base_display
        self.max_instances = max_instances
        self.base_websocket_port = base_websocket_port
        self.geometry = geometry
        self.depth = depth
        self.dosbox_conf = dosbox_conf
        self.dosbox_binary = dosbox_binary
        self.vnc_binary = vnc_binary
        self.websockify_binary = websockify_binary
        self._instances: Dict[str, Instance] = {}
        self._lock = threading.Lock()

    def _allocate_slot(self) -> Tuple[int, int]:
        used_displays = {instance.display for instance in self._instances.values()}
        for offset in range(self.max_instances):
            display = self.base_display + offset
            if display not in used_displays:
                ws_port = self.base_websocket_port + offset
                return display, ws_port
        raise InstanceError("No free session slots available")

    def _spawn_process(self, command, env=None) -> subprocess.Popen:
        return subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _start_vnc(self, display: int) -> None:
        subprocess.run(
            [self.vnc_binary, "-kill", f":{display}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        cmd = [
            self.vnc_binary,
            f":{display}",
            "-geometry",
            self.geometry,
            "-depth",
            str(self.depth),
            "-localhost",
        ]
        completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if completed.returncode != 0:
            raise InstanceError(
                f"Failed to start VNC server (display :{display}): {completed.stderr.decode('utf-8', 'ignore')}"
            )

    def _start_dosbox(self, display: int) -> subprocess.Popen:
        env = os.environ.copy()
        env["DISPLAY"] = f":{display}"
        return self._spawn_process(
            [
                self.dosbox_binary,
                "-fullscreen",
                "-conf",
                self.dosbox_conf,
            ],
            env=env,
        )

    def _start_websockify(self, websocket_port: int, display: int) -> subprocess.Popen:
        target = f"localhost:{5900 + display}"
        return self._spawn_process(
            [
                self.websockify_binary,
                "--idle-timeout",
                "30",
                str(websocket_port),
                target,
            ]
        )

    def start_session(self, session_id: str, username: str) -> Tuple[int, int]:
        with self._lock:
            if session_id in self._instances:
                instance = self._instances[session_id]
                return instance.display, instance.websocket_port

            display, ws_port = self._allocate_slot()
            processes = []
            try:
                self._start_vnc(display)
                time.sleep(1)  # allow VNC to initialize
                dosbox_proc = self._start_dosbox(display)
                processes.append(dosbox_proc)
                ws_proc = self._start_websockify(ws_port, display)
                processes.append(ws_proc)
            except Exception as exc:  # pragma: no cover - defensive cleanup
                for proc in processes:
                    if proc.poll() is None:
                        proc.terminate()
                subprocess.run(
                    [self.vnc_binary, "-kill", f":{display}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                raise InstanceError(f"Failed to provision session: {exc}") from exc

            self._instances[session_id] = Instance(
                session_id=session_id,
                username=username,
                display=display,
                websocket_port=ws_port,
                processes=tuple(processes),
            )
            return display, ws_port

    def ensure_session(self, session_id: str, username: str, display: int, websocket_port: int) -> None:
        with self._lock:
            if session_id in self._instances:
                return
            processes = []
            try:
                self._start_vnc(display)
                time.sleep(1)
                dosbox_proc = self._start_dosbox(display)
                processes.append(dosbox_proc)
                ws_proc = self._start_websockify(websocket_port, display)
                processes.append(ws_proc)
            except Exception as exc:  # pragma: no cover - defensive cleanup
                for proc in processes:
                    if proc.poll() is None:
                        proc.terminate()
                subprocess.run(
                    [self.vnc_binary, "-kill", f":{display}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                raise InstanceError(f"Failed to resume session: {exc}") from exc
            self._instances[session_id] = Instance(
                session_id=session_id,
                username=username,
                display=display,
                websocket_port=websocket_port,
                processes=tuple(processes),
            )

    def stop_session(self, session_id: str) -> None:
        with self._lock:
            instance = self._instances.pop(session_id, None)
        if not instance:
            return
        for proc in instance.processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        subprocess.run(
            [self.vnc_binary, "-kill", f":{instance.display}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def stop_all(self) -> None:
        with self._lock:
            session_ids = list(self._instances.keys())
        for session_id in session_ids:
            self.stop_session(session_id)

