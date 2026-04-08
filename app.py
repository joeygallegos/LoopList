# app.py
from __future__ import annotations

import json
import os
import random
import string
import threading
from typing import Any, Dict, List, Tuple

from flask import Flask, request, render_template_string, session
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_TO_SOMETHING_SECURE"
socketio = SocketIO(app, cors_allowed_origins="*")

CONFIG_PATH = "config.json"
STATE_PATH = "state.json"
DEFAULT_LIST_NAME = "Default"

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


def sync_state_with_config(
    config: Dict[str, List[str]],
    state: Dict[str, List[bool]],
) -> Dict[str, List[bool]]:
    new_state: Dict[str, List[bool]] = {}
    for group, items in config.items():
        current = list(state.get(group, []))
        target_len = len(items)

        if len(current) < target_len:
            current.extend([False] * (target_len - len(current)))
        elif len(current) > target_len:
            current = current[:target_len]

        new_state[group] = current

    return new_state


def normalize_state(
    raw_state: Any,
    lists_config: Dict[str, Dict[str, List[str]]],
    default_list: str,
) -> Dict[str, Dict[str, List[bool]]]:
    state_by_list: Dict[str, Dict[str, List[bool]]] = {}

    if isinstance(raw_state, dict) and any(isinstance(value, dict) for value in raw_state.values()):
        for list_name, raw_sections in raw_state.items():
            if isinstance(raw_sections, dict):
                state_by_list[str(list_name)] = {
                    str(section_name): [bool(value) for value in values]
                    for section_name, values in raw_sections.items()
                    if isinstance(values, list)
                }
    elif isinstance(raw_state, dict):
        state_by_list[default_list] = {
            str(section_name): [bool(value) for value in values]
            for section_name, values in raw_state.items()
            if isinstance(values, list)
        }

    normalized_state: Dict[str, Dict[str, List[bool]]] = {}
    for list_name, sections in lists_config.items():
        normalized_state[list_name] = sync_state_with_config(
            sections,
            state_by_list.get(list_name, {}),
        )

    return normalized_state


