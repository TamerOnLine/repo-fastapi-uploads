# app/plugins/whisper/plugin.py
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from app.core.config import get_settings
from app.plugins.base import AIPlugin


# ============================
# Globals (lazy-loaded once)
# ============================
_MODEL = None
_PROCESSOR = None
_PIPELINE = None  # optional: transformers pipeline for ASR


# ============================
# Helpers
# ============================
def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _fetch_bytes_from_url(url: str, timeout: int = 30) -> bytes:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _is_url(s: str) -> bool:
    try:
        p = urlparse(str(s))
        return p.scheme in ("http", "https")
    except Exception:
        return False


def _load_audio_mono16k(audio_bytes: bytes) -> tuple[list[float], int]:
    """
    Load audio from bytes into a mono 16k waveform (float32 list) and return (samples, sample_rate).
    Prefer soundfile or librosa if available; otherwise try torchaudio.

    Returns:
        (samples, 16000)
    Raises:
        RuntimeError if no supported backend is available.
    """
    # Try soundfile
    try:
        import soundfile as sf

        with io.BytesIO(audio_bytes) as bio:
            data, sr = sf.read(bio, dtype="float32", always_2d=False)
        # Convert to mono
        import numpy as np

        if data.ndim > 1:
            data = data.mean(axis=1)
        # Resample if needed
        if sr != 16000:
            try:
                import librosa

                data = librosa.resample(y=data, orig_sr=sr, target_sr=16000)
                sr = 16000
            except Exception:
                # Fallback: simple naive resample (not ideal)
                import numpy as np

                ratio = 16000 / float(sr)
                new_len = int(round(len(data) * ratio))
                if new_len > 1:
                    # linear interpolation
                    x_old = np.linspace(0, 1, num=len(data), endpoint=False)
                    x_new = np.linspace(0, 1, num=new_len, endpoint=False)
                    data = np.interp(x_new, x_old, data).astype("float32")
                    sr = 16000
        return data.tolist(), 16000
    except Exception:
        pass

    # Try librosa directly
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(io.BytesIO(audio_bytes), sr=16000, mono=True)
        y = y.astype("float32")
        return y.tolist(), 16000
    except Exception:
        pass

    # Try torchaudio
    try:
        import torch
        import torchaudio

        with io.BytesIO(audio_bytes) as bio:
            wav, sr = torchaudio.load(bio)  # [channels, time]
        if wav.dim() == 2 and wav.size(0) > 1:
            wav = wav.mean(dim=0, keepdim=True)
        wav = wav.squeeze(0)  # [time]
        # Resample if needed
        if sr != 16000:
            resampler = torchaudio.transforms.Resample(sr, 16000)
            wav = resampler(wav)
            sr = 16000
        return wav.to(dtype=torch.float32).cpu().numpy().tolist(), 16000
    except Exception:
        pass

    raise RuntimeError("Failed to load audio. Please install one of: soundfile, librosa, or torchaudio.")


