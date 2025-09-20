# 🛠️ Plugin Wrappers Generator

This script (`tools/generate_plugin_wrappers.py`) automatically creates **Plugin wrappers** for each service found under `app/services/*/service.py`.
Benefit: every service you add will automatically be exposed as a **Plugin** in the REST API (`/plugins/{name}/{task}`).

---

## 📂 Folder structure after generation
For example, if you have a service `pdf_reader` inside:
```
app/services/pdf_reader/service.py
```

The script will generate:
```
app/plugins/pdf_reader/
├─ __init__.py
├─ plugin.py        # Lazy wrapper delegating to the service
└─ manifest.json    # Metadata (name, tasks, ...)
```

---

## 🚀 Usage

### 1. Activate virtual environment
```powershell
& Q:/repo-fastapi-uploads/.venv/Scripts/Activate.ps1
```

### 2. Commands

- **Generate wrappers for all services (without deleting existing ones):**
```powershell
python tools/generate_plugin_wrappers.py
```

- **Regenerate with force (delete existing app/plugins/<name>/ then recreate):**
```powershell
python tools/generate_plugin_wrappers.py --force
```

- **Generate only for a specific service (e.g., pdf_reader):**
```powershell
python tools/generate_plugin_wrappers.py --only pdf_reader
```

- **Regenerate only for a specific service:**
```powershell
python tools/generate_plugin_wrappers.py --only pdf_reader --force
```

- **Dry run (show planned actions without writing files):**
```powershell
python tools/generate_plugin_wrappers.py --dry-run
```

---

## ✅ Verification after generation

Check the list of plugins:
```powershell
python -c "from app.main import app; from starlette.testclient import TestClient; c=TestClient(app); import json; print(json.dumps(c.get('/plugins').json(), indent=2))"
```

Expected output should include services like:
```json
{
  "plugins": [
    {"name": "dummy", "tasks": ["ping"]},
    {"name": "pdf_reader", "tasks": ["extract_text"]},
    {"name": "whisper", "tasks": ["transcribe"]}
  ]
}
```

---

## 🧹 Notes
- The script always writes files with LF newlines to avoid `mixed-line-ending` issues.
- The wrapper is generated as a **Lazy Adapter** to prevent circular import problems.
- Any new service added in `app/services/*/service.py` → just run the script to generate its wrapper automatically.
