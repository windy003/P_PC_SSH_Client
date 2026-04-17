"""SSH连接配置的保存与加载。"""

import json
import os
import uuid

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CONFIG_DIR, "connections.json")


def _ensure_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_connections() -> list[dict]:
    """加载所有已保存的连接配置。"""
    _ensure_dir()
    if not os.path.exists(CONFIG_FILE):
        return []
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_connections(connections: list[dict]):
    """保存连接配置列表。"""
    _ensure_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(connections, f, ensure_ascii=False, indent=2)


def add_connection(conn: dict) -> str:
    """添加一个新连接，返回其 id。"""
    connections = load_connections()
    conn_id = str(uuid.uuid4())[:8]
    conn["id"] = conn_id
    connections.append(conn)
    save_connections(connections)
    return conn_id


def update_connection(conn_id: str, data: dict):
    """更新指定 id 的连接。"""
    connections = load_connections()
    for i, c in enumerate(connections):
        if c.get("id") == conn_id:
            data["id"] = conn_id
            connections[i] = data
            break
    save_connections(connections)


def delete_connection(conn_id: str):
    """删除指定 id 的连接。"""
    connections = load_connections()
    connections = [c for c in connections if c.get("id") != conn_id]
    save_connections(connections)


def get_connection(conn_id: str) -> dict | None:
    """获取指定 id 的连接配置。"""
    for c in load_connections():
        if c.get("id") == conn_id:
            return c
    return None


# ── 通用设置 ──────────────────────────────────────────────

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


def load_settings() -> dict:
    _ensure_dir()
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_setting(key: str, value):
    settings = load_settings()
    settings[key] = value
    _ensure_dir()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