def load_normalized_data() -> Tuple[
    Dict[str, Dict[str, List[str]]],
    Dict[str, Dict[str, List[bool]]],
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
        _, state_doc, _, config_doc, raw_config, raw_state = load_normalized_data()
        if config_doc != raw_config:
            save_json(CONFIG_PATH, config_doc)
        if state_doc != raw_state:
            save_json(STATE_PATH, state_doc)


@app.route("/")
def index():
    ensure_state()
    with _file_lock:
        lists_config, state, default_list, _, _, _ = load_normalized_data()
    session["reset_code"] = generate_code()

    html = """
    <!DOCTYPE html>
    <html lang="en" x-data="scrubSquadApp()">
    <head>
        <meta charset="UTF-8">
        <title>ScrubSquad</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="//unpkg.com/alpinejs" defer></script>
        <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>

        <style>
        @keyframes shine {
            0% { background-position: 0% 0%; }
            100% { background-position: 200% 0%; }
        }

        .progress-animated {
            background: linear-gradient(
                90deg,
                rgba(255,0,0,0.8),
                rgba(255,165,0,0.8),
                rgba(255,255,0,0.8),
                rgba(0,255,0,0.8),
                rgba(0,255,255,0.8),
                rgba(0,0,255,0.8),
                rgba(255,0,255,0.8),
                rgba(255,0,0,0.8)
            );
            background-size: 200% 100%;
            animation: shine 6s linear infinite;
            transition: all 0.3s ease;
            border-radius: 9999px;
        }
        </style>
    </head>
    <body class="bg-gray-100 p-6">
        <div class="max-w-4xl mx-auto">
            <h1 class="text-4xl font-extrabold mb-6 text-center text-blue-700">
                🧽 ScrubSquad
            </h1>

            <div class="flex flex-col gap-3 mb-4 md:flex-row md:items-end md:justify-between">
                <div class="w-full md:max-w-sm">
                    <label class="block text-sm font-medium text-gray-700 mb-1">Configured List</label>
                    <select
                        class="border p-2 rounded w-full bg-white"
                        x-model="selectedList"
                    >
                        <template x-for="listName in listNames" :key="listName">
                            <option :value="listName" x-text="listName"></option>
                        </template>
                    </select>
                </div>

                <div class="flex justify-end gap-2">
                    <button
                        class="bg-blue-700 hover:bg-blue-800 text-white px-4 py-2 rounded"
                        @click="openAddModal()"
                    >
                        + Add Item
                    </button>

                    <button
                        class="bg-gray-700 hover:bg-gray-800 text-white px-4 py-2 rounded"
                        @click="showResetModal = true"
                    >
                        Reset List
                    </button>
                </div>
            </div>

            <div class="mb-6">
                <div class="w-full bg-gray-300 rounded h-6 overflow-hidden shadow">
                    <div class="h-full progress-animated"
                        :style="`
                            width: ${percentComplete}%;
                            box-shadow: 0 0 ${percentComplete/5}px hsl(${percentComplete * 1.2}, 80%, 60%);
                        `">
                    </div>
                </div>
                <p class="text-center text-sm text-gray-700 mt-1"
                   x-text="percentComplete + '%' + ' complete'"></p>
            </div>

            <!-- Add Item Modal -->
            <div
                class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center"
                x-show="showAddModal"
                x-transition
            >
                <div class="bg-white rounded shadow p-6 w-96">
                    <h2 class="text-xl font-bold mb-4">Add Item</h2>

                    <label class="block text-sm font-medium text-gray-700 mb-1">Group</label>
                    <select
                        class="border p-2 rounded w-full mb-4"
                        x-model="addGroup"
                    >
                        <template x-for="g in Object.keys(groups)" :key="g">
                            <option :value="g" x-text="g"></option>
                        </template>
                    </select>

                    <label class="block text-sm font-medium text-gray-700 mb-1">Item</label>
                    <input
                        type="text"
                        class="border p-2 rounded w-full mb-4"
                        placeholder="e.g., Clean sink"
                        x-model="addText"
                        @keydown.enter.prevent="submitAdd()"
                    >

                    <p class="text-sm text-red-600 mb-3" x-show="addError" x-text="addError"></p>

                    <div class="flex justify-between">
                        <button
                            class="bg-blue-700 hover:bg-blue-800 text-white px-4 py-2 rounded"
                            @click="submitAdd()"
                        >
                            Add
                        </button>
                        <button
                            class="bg-gray-400 text-white px-4 py-2 rounded"
                            @click="closeAddModal()"
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            </div>

            <!-- Reset Modal -->
            <div
                class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center"
                x-show="showResetModal"
                x-transition
            >
                <div class="bg-white rounded shadow p-6 w-80">
                    <h2 class="text-xl font-bold mb-4">Reset This List</h2>

                    <p class="text-sm mb-2 text-gray-600">
                        Enter the reset code to clear progress for the selected list:
                    </p>

                    <p class="text-sm font-medium mb-3 text-gray-800" x-text="selectedList"></p>

                    <p class="font-mono text-lg mb-3 text-blue-700">
                        <strong>{{ reset_code }}</strong>
                    </p>

                    <input type="text" maxlength="6"
                        placeholder="Enter code"
                        class="border p-2 rounded w-full mb-4"
                        x-model="resetCode">

                    <div class="flex justify-between">
                        <button
                            class="bg-red-600 text-white px-4 py-2 rounded"
                            @click="attemptReset()"
                        >
                            Reset List
                        </button>

                        <button
                            class="bg-gray-400 text-white px-4 py-2 rounded"
                            @click="showResetModal = false"
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            </div>

            <!-- Groups -->
            <template x-for="(items, groupName) in groups" :key="groupName">
                <div class="mb-6 p-4 bg-white rounded shadow">
                    <div class="flex items-center justify-between mb-3">
                        <h2 class="text-xl font-semibold text-blue-600" x-text="groupName"></h2>
                        <button
                            class="text-sm bg-blue-100 hover:bg-blue-200 text-blue-800 px-3 py-1 rounded"
                            @click="openAddModal(groupName)"
                        >
                            + Add to this group
                        </button>
                    </div>

                    <template x-for="(item, idx) in items" :key="idx">
                        <label class="flex items-center mb-2 cursor-pointer">
                            <input type="checkbox"
                                class="mr-2"
                                :checked="state[groupName] && state[groupName][idx]"
                                @change="toggleItem(groupName, idx)">
                            <span x-text="item"></span>
                        </label>
                    </template>
                </div>
            </template>

            <div
                class="bg-white rounded shadow p-6 text-center text-gray-500"
                x-show="!Object.keys(groups).length"
            >
                This list has no sections configured.
            </div>
        </div>

        <script>
            function scrubSquadApp() {
                const socket = io();

                return {
                    lists: {{ lists_config|tojson }},
                    stateByList: {{ state|tojson }},
                    selectedList: {{ default_list|tojson }},

                    resetCode: "",
                    showResetModal: false,

                    showAddModal: false,
                    addGroup: "",
                    addText: "",
                    addError: "",

                    get listNames() {
                        return Object.keys(this.lists || {});
                    },

                    get groups() {
                        return this.lists[this.selectedList] || {};
                    },

                    get state() {
                        return this.stateByList[this.selectedList] || {};
                    },

                    get percentComplete() {
                        let total=0, done=0;
                        for(const g in this.groups){
                            const values = this.state[g] || [];
                            total += values.length;
                            done += values.filter(Boolean).length;
                        }
                        return total===0?0:Math.round((done/total)*100);
                    },

                    openAddModal(groupName = "") {
                        const keys = Object.keys(this.groups || {});
                        this.addGroup = groupName || this.addGroup || (keys.length ? keys[0] : "");
                        this.addText = "";
                        this.addError = "";
                        this.showAddModal = true;
                    },

                    closeAddModal() {
                        this.showAddModal = false;
                        this.addError = "";
                    },

                    submitAdd() {
                        const text = (this.addText || "").trim();
                        const group = (this.addGroup || "").trim();

                        if (!group) {
                            this.addError = "Pick a group.";
                            return;
                        }
                        if (!text) {
                            this.addError = "Item cannot be empty.";
                            return;
                        }
                        if (text.length > 120) {
                            this.addError = "Keep items under 120 characters.";
                            return;
                        }

                        socket.emit("add_item", { list_name: this.selectedList, group, text });
                    },

                    toggleItem(group, idx) {
                        socket.emit("toggle_item", {list_name: this.selectedList, group, index: idx});
                    },

                    attemptReset() {
                        socket.emit("reset_all", {code: this.resetCode, list_name: this.selectedList});
                    },

                    init() {
                        if (!this.listNames.includes(this.selectedList)) {
                            this.selectedList = this.listNames.length ? this.listNames[0] : "";
                        }

                        socket.on("state_update", data => { this.stateByList = data; });
                        socket.on("config_update", data => {
                            this.lists = data.lists || {};
                            const fallback = data.default_list || this.listNames[0] || "";
                            if (!this.listNames.includes(this.selectedList)) this.selectedList = fallback;
                            const keys = Object.keys(this.groups || {});
                            if (!keys.includes(this.addGroup)) this.addGroup = keys.length ? keys[0] : "";
                        });

                        socket.on("reset_failed", () => { alert("Invalid reset code."); });

                        socket.on("add_failed", (payload) => {
                            this.addError = (payload && payload.error) ? payload.error : "Failed to add item.";
                        });

                        socket.on("add_ok", () => {
                            this.closeAddModal();
                        });
                    }
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(
        html,
        lists_config=lists_config,
        state=state,
        default_list=default_list,
        reset_code=session["reset_code"],
    )


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

        state[list_name][group][idx] = not state[list_name][group][idx]
        save_json(STATE_PATH, state)

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
            group_name: [False] * len(items)
            for group_name, items in lists_config[list_name].items()
        }
        save_json(STATE_PATH, state)

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
        save_json(STATE_PATH, state)

    emit("add_ok", {}, to=request.sid)
    emit("config_update", config_doc, broadcast=True)
    emit("state_update", state, broadcast=True)


if __name__ == "__main__":
    print("🧽 ScrubSquad (Real-Time Rainbow Edition) running on http://0.0.0.0:4813")
    socketio.run(app, host="0.0.0.0", port=4813)
