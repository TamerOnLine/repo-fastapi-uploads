# text_tools

**Type:** service
**Provider:** _unknown_
**Tasks:** arabic_normalize, spellcheck_ar



## Models
- _None_

## Usage

### API Overview
- `GET /services` — list all available services.
- `GET /services/{name}` — get metadata for this service.
- `POST /services/{name}/{task}` — run a task of this service.

> Replace `{name}` with this service's folder name and `{task}` with one of the tasks listed above.

### cURL Example
```bash
curl -X POST "http://localhost:8000/services/text_tools/arabic_normalize"      -H "Content-Type: application/json"      -d '{}'
```

### Python Example
```python
import requests

resp = requests.post(
    "http://localhost:8000/services/text_tools/arabic_normalize",
    json={},
    timeout=60,
)
print(resp.json())
```

## Notes
- If this service requires environment variables (e.g., HF_HOME, TORCH_HOME, TRANSFORMERS_OFFLINE), document them here.
- Add relevant reference links (model cards, docs) if applicable.
