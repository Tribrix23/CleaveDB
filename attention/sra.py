import os
import json
import numpy as np

# Hide huggingface symlinks warning on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

try:
    import sys
    from tokenizers import Tokenizer
    import onnxruntime as ort
    
    print("SRA Module: Initializing Hardware-Efficient AI Semantic Search (ONNX Q8_0)...")
    
    # Locate model and tokenizer across known potential locations
    _candidates = [
        os.path.join(os.path.dirname(__file__), 'model'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'model'),
        os.path.join(os.path.dirname(sys.executable), 'attention', 'model'),
        os.path.join(os.path.dirname(sys.executable), '_internal', 'attention', 'model'),
        os.path.join(os.getcwd(), 'attention', 'model')
    ]
    
    _model_path = None
    _vocab_path = None
    for c in _candidates:
        m = os.path.join(c, 'model_quantized.onnx')
        v = os.path.join(c, 'tokenizer.json')
        if os.path.exists(m) and os.path.exists(v):
            _model_path = m
            _vocab_path = v
            break

    if not _model_path or not _vocab_path:
        raise FileNotFoundError(f"Model files not found in any candidate path: {_candidates}")

    _tokenizer = Tokenizer.from_file(_vocab_path)
    # CPU Execution Provider leverages AVX instructions under the hood
    _session = ort.InferenceSession(_model_path, providers=['CPUExecutionProvider'])
    
    _AI_ENABLED = True
except Exception as e:
    print(f"SRA Module: ML model not loaded ({e}). Falling back to exact matching.")
    _AI_ENABLED = False

def get_embedding(text: str) -> np.ndarray:
    if not _AI_ENABLED:
        return np.zeros((1, 384))
        
    enc = _tokenizer.encode(text)
    input_ids = np.array([enc.ids], dtype=np.int64)
    attention_mask = np.array([enc.attention_mask], dtype=np.int64)
    token_type_ids = np.zeros_like(input_ids, dtype=np.int64)
    
    outputs = _session.run(None, {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "token_type_ids": token_type_ids
    })
    
    # Mean pooling
    last_hidden_state = outputs[0]
    mask_expanded = attention_mask[..., np.newaxis]
    sum_emb = np.sum(last_hidden_state * mask_expanded, axis=1)
    sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
    emb = sum_emb / sum_mask
    
    # Normalize
    norm = np.linalg.norm(emb, axis=1, keepdims=True)
    return (emb / norm)[0] # return the flat 1D vector

def compute_similarity(text1: str, text2: str) -> float:
    if not _AI_ENABLED:
        return 1.0 if text1.lower() == text2.lower() else 0.0
    e1 = get_embedding(text1)
    e2 = get_embedding(text2)
    return float(np.dot(e1, e2))

def get_diagnostics() -> dict:
    if not _AI_ENABLED:
        return {"status": "offline", "reason": "Missing ML dependencies"}
    
    meta = _session.get_modelmeta()
    
    return {
        "model": "all-MiniLM-L6-v2",
        "onnx_version": ort.__version__,
        "providers": _session.get_providers(),
        "input_names": [i.name for i in _session.get_inputs()],
        "output_names": [o.name for o in _session.get_outputs()],
        "dim": _session.get_outputs()[0].shape[-1],
        "hw_acceleration": _session.get_providers()[0] if _session.get_providers() else "Unknown",
        "custom_metadata": meta.custom_metadata_map if hasattr(meta, "custom_metadata_map") else {}
    }
