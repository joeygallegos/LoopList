# app.py
from __future__ import annotations

import json
import os
import random
import string
import threading
from typing import Any, Dict, List, Tuple

from flask import Flask, jsonify, request, render_template, session
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_TO_SOMETHING_SECURE"
socketio = SocketIO(app, cors_allowed_origins="*")

CONFIG_PATH = "config.json"
STATE_PATH = "state.json"
DEFAULT_LIST_NAME = "Default"
STATE_SCHEMA_VERSION = 2
STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
VALID_STATUSES = {STATUS_PENDING, STATUS_DONE, STATUS_SKIPPED}

_file_lock = threading.Lock()


def generate_code() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=6))


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_json_or_default(path: str, default: Any) -> Any:
    try:
        return load_json(path)
    except FileNotFoundError:
        return default


def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize_sections(raw_sections: Any) -> Dict[str, List[str]]:
    if not isinstance(raw_sections, dict):
        return {}

    sections: Dict[str, List[str]] = {}
    for section_name, raw_items in raw_sections.items():
        if not isinstance(raw_items, list):
            continue
        sections[str(section_name)] = [str(item) for item in raw_items]
    return sections


def normalize_config(raw_config: Any) -> Tuple[Dict[str, Dict[str, List[str]]], str]:
    lists: Dict[str, Dict[str, List[str]]] = {}
    default_list = DEFAULT_LIST_NAME

    if isinstance(raw_config, dict) and isinstance(raw_config.get("lists"), dict):
        for list_name, raw_sections in raw_config["lists"].items():
            if isinstance(raw_sections, dict):
                lists[str(list_name)] = normalize_sections(raw_sections)
        requested_default = raw_config.get("default_list")
        if isinstance(requested_default, str) and requested_default.strip():
            default_list = requested_default.strip()
    else:
        sections = normalize_sections(raw_config)
        lists[DEFAULT_LIST_NAME] = sections

    if not lists:
        lists[DEFAULT_LIST_NAME] = {}

    if default_list not in lists:
        default_list = next(iter(lists))

    return lists, default_list


def build_config_document(
    lists_config: Dict[str, Dict[str, List[str]]],
    default_list: str,
) -> Dict[str, Any]:
    if default_list not in lists_config:
        default_list = next(iter(lists_config), DEFAULT_LIST_NAME)
    return {
        "default_list": default_list,
        "lists": lists_config,
    }


def normalize_status(value: Any) -> str:
    if isinstance(value, bool):
        return STATUS_DONE if value else STATUS_PENDING
    if isinstance(value, str) and value in VALID_STATUSES:
        return value
    return STATUS_PENDING


def extract_state_payload(raw_state: Any) -> Any:
    if (
        isinstance(raw_state, dict)
        and raw_state.get("schema_version") == STATE_SCHEMA_VERSION
        and isinstance(raw_state.get("lists"), dict)
    ):
        return raw_state["lists"]
    return raw_state


def build_state_document(state_by_list: Dict[str, Dict[str, List[str]]]) -> Dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "lists": state_by_list,
    }


def state_requires_migration(raw_state: Any, state_doc: Dict[str, Any]) -> bool:
    return raw_state != state_doc


def sync_state_with_config(
    config: Dict[str, List[str]],
    state: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    new_state: Dict[str, List[str]] = {}
    for group, items in config.items():
        current = [normalize_status(value) for value in list(state.get(group, []))]
        target_len = len(items)

        if len(current) < target_len:
            current.extend([STATUS_PENDING] * (target_len - len(current)))
        elif len(current) > target_len:
            current = current[:target_len]

        new_state[group] = current

    return new_state


def normalize_state(
    raw_state: Any,
    lists_config: Dict[str, Dict[str, List[str]]],
    default_list: str,
) -> Dict[str, Dict[str, List[str]]]:
    raw_state = extract_state_payload(raw_state)
    state_by_list: Dict[str, Dict[str, List[str]]] = {}

    if isinstance(raw_state, dict) and any(isinstance(value, dict) for value in raw_state.values()):
        for list_name, raw_sections in raw_state.items():
            if isinstance(raw_sections, dict):
                state_by_list[str(list_name)] = {
                    str(section_name): [normalize_status(value) for value in values]
                    for section_name, values in raw_sections.items()
                    if isinstance(values, list)
                }
    elif isinstance(raw_state, dict):
        state_by_list[default_list] = {
            str(section_name): [normalize_status(value) for value in values]
            for section_name, values in raw_state.items()
            if isinstance(values, list)
        }

    normalized_state: Dict[str, Dict[str, List[str]]] = {}
    for list_name, sections in lists_config.items():
        normalized_state[list_name] = sync_state_with_config(
            sections,
            state_by_list.get(list_name, {}),
        )

    return normalized_state


def load_normalized_data() -> Tuple[
    Dict[str, Dict[str, List[str]]],
    Dict[str, Dict[str, List[str]]],
    str,
    Dict[str, Any],
    Any,
    Any,
]:
    raw_config = load_json(CONFIG_PATH)
    lists_config, default_list = normalize_config(raw_config)
    config_doc = build_config_document(lists_config, default_list)

    raw_state = load_json_or_default(STATE_PATH, {})
    state_doc = normalize_state(raw_state, lists_config, default_list)

    return lists_config, state_doc, default_list, config_doc, raw_config, raw_state


def ensure_state() -> None:
    with _file_lock:
        _, state, _, config_doc, raw_config, raw_state = load_normalized_data()
        state_doc = build_state_document(state)
        if config_doc != raw_config:
            save_json(CONFIG_PATH, config_doc)
        if state_requires_migration(raw_state, state_doc):
            save_json(STATE_PATH, state_doc)



def build_lists_api_payload(
    lists_config: Dict[str, Dict[str, List[str]]],
    state: Dict[str, Dict[str, List[str]]],
    default_list: str,
) -> Dict[str, Any]:
    lists_payload: Dict[str, Any] = {}
    for list_name, sections in lists_config.items():
        section_payload: Dict[str, Any] = {}
        for section_name, items in sections.items():
            statuses = state.get(list_name, {}).get(section_name, [])
            section_payload[section_name] = [
                {
                    "index": idx,
                    "text": item,
                    "status": normalize_status(statuses[idx] if idx < len(statuses) else STATUS_PENDING),
                }
                for idx, item in enumerate(items)
            ]
        lists_payload[list_name] = {"sections": section_payload}

    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "default_list": default_list,
        "lists": lists_payload,
    }

