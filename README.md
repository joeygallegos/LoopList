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

## Data Files

LoopList uses two JSON files:

- `config.json` defines the actual lists, sections, and item text.
- `state.json` stores progress only. It mirrors the list and section names from `config.json`, but each item is represented only by a status string.

### `config.json`

Use `config.json` for the checklist content users see in the UI. This is where item text belongs.

```json
{
  "default_list": "House Cleaning",
  "lists": {
    "House Cleaning": {
      "List A - Kitchen": [
        "Clean counters",
        "Wipe sink"
      ]
    },
    "Packing Checklist": {
      "Clothes": [
        "Socks",
        "Jackets"
      ]
    }
  }
}
```

### `state.json`

Use `state.json` for progress only. The item positions line up with the items in `config.json`; the strings are statuses, not checklist item text.

```json
{
  "schema_version": 2,
  "lists": {
    "House Cleaning": {
      "List A - Kitchen": [
        "pending",
        "done"
      ]
    },
    "Packing Checklist": {
      "Clothes": [
        "pending",
        "skipped"
      ]
    }
  }
}
```

Valid statuses are:

- `pending`
- `done`
- `skipped`

For example, if `config.json` has two items in `House Cleaning` -> `List A - Kitchen`, then `state.json` should have two statuses in that same list and section. The first status applies to the first item, the second status applies to the second item, and so on.

### Generated API JSON

`GET /api/lists` returns a combined view of both files. That response includes item objects with `index`, `text`, and `status`:

```json
{
  "index": 0,
  "text": "Clean counters",
  "status": "pending"
}
```

Do not use that combined API shape directly as `state.json`. To recreate the app data from API output, put item text into `config.json` and put only the status arrays into `state.json`.

## Notes

- If `state.json` is missing, the app treats every configured item as `pending`.
- Add/remove item actions update both files: `config.json` changes the item text arrays, and `state.json` is resized so statuses stay aligned by index.
- This project currently keeps frontend and backend in `app.py` on purpose to stay simple.

## REST API

Fetch all configured list data and current item statuses:

```http
GET /api/lists
```

The response includes `schema_version`, `default_list`, and `lists`. Each list contains sections, and each section contains items with `index`, `text`, and `status` (`pending`, `done`, or `skipped`).

Add one item to a section by naming the section in the JSON body:

```http
POST /api/lists/House%20Cleaning/items
Content-Type: application/json
```

```json
{
  "section": "List A - Kitchen",
  "text": "Clean under sink"
}
```

Add one or more items to a section named in the URL:

```http
POST /api/lists/House%20Cleaning/sections/List%20A%20-%20Kitchen/items
Content-Type: application/json
```

```json
{
  "items": [
    "Clean under sink",
    "Polish faucet"
  ]
}
```

Set `"create_section": true` to create a missing section while adding items. Both POST endpoints return the full list JSON using the same schema as `GET /api/lists`.
