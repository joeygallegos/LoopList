# LoopList

LoopList is a lightweight shared checklist app for repeatable workflows.
It lets you define multiple named lists in `config.json`, split each list into sections, track completion in real time, add items from the UI, and reset progress when you need a fresh pass.

## Requirements

- Python 3.10+
- `flask`
- `flask-socketio`

## First-Time Setup

Create and activate a virtual environment if you want to keep dependencies isolated:

```bash
python -m venv .venv
```

Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

Then install dependencies:

```bash
pip install -r requirements.txt
```

## Run

Start the app with:

```bash
python app.py
```

Then open `http://localhost:4813`.

## Configuration

Lists are defined in `config.json`:

```json
{
  "default_list": "house",
  "lists": {
    "house": {
      "Kitchen": [
        "Clean counters",
        "Wipe sink"
      ]
    },
    "packing": {
      "Clothes": [
        "Socks",
        "Jackets"
      ]
    }
  }
}
```

## Notes

- Progress is stored in `state.json`.
- If `state.json` is missing, the app will recreate it from `config.json`.
- This project currently keeps frontend and backend in `app.py` on purpose to stay simple.

## REST API

Fetch all configured list data and current item statuses:

```http
GET /api/lists
```

The response includes `schema_version`, `default_list`, and `lists`. Each list contains sections, and each section contains items with `index`, `text`, and `status` (`pending`, `done`, or `skipped`).