@app.route("/")
def index():
    ensure_state()
    with _file_lock:
        _, state, _, config_doc, _, _ = load_normalized_data()
    session["reset_code"] = generate_code()
    return render_template(
        "index.html",
        config_doc=config_doc,
        state=state,
        reset_code=session["reset_code"],
    )



@app.route("/api/lists", methods=["GET"])
def api_lists():
    with _file_lock:
        lists_config, state, default_list, _, _, _ = load_normalized_data()
        payload = build_lists_api_payload(lists_config, state, default_list)
    return jsonify(payload)

# -----------------------------
# SocketIO server events
# -----------------------------
@socketio.on("toggle_item")
def socket_toggle(data):
    list_name = (data.get("list_name") or "").strip()
    group = data["group"]
    idx = int(data["index"])

    with _file_lock:
        lists_config, state, default_list, _, _, _ = load_normalized_data()
        if list_name not in lists_config:
            list_name = default_list

        if group not in state.get(list_name, {}) or idx < 0 or idx >= len(state[list_name][group]):
            return

        current_status = normalize_status(state[list_name][group][idx])
        state[list_name][group][idx] = STATUS_PENDING if current_status == STATUS_DONE else STATUS_DONE
        save_json(STATE_PATH, build_state_document(state))

    emit("state_update", state, broadcast=True)


@socketio.on("set_item_status")
def socket_set_item_status(data):
    list_name = (data.get("list_name") or "").strip()
    group = (data.get("group") or "").strip()
    idx = int(data["index"])
    requested_status = normalize_status(data.get("status"))

    with _file_lock:
        lists_config, state, default_list, _, _, _ = load_normalized_data()
        if list_name not in lists_config:
            list_name = default_list

        if group not in state.get(list_name, {}) or idx < 0 or idx >= len(state[list_name][group]):
            return

        current_status = normalize_status(state[list_name][group][idx])
        state[list_name][group][idx] = STATUS_PENDING if current_status == requested_status else requested_status
        save_json(STATE_PATH, build_state_document(state))

    emit("state_update", state, broadcast=True)


@socketio.on("reset_all")
def socket_reset(payload):
    submitted = (payload.get("code") or "").strip()
    expected = (session.get("reset_code") or "").strip()
    list_name = (payload.get("list_name") or "").strip()

    if submitted != expected:
        emit("reset_failed", {}, to=request.sid)
        return

    with _file_lock:
        lists_config, state, default_list, _, _, _ = load_normalized_data()
        if list_name not in lists_config:
            list_name = default_list

        state[list_name] = {
            group_name: [STATUS_PENDING] * len(items)
            for group_name, items in lists_config[list_name].items()
        }
        save_json(STATE_PATH, build_state_document(state))

    emit("state_update", state, broadcast=True)


@socketio.on("add_item")
def socket_add_item(payload):
    list_name = (payload.get("list_name") or "").strip()
    group = (payload.get("group") or "").strip()
    text = (payload.get("text") or "").strip()

    if not list_name:
        emit("add_failed", {"error": "Missing list."}, to=request.sid)
        return
    if not group:
        emit("add_failed", {"error": "Missing group."}, to=request.sid)
        return
    if not text:
        emit("add_failed", {"error": "Item cannot be empty."}, to=request.sid)
        return
    if len(text) > 120:
        emit("add_failed", {"error": "Keep items under 120 characters."}, to=request.sid)
        return

    with _file_lock:
        lists_config, state, default_list, _, _, _ = load_normalized_data()
        if list_name not in lists_config:
            emit("add_failed", {"error": f'List "{list_name}" does not exist.'}, to=request.sid)
            return

        if group not in lists_config[list_name]:
            emit("add_failed", {"error": f'Section "{group}" does not exist.'}, to=request.sid)
            return

        lists_config[list_name][group].append(text)
        config_doc = build_config_document(lists_config, default_list)
        save_json(CONFIG_PATH, config_doc)

        state = normalize_state(state, lists_config, default_list)
        save_json(STATE_PATH, build_state_document(state))

    emit("add_ok", {}, to=request.sid)
    emit("config_update", config_doc, broadcast=True)
    emit("state_update", state, broadcast=True)


if __name__ == "__main__":
    print("LoopList running on http://0.0.0.0:4813")
    socketio.run(app, host="0.0.0.0", port=4813)
