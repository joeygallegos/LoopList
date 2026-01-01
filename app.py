# app.py
from __future__ import annotations

import json
import os
import random
import string
import threading
from typing import Any, Dict, List

from flask import Flask, request, render_template_string, session
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_TO_SOMETHING_SECURE"
socketio = SocketIO(app, cors_allowed_origins="*")

CONFIG_PATH = "config.json"
STATE_PATH = "state.json"

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


def ensure_state() -> None:
    with _file_lock:
        config: Dict[str, List[str]] = load_json(CONFIG_PATH)
        state: Dict[str, List[bool]] = load_json_or_default(STATE_PATH, {})
        new_state = sync_state_with_config(config, state)
        if new_state != state:
            save_json(STATE_PATH, new_state)


@app.route("/")
def index():
    ensure_state()
    config = load_json(CONFIG_PATH)
    state = load_json(STATE_PATH)
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

            <div class="flex justify-end gap-2 mb-4">
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
                    Reset Options
                </button>
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
                    <h2 class="text-xl font-bold mb-4">Reset All Items</h2>

                    <p class="text-sm mb-2 text-gray-600">
                        Enter the reset code to clear all progress:
                    </p>

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
                            Reset All
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
        </div>

        <script>
            function scrubSquadApp() {
                const socket = io();

                return {
                    groups: {{ config|tojson }},
                    state: {{ state|tojson }},

                    resetCode: "",
                    showResetModal: false,

                    showAddModal: false,
                    addGroup: "",
                    addText: "",
                    addError: "",

                    get percentComplete() {
                        let total=0, done=0;
                        for(const g in this.state){
                            total += this.state[g].length;
                            done += this.state[g].filter(Boolean).length;
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

                        socket.emit("add_item", { group, text });
                    },

                    toggleItem(group, idx) {
                        socket.emit("toggle_item", {group, index: idx});
                    },

                    attemptReset() {
                        socket.emit("reset_all", {code: this.resetCode});
                    },

                    init() {
                        socket.on("state_update", data => { this.state = data; });
                        socket.on("config_update", data => {
                            this.groups = data;
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
        config=config,
        state=state,
        reset_code=session["reset_code"],
    )


# -----------------------------
# SocketIO server events
# -----------------------------
@socketio.on("toggle_item")
def socket_toggle(data):
    group = data["group"]
    idx = int(data["index"])

    with _file_lock:
        config = load_json(CONFIG_PATH)
        state = load_json_or_default(STATE_PATH, {})
        state = sync_state_with_config(config, state)

        if group not in state or idx < 0 or idx >= len(state[group]):
            return

        state[group][idx] = not state[group][idx]
        save_json(STATE_PATH, state)

    emit("state_update", state, broadcast=True)


@socketio.on("reset_all")
def socket_reset(payload):
    submitted = (payload.get("code") or "").strip()
    expected = (session.get("reset_code") or "").strip()

    if submitted != expected:
        emit("reset_failed", {}, to=request.sid)
        return

    with _file_lock:
        config = load_json(CONFIG_PATH)
        new_state = {g: [False] * len(items) for g, items in config.items()}
        save_json(STATE_PATH, new_state)

    emit("state_update", new_state, broadcast=True)


@socketio.on("add_item")
def socket_add_item(payload):
    group = (payload.get("group") or "").strip()
    text = (payload.get("text") or "").strip()

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
        config: Dict[str, List[str]] = load_json(CONFIG_PATH)
        if group not in config:
            emit("add_failed", {"error": f'Group "{group}" does not exist.'}, to=request.sid)
            return

        config[group].append(text)
        save_json(CONFIG_PATH, config)

        state: Dict[str, List[bool]] = load_json_or_default(STATE_PATH, {})
        state = sync_state_with_config(config, state)  # includes the new item
        save_json(STATE_PATH, state)

    emit("add_ok", {}, to=request.sid)
    emit("config_update", config, broadcast=True)
    emit("state_update", state, broadcast=True)


if __name__ == "__main__":
    print("🧽 ScrubSquad (Real-Time Rainbow Edition) running on http://0.0.0.0:4813")
    socketio.run(app, host="0.0.0.0", port=4813)
