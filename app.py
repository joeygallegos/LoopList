from flask import Flask, request, jsonify, render_template_string, session
from flask_socketio import SocketIO, emit
import json, os, random, string

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_TO_SOMETHING_SECURE"
socketio = SocketIO(app, cors_allowed_origins="*")

CONFIG_PATH = "config.json"
STATE_PATH = "state.json"

def generate_code():
    return ''.join(random.choices(string.ascii_uppercase, k=6))

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def ensure_state():
    config = load_json(CONFIG_PATH)
    if not os.path.exists(STATE_PATH):
        state = {group: [False] * len(items) for group, items in config.items()}
        save_json(STATE_PATH, state)

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
        /* Animated rainbow glowing progress bar */
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

            <!-- Reset Options Button -->
            <div class="flex justify-end mb-4">
                <button
                    class="bg-gray-700 hover:bg-gray-800 text-white px-4 py-2 rounded"
                    @click="showResetModal = true"
                >
                    Reset Options
                </button>
            </div>

            <!-- Glowing Rainbow Progress Bar -->
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
                    <h2 class="text-xl font-semibold mb-3 text-blue-600" x-text="groupName"></h2>
                    <template x-for="(item, idx) in items" :key="idx">
                        <label class="flex items-center mb-2 cursor-pointer">
                            <input type="checkbox"
                                class="mr-2"
                                :checked="state[groupName][idx]"
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

                    get percentComplete() {
                        let total=0, done=0;
                        for(const g in this.state){
                            total += this.state[g].length;
                            done += this.state[g].filter(Boolean).length;
                        }
                        return total===0?0:Math.round((done/total)*100);
                    },

                    toggleItem(group, idx) {
                        socket.emit("toggle_item", {group, index: idx});
                    },

                    attemptReset() {
                        socket.emit("reset_all", {code: this.resetCode});
                    },

                    init() {
                        socket.on("state_update", data => { this.state = data; });
                        socket.on("reset_failed", () => { alert("Invalid reset code."); });
                    }
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, config=config, state=state, reset_code=session["reset_code"])

# -----------------------------
# SocketIO server events
# -----------------------------
@socketio.on("toggle_item")
def socket_toggle(data):
    group = data["group"]
    idx = data["index"]
    state = load_json(STATE_PATH)
    state[group][idx] = not state[group][idx]
    save_json(STATE_PATH, state)
    emit("state_update", state, broadcast=True)

@socketio.on("reset_all")
def socket_reset(payload):
    submitted = payload.get("code", "")
    expected = session.get("reset_code", "")
    if submitted != expected:
        emit("reset_failed", {}, to=request.sid)
        return
    config = load_json(CONFIG_PATH)
    new_state = {g: [False]*len(items) for g, items in config.items()}
    save_json(STATE_PATH, new_state)
    emit("state_update", new_state, broadcast=True)

if __name__ == "__main__":
    print("🧽 ScrubSquad (Real-Time Rainbow Edition) running on http://0.0.0.0:5000")
    socketio.run(app, host="0.0.0.0", port=4813)
