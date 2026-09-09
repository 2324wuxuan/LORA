"""SQLite 持久化接口：设备快照、告警及维修记录。

启动时调用 init_database()（或 init_db()）。查询返回普通字典，时间以
ISO 格式文本保存；设备查询返回的布尔字段恢复为 bool。数据库不参与仿真决策。
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from config import DATABASE_PATH, DEVICES, SYSTEM, ZONES


def get_connection() -> sqlite3.Connection:
    """创建目录及数据库文件；直接调用者负责关闭连接。"""
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def _connection():
    connection = get_connection()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_database() -> None:
    """幂等建表，并在空库中写入 config.py 定义的设备基础记录。"""
    with _connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY NOT NULL,
                name TEXT, zone TEXT, area TEXT, x REAL, y REAL,
                distance REAL, sf INTEGER, rated_power REAL,
                lamp_state INTEGER, mode TEXT, lux REAL, occupancy INTEGER,
                online INTEGER, brightness REAL, power REAL,
                rssi REAL, snr REAL, packet_loss REAL,
                fault INTEGER, fault_type TEXT, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alarms (
                alarm_id TEXT PRIMARY KEY NOT NULL,
                device_id TEXT NOT NULL, fault_type TEXT NOT NULL,
                level TEXT NOT NULL, message TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                fault_code TEXT, recovered_at TEXT
            );
            CREATE TABLE IF NOT EXISTS maintenance (
                record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL, problem TEXT NOT NULL,
                solution TEXT NOT NULL, operator TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alarms_status ON alarms(status);
            CREATE INDEX IF NOT EXISTS idx_maintenance_device ON maintenance(device_id);
        """)
        _seed_configured_devices(conn)


