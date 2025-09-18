# whisper

**Type:** plugin
**Provider:** _unknown_
**Tasks:** transcribe

Whisper ASR plugin.

Tasks:
  - transcribe:  {rel_path|url|base64}[, language, task, return_segments, translate]
                 -> {'text', 'language', 'segments?[]', 'duration?'}

## Models
- {"type": "hf", "id": "openai/whisper-small"}

## Usage

### API Overview
- `GET /plugins` — list all available plugins.
- `GET /plugins/{name}` — get metadata for this plugin.
- `POST /plugins/{name}/{task}` — run a task of this plugin.

> Replace `{name}` with this plugin's folder name and `{task}` with one of the tasks listed above.

### cURL Example
```bash
curl -X POST "http://localhost:8000/plugins/whisper/transcribe"      -H "Content-Type: application/json"      -d '{}'
```

### Python Example
```python
import requests

resp = requests.post(
    "http://localhost:8000/plugins/whisper/transcribe",
    json={},
    timeout=60,
)
print(resp.json())
```

## Notes
- If this plugin requires environment variables (e.g., HF_HOME, TORCH_HOME, TRANSFORMERS_OFFLINE), document them here.
- Add relevant reference links (model cards, docs) if applicable.