def _read_audio_from_payload(payload: dict[str, Any]) -> tuple[list[float], int]:
    """
    Accepts:
      - rel_path: relative path under UPLOAD_DIR (e.g., 'audio/sample.wav')
      - path: absolute or relative (prefer rel_path)
      - url: http(s) url
      - base64: base64-encoded audio (raw file)
    Returns mono 16k samples as float list and sample rate (16000).
    """
    settings = get_settings()
    # 1) rel_path under uploads/
    rel_path = payload.get("rel_path")
    if rel_path:
        p = (Path(settings.UPLOAD_DIR) / rel_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Audio file not found: {p}")
        data = p.read_bytes()
        return _load_audio_mono16k(data)

    # 2) explicit path
    path = payload.get("path")
    if path and not _is_url(str(path)):
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Audio file not found: {p}")
        data = p.read_bytes()
        return _load_audio_mono16k(data)

    # 3) url
    url = payload.get("url")
    if url and _is_url(str(url)):
        data = _fetch_bytes_from_url(str(url))
        return _load_audio_mono16k(data)

    # 4) base64
    b64 = payload.get("base64")
    if b64:
        # if dict with "data", support that too
        if isinstance(b64, dict):
            b64 = b64.get("data")
        data = base64.b64decode(str(b64))
        return _load_audio_mono16k(data)

    raise ValueError("No audio source provided (rel_path | path | url | base64).")


# ============================
# Plugin implementation
# ============================
class Plugin(AIPlugin):
    """
    Whisper ASR plugin.

    Tasks:
      - transcribe:  {rel_path|url|base64}[, language, task, return_segments, translate]
                     -> {'text', 'language', 'segments?[]', 'duration?'}
    """

    name = "whisper"
    tasks = ["transcribe"]

    # Let the dynamic prefetcher know the required huggingface model
    REQUIRED_MODELS = [{"type": "hf", "id": "openai/whisper-small"}]

    def _ensure_loaded(self) -> None:
        global _MODEL, _PROCESSOR, _PIPELINE
        if _MODEL is not None and _PROCESSOR is not None:
            return

        # Lazily import heavy deps
        from transformers import (
            AutoProcessor,
            WhisperForConditionalGeneration,
            pipeline,
        )

        model_id = "openai/whisper-small"
        _PROCESSOR = AutoProcessor.from_pretrained(model_id)
        _MODEL = WhisperForConditionalGeneration.from_pretrained(model_id)

        # Optional pipeline (can be handy for simple usage)
        # Note: device_map="auto" will place on CUDA if available
        try:
            _PIPELINE = pipeline(
                "automatic-speech-recognition",
                model=_MODEL,
                tokenizer=_PROCESSOR.tokenizer,
                feature_extractor=_PROCESSOR.feature_extractor,
                device_map="auto",
            )
        except Exception:
            _PIPELINE = None

    # Optional prefetch hook (used by dynamic prefetch script)
    def prefetch(self) -> None:
        try:
            from transformers import AutoProcessor, WhisperForConditionalGeneration

            _ = AutoProcessor.from_pretrained("openai/whisper-small")
            _ = WhisperForConditionalGeneration.from_pretrained("openai/whisper-small")
        except Exception:
            # leave fallback to REQUIRED_MODELS in prefetch script
            pass

    # Legacy method required by AIPlugin; not used directly here
    def load(self) -> None:
        self._ensure_loaded()

    def infer(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Fallback to transcribe for legacy compatibility
        return self.transcribe(payload)

    # ============================
    # Task: /plugins/whisper/transcribe
    # ============================
    def transcribe(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Parameters (payload):
          - rel_path | path | url | base64 : audio source (required)
          - language: explicit language code (e.g., 'ar', 'en'); if None -> auto detect
          - task: 'transcribe' (default) or 'translate' (force English)
          - translate: bool, shortcut for task='translate'
          - return_segments: bool, default False
          - chunk_length_s: float (pipeline-only)
          - stride_length_s: float (pipeline-only)
        """
        self._ensure_loaded()

        # Read audio -> mono float32 @16k
        samples, sr = _read_audio_from_payload(payload)

        # Controls
        want_segments = bool(payload.get("return_segments", False))
        explicit_lang = payload.get("language")
        task = (payload.get("task") or "").strip().lower()
        if task not in ("", "transcribe", "translate"):
            task = "transcribe"

        # boolean translate flag overrides task
        if str(payload.get("translate", "")).lower() in ("1", "true", "yes"):
            task = "translate"

        # Try pipeline first (simple & robust)
        if _PIPELINE is not None:
            pipe_kwargs: dict[str, Any] = {
                "return_timestamps": "word" if want_segments else False,
            }

            # chunk/stride controls (optional)
            cls = payload.get("chunk_length_s")
            sls = payload.get("stride_length_s")
            if cls is not None:
                pipe_kwargs["chunk_length_s"] = float(cls)
            if sls is not None:
                pipe_kwargs["stride_length_s"] = float(sls)

            # task & language
            if explicit_lang:
                pipe_kwargs["generate_kwargs"] = {
                    "language": explicit_lang,
                    "task": task or "transcribe",
                }
            elif task:
                pipe_kwargs["generate_kwargs"] = {"task": task}

            # Run
            # Pipeline accepts either file path or numpy array; we pass array
            import numpy as np

            audio_np = np.asarray(samples, dtype="float32")
            out = _PIPELINE(audio_np, **pipe_kwargs)

            # Standardize output
            text = out["text"] if isinstance(out, dict) and "text" in out else str(out)
            language = out.get("language") if isinstance(out, dict) else explicit_lang or None
            result: dict[str, Any] = {
                "ok": True,
                "text": text,
                "language": language,
                "sample_rate": sr,
            }

            # Timestamps/segments (if available)
            if want_segments:
                # Some pipeline versions return 'chunks' or 'segments'
                segs = []
                if isinstance(out, dict) and "chunks" in out and isinstance(out["chunks"], list):
                    for ch in out["chunks"]:
                        segs.append(
                            {
                                "text": ch.get("text"),
                                "timestamp": ch.get("timestamp"),
                            }
                        )
                result["segments"] = segs

            return result

        # Fallback: manual generate() with processor+model
        import numpy as np
        from transformers import GenerationConfig

        audio_np = np.asarray(samples, dtype="float32")
        inputs = _PROCESSOR.feature_extractor(audio_np, sampling_rate=sr, return_tensors="pt")
        input_features = inputs.input_features.to(_MODEL.device)

        gen_kwargs = {}
        if explicit_lang:
            gen_kwargs["language"] = explicit_lang
        if task in ("transcribe", "translate"):
            gen_kwargs["task"] = task

        # Some versions use forced_decoder_ids via processor.get_decoder_prompt_ids
        try:
            forced_ids = _PROCESSOR.get_decoder_prompt_ids(
                language=explicit_lang if explicit_lang else None,
                task=task if task else "transcribe",
            )
            generation_config = GenerationConfig.forced_decoder_ids_for_generation(forced_ids)
        except Exception:
            generation_config = None

        with _MODEL.eval():
            pred_ids = _MODEL.generate(
                input_features,
                generation_config=generation_config,
                max_new_tokens=_safe_int(payload.get("max_new_tokens", 448), 448),
                num_beams=_safe_int(payload.get("num_beams", 1), 1),
            )

        text = _PROCESSOR.tokenizer.batch_decode(pred_ids, skip_special_tokens=True)[0]
        return {
            "ok": True,
            "text": text,
            "language": explicit_lang,  # language detection not provided in this fallback
            "sample_rate": sr,
        }