def _seed_configured_devices(conn: sqlite3.Connection) -> None:
    """首次初始化时写入设备；已有设备状态不会被启动过程覆盖。"""
    now = _time()
    rows = []
    for device_id, config in DEVICES.items():
        brightness = float(config.get("initial_brightness", 0))
        rated_power = float(config["rated_power_w"])
        zone_id = config["zone_id"]
        zone_name = ZONES[zone_id]["name"]
        rows.append((
            device_id,
            config.get("device_name", device_id),
            zone_name,
            zone_name,
            float(config["distance_to_gateway_m"]),
            int(config["lora_sf"]),
            rated_power,
            int(brightness > 0),
            config.get("initial_mode", "AUTO"),
            0.0,
            0,
            int(config.get("initial_status", "ONLINE") == "ONLINE"),
            brightness,
            rated_power * brightness / 100 if brightness > 0 else 0.0,
            0,
            now,
        ))
    conn.executemany("""
        INSERT OR IGNORE INTO devices (
            device_id, name, zone, area, distance, sf, rated_power,
            lamp_state, mode, lux, occupancy, online, brightness, power,
            fault, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)


init_db = init_database


def _time(value=None) -> str:
    if value is None:
        value = datetime.now()
    return value.isoformat(sep=" ") if isinstance(value, datetime) else str(value)


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串")
    return value


_DEVICE_FIELDS = (
    "device_id", "name", "zone", "area", "x", "y", "distance", "sf",
    "rated_power", "lamp_state", "mode", "lux", "occupancy", "online",
    "brightness", "power", "rssi", "snr", "packet_loss", "fault", "fault_type",
)
_BOOL_FIELDS = ("lamp_state", "occupancy", "online", "fault")


def save_device(device) -> None:
    """保存设备对象或字典；重复编号更新已提供字段，保留未提供字段。

    支持 VirtualLightingNode.to_dict()；缺失的通信指标保持 NULL。
    zone 与 area 任一缺失时使用另一个字段补齐。
    """
    if isinstance(device, Mapping):
        data = dict(device)
    else:
        data = {key: getattr(device, key) for key in _DEVICE_FIELDS
                if hasattr(device, key)}
    _required(data.get("device_id"), "device_id")
    if "zone" in data:
        data.setdefault("area", data["zone"])
    elif "area" in data:
        data["zone"] = data["area"]
    values = {key: data[key] for key in _DEVICE_FIELDS if key in data}
    values["updated_at"] = _time(data.get("updated_at"))
    columns = list(values)
    # 列名仅来自本模块白名单，所有外部值使用参数绑定。
    updates = ", ".join(f"{key}=excluded.{key}" for key in columns if key != "device_id")
    with _connection() as conn:
        conn.execute(
            f"INSERT INTO devices ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT(device_id) DO UPDATE SET {updates}",
            tuple(values.values()),
        )


def _device_dict(row) -> dict:
    result = dict(row)
    for key in _BOOL_FIELDS:
        if result[key] is not None:
            result[key] = bool(result[key])
    return result


def get_device(device_id: str) -> dict | None:
    with _connection() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
    return _device_dict(row) if row is not None else None


def get_all_devices() -> list[dict]:
    with _connection() as conn:
        return [_device_dict(row) for row in conn.execute("SELECT * FROM devices ORDER BY device_id")]


def delete_device(device_id: str) -> bool:
    """删除设备快照，保留历史告警和维修记录。"""
    with _connection() as conn:
        return conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,)).rowcount > 0


def _alarm_status(status: str) -> str:
    if status not in {"OPEN", "ACKNOWLEDGED", "CLOSED"}:
        raise ValueError("告警状态必须为 OPEN / ACKNOWLEDGED / CLOSED")
    return status


def add_alarm(device_id: str, fault_type: str, level: str, message: str,
              *, status: str = "OPEN", created_at=None) -> str:
    """新增告警并返回 UUID，与 fault.py 的告警编号约定一致。"""
    alarm_id = str(uuid4())
    save_alarm(dict(alarm_id=alarm_id, device_id=device_id, fault_type=fault_type,
                    level=level, message=message, status=status, created_at=created_at))
    return alarm_id


def save_alarm(alarm: Mapping) -> None:
    """保存 fault.py 告警快照；同一 UUID 更新状态，避免累计快照重复插入。"""
    alarm_id = _required(alarm.get("alarm_id"), "alarm_id")
    device_id = _required(alarm.get("device_id"), "device_id")
    kind = _required(alarm.get("fault_type", alarm.get("alarm_type")), "fault_type")
    level = alarm.get("level", alarm.get("severity"))
    if level not in SYSTEM["supported_alarm_levels"]:
        raise ValueError("告警级别必须为 INFO / WARNING / CRITICAL")
    message = _required(alarm.get("message"), "message")
    status = _alarm_status(alarm.get("status", "OPEN"))
    created = _time(alarm.get("created_at", alarm.get("timestamp")))
    recovered = alarm.get("recovered_at")
    with _connection() as conn:
        conn.execute("""
            INSERT INTO alarms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alarm_id) DO UPDATE SET
                fault_type=excluded.fault_type, level=excluded.level,
                message=excluded.message, status=excluded.status,
                fault_code=excluded.fault_code, recovered_at=excluded.recovered_at
        """, (alarm_id, device_id, kind, level, message, status, created,
              alarm.get("fault_code"), _time(recovered) if recovered is not None else None))


def get_alarms(status: str | None = None, *, device_id: str | None = None) -> list[dict]:
    """最新告警优先；同时提供 fault.py 使用的字段别名。"""
    clauses, params = [], []
    if status is not None:
        clauses.append("status=?")
        params.append(_alarm_status(status))
    if device_id is not None:
        clauses.append("device_id=?")
        params.append(device_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _connection() as conn:
        rows = conn.execute("SELECT *, fault_type AS alarm_type, level AS severity, "
                            "created_at AS timestamp FROM alarms" + where +
                            " ORDER BY created_at DESC, rowid DESC", params)
        return [dict(row) for row in rows]


def update_alarm_status(alarm_id: str, status: str) -> bool:
    """更新处理状态；不存在返回 False，不推断设备已恢复。"""
    with _connection() as conn:
        return conn.execute("UPDATE alarms SET status=? WHERE alarm_id=?",
                            (_alarm_status(status), alarm_id)).rowcount > 0


def delete_alarm(alarm_id: str) -> bool:
    with _connection() as conn:
        return conn.execute("DELETE FROM alarms WHERE alarm_id=?", (alarm_id,)).rowcount > 0


def add_maintenance_record(device_id: str, problem: str, solution: str,
                           operator: str, status: str = "COMPLETED", *, created_at=None) -> int:
    """新增维修记录并返回自增编号；status 为非空业务状态文本。"""
    values = [_required(value, name) for name, value in (
        ("device_id", device_id), ("problem", problem), ("solution", solution),
        ("operator", operator), ("status", status))]
    with _connection() as conn:
        cursor = conn.execute("INSERT INTO maintenance "
                              "(device_id, problem, solution, operator, status, created_at) "
                              "VALUES (?, ?, ?, ?, ?, ?)", (*values, _time(created_at)))
        return cursor.lastrowid


def get_maintenance_records(device_id: str | None = None) -> list[dict]:
    where = " WHERE device_id=?" if device_id is not None else ""
    with _connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM maintenance" + where + " ORDER BY created_at DESC, record_id DESC",
            (device_id,) if device_id is not None else ())]


def update_maintenance_record(record_id: int, *, solution: str, status: str) -> bool:
    with _connection() as conn:
        return conn.execute("UPDATE maintenance SET solution=?, status=? WHERE record_id=?",
                            (_required(solution, "solution"), _required(status, "status"),
                             record_id)).rowcount > 0


def delete_maintenance_record(record_id: int) -> bool:
    with _connection() as conn:
        return conn.execute("DELETE FROM maintenance WHERE record_id=?", (record_id,)).rowcount > 0


if __name__ == "__main__":
    init_database()
    print(f"数据库已初始化：{DATABASE_PATH}")
