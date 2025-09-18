#!/usr/bin/env python3
from pathlib import Path


p = Path("app/api/router_inference.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    'raise HTTPException(status_code=400, detail="Plugin and task are required") from e',
    'raise HTTPException(status_code=400, detail="Plugin and task are required")',
)
s = s.replace(
    "raise HTTPException(status_code=404, detail=f\"Task '{req.task}' not found in plugin '{req.plugin}'\") from e",
    "raise HTTPException(status_code=404, detail=f\"Task '{req.task}' not found in plugin '{req.plugin}'\")",
)
p.write_text(s, encoding="utf-8")
print("Patched:", p)
