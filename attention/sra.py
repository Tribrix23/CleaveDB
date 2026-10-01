import os
import json
import numpy as np

# Hide huggingface symlinks warning on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

try:
    from tokenizers import Tokenizer
    import onnxruntime as ort
    
    print("SRA Module: Initializing Hardware-Efficient AI Semantic Search (ONNX Q8_0)...")
    
    # Model is fully bundled inside the attention/model directory
    _model_path = os.path.join(os.path.dirname(__file__), 'model', 'model_quantized.onnx')
    _vocab_path = os.path.join(os.path.dirname(__file__), 'model', 'tokenizer.json')

    _tokenizer = Tokenizer.from_file(_vocab_path)
    # CPU Execution Provider leverages AVX instructions under the hood
    _session = ort.InferenceSession(_model_path, providers=['CPUExecutionProvider'])
    
    _AI_ENABLED = True
except ImportError:
    print("SRA Module: ML dependencies not found. Falling back to exact matching.")
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
