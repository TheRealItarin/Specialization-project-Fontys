import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from instance_manager import InstanceError, InstanceManager


DEFAULT_USERS_FILE = "/config/users.json"
DEFAULT_DB_PATH = "/var/lib/session.db"
DEFAULT_IDLE_TIMEOUT = 900  # 15 minutes
DEFAULT_ABSOLUTE_TIMEOUT = 28800  # 8 hours
DEFAULT_BASE_DISPLAY = 11
DEFAULT_MAX_INSTANCES = 5
DEFAULT_BASE_WEBSOCKET_PORT = 7700
DEFAULT_VNC_GEOMETRY = "1024x768"
DEFAULT_VNC_DEPTH = 24
DEFAULT_DOSBOX_CONF = "/root/.dosbox/dosbox-0.74-3.conf"


def load_users(file_path: str) -> Dict[str, str]:
    path = Path(file_path)
    if not path.exists():
        raise RuntimeError(f"User config not found at {file_path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not data:
        raise RuntimeError("User configuration must be a non-empty object")
    return {str(user): str(password) for user, password in data.items()}


class SessionStore:
    def __init__(
        self,
        db_path: str,
        idle_timeout: int,
        absolute_timeout: int,
        instance_manager: InstanceManager,
    ) -> None:
        self.db_path = db_path
        self.idle_timeout = idle_timeout
        self.absolute_timeout = absolute_timeout
        self.instance_manager = instance_manager
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    display INTEGER,
                    websocket_port INTEGER,
                    created_at INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "display" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN display INTEGER")
            if "websocket_port" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN websocket_port INTEGER")
            conn.commit()

    def _cleanup_expired(self, conn: sqlite3.Connection, now_ts: int) -> None:
        stale_ids = [
            row[0]
            for row in conn.execute(
                """
                SELECT session_id FROM sessions
                WHERE (? - last_seen) > ?
                   OR (? - created_at) > ?
                """,
                (now_ts, self.idle_timeout, now_ts, self.absolute_timeout),
            ).fetchall()
        ]
        conn.execute(
            """
            DELETE FROM sessions
            WHERE (? - last_seen) > ?
               OR (? - created_at) > ?
            """,
            (now_ts, self.idle_timeout, now_ts, self.absolute_timeout),
        )
        conn.commit()
        for session_id in stale_ids:
            self.instance_manager.stop_session(session_id)

    def create_session(self, username: str) -> Dict[str, int]:
        session_id = str(uuid.uuid4())
        now_ts = int(time.time())
        with self._lock:
            with self._connect() as conn:
                old_sessions = [
                    row[0]
                    for row in conn.execute(
                        "SELECT session_id FROM sessions WHERE username = ?",
                        (username,),
                    ).fetchall()
                ]
                conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
                conn.commit()
            for existing_session in old_sessions:
                self.instance_manager.stop_session(existing_session)
            display, ws_port = self.instance_manager.start_session(session_id, username)
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, username, display, websocket_port, created_at, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, username, display, ws_port, now_ts, now_ts),
                )
                conn.commit()
        return {
            "session_id": session_id,
            "created_at": now_ts,
            "display": display,
            "websocket_port": ws_port,
        }

    def validate(self, session_id: str) -> Optional[Dict[str, int]]:
        if not session_id:
            return None
        now_ts = int(time.time())
        with self._lock, self._connect() as conn:
            self._cleanup_expired(conn, now_ts)
            row = conn.execute(
                """
                SELECT username, created_at, last_seen, display, websocket_port
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if not row:
                return None
            last_seen = row[2]
            # Update last_seen atomically
            conn.execute(
                "UPDATE sessions SET last_seen = ? WHERE session_id = ?",
                (now_ts, session_id),
            )
            conn.commit()
        display, ws_port = row[3], row[4]
        if display is None or ws_port is None:
            return None
        self.instance_manager.ensure_session(session_id, row[0], display, ws_port)
        return {
            "username": row[0],
            "created_at": row[1],
            "last_seen": last_seen,
            "display": display,
            "websocket_port": ws_port,
        }

    def delete(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
        self.instance_manager.stop_session(session_id)


class LoginPayload(BaseModel):
    username: str
    password: str


class SessionResponse(BaseModel):
    username: str
    issued_at: int
    last_seen: int
    websocket_port: int
    idle_timeout_seconds: int
    absolute_timeout_seconds: int


USERS_FILE = os.getenv("AUTH_USERS_FILE", DEFAULT_USERS_FILE)
IDLE_TIMEOUT = int(os.getenv("SESSION_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT))
ABSOLUTE_TIMEOUT = int(os.getenv("SESSION_ABSOLUTE_TIMEOUT", DEFAULT_ABSOLUTE_TIMEOUT))
DB_PATH = os.getenv("SESSION_DB_PATH", DEFAULT_DB_PATH)
BASE_DISPLAY = int(os.getenv("SESSION_BASE_DISPLAY", DEFAULT_BASE_DISPLAY))
MAX_INSTANCES = int(os.getenv("SESSION_MAX_INSTANCES", DEFAULT_MAX_INSTANCES))
BASE_WS_PORT = int(os.getenv("SESSION_BASE_WEBSOCKET_PORT", DEFAULT_BASE_WEBSOCKET_PORT))
VNC_GEOMETRY = os.getenv("SESSION_VNC_GEOMETRY", DEFAULT_VNC_GEOMETRY)
VNC_DEPTH = int(os.getenv("SESSION_VNC_DEPTH", DEFAULT_VNC_DEPTH))
DOSBOX_CONF = os.getenv("SESSION_DOSBOX_CONF", DEFAULT_DOSBOX_CONF)

USERS = load_users(USERS_FILE)
INSTANCE_MANAGER = InstanceManager(
    base_display=BASE_DISPLAY,
    max_instances=MAX_INSTANCES,
    base_websocket_port=BASE_WS_PORT,
    geometry=VNC_GEOMETRY,
    depth=VNC_DEPTH,
    dosbox_conf=DOSBOX_CONF,
)
SESSION_STORE = SessionStore(DB_PATH, IDLE_TIMEOUT, ABSOLUTE_TIMEOUT, INSTANCE_MANAGER)

app = FastAPI(title="secureDos session service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


def get_session_id_from_request(request: Request) -> str:
    cookie = request.cookies.get("SESSION_ID")
    header = request.headers.get("X-Session-Id")
    return header or cookie or ""


def require_session(request: Request) -> Dict[str, int]:
    session_id = get_session_id_from_request(request)
    data = SESSION_STORE.validate(session_id)
    if not data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    data["session_id"] = session_id
    return data


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


@app.post("/api/login", response_model=SessionResponse)
def login(payload: LoginPayload, response: Response):
    expected_password = USERS.get(payload.username)
    if expected_password is None or expected_password != payload.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    try:
        session_data = SESSION_STORE.create_session(payload.username)
    except InstanceError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    now_ts = session_data["created_at"]
    response.set_cookie(
        "SESSION_ID",
        session_data["session_id"],
        max_age=ABSOLUTE_TIMEOUT,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return SessionResponse(
        username=payload.username,
        issued_at=now_ts,
        last_seen=now_ts,
        websocket_port=session_data["websocket_port"],
        idle_timeout_seconds=IDLE_TIMEOUT,
        absolute_timeout_seconds=ABSOLUTE_TIMEOUT,
    )


@app.post("/api/logout")
def logout(session=Depends(require_session)):
    SESSION_STORE.delete(session["session_id"])
    response = JSONResponse({"message": "logged out"})
    response.delete_cookie("SESSION_ID")
    return response


@app.get("/api/session", response_model=SessionResponse)
def get_session(session=Depends(require_session)):
    return SessionResponse(
        username=session["username"],
        issued_at=session["created_at"],
        last_seen=session["last_seen"],
        websocket_port=session["websocket_port"],
        idle_timeout_seconds=IDLE_TIMEOUT,
        absolute_timeout_seconds=ABSOLUTE_TIMEOUT,
    )


@app.get("/internal/validate")
def internal_validate(request: Request):
    session_id = request.headers.get("x-session-id")
    data = SESSION_STORE.validate(session_id)
    if not data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    headers = {
        "X-Session-User": data["username"],
        "X-Session-Port": str(data["websocket_port"]),
    }
    return PlainTextResponse("ok", headers=headers)

