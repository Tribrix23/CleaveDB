"""Weight persistence for attention models (QUA, SRA, AQP, BDA).

Supports JSON (portable) and binary (fast) formats for saving/loading
model weights used by the attention-based query processing layers.
"""
import json
import os
import struct
from typing import Any, Dict, List, Optional


class WeightStore:
    """Persist and load model weights in JSON or binary format.
    
    JSON format: human-readable, portable, good for small models.
    Binary format: compact, fast, good for large weight matrices.
    """

    @staticmethod
    def save_json(weights: Dict[str, Any], path: str):
        """Save weights as pretty-printed JSON."""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        # Write atomically via temp file
        tmp_path = path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(weights, f, indent=2, default=_json_serializer)
        os.replace(tmp_path, path)

    @staticmethod
    def load_json(path: str) -> Dict[str, Any]:
        """Load weights from JSON file."""
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def save_binary(weights: Dict[str, List[float]], path: str):
        """Save float weight vectors in compact binary format.
        
        Format per entry:
        [name_len: u16][name: utf8 bytes][n_floats: u32][floats: f32 × n]
        """
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, 'wb') as f:
            # Header: magic + version + entry count
            f.write(b'CDB3')  # magic
            f.write(struct.pack('<HI', 1, len(weights)))  # version=1, n_entries

            for name, values in weights.items():
                name_bytes = name.encode('utf-8')
                f.write(struct.pack('<H', len(name_bytes)))
                f.write(name_bytes)

                if isinstance(values, list):
                    floats = values
                elif isinstance(values, dict):
                    # Flatten dict values
                    floats = list(values.values()) if all(isinstance(v, (int, float)) for v in values.values()) else []
                else:
                    floats = [float(values)] if isinstance(values, (int, float)) else []

                f.write(struct.pack('<I', len(floats)))
                for v in floats:
                    f.write(struct.pack('<f', float(v)))

        os.replace(tmp_path, path)

    @staticmethod
    def load_binary(path: str) -> Dict[str, List[float]]:
        """Load float weight vectors from binary format."""
        weights = {}
        with open(path, 'rb') as f:
            magic = f.read(4)
            if magic != b'CDB3':
                raise ValueError(f"Invalid weight file magic: {magic!r}")

            version, n_entries = struct.unpack('<HI', f.read(6))
            if version != 1:
                raise ValueError(f"Unsupported weight file version: {version}")

            for _ in range(n_entries):
                name_len = struct.unpack('<H', f.read(2))[0]
                name = f.read(name_len).decode('utf-8')
                n_floats = struct.unpack('<I', f.read(4))[0]
                values = list(struct.unpack(f'<{n_floats}f', f.read(4 * n_floats)))
                weights[name] = values

        return weights

    @staticmethod
    def exists(path: str) -> bool:
        return os.path.exists(path)


def _json_serializer(obj):
    """Custom JSON serializer for weight objects."""
    if isinstance(obj, float):
        if obj != obj:  # NaN
            return None
        return obj
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class ModelCheckpoint:
    """Manages versioned model checkpoints with rollback support."""

    def __init__(self, checkpoint_dir: str):
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(checkpoint_dir, exist_ok=True)

    def save(self, name: str, weights: Dict, version: Optional[int] = None):
        """Save a named checkpoint."""
        if version is None:
            version = self._next_version(name)
        path = os.path.join(self.checkpoint_dir, f"{name}_v{version}.json")
        WeightStore.save_json(weights, path)
        # Update 'latest' symlink/file
        latest_path = os.path.join(self.checkpoint_dir, f"{name}_latest.json")
        WeightStore.save_json({"version": version, "path": path}, latest_path)
        return version

    def load_latest(self, name: str) -> Optional[Dict]:
        """Load the latest checkpoint for a model."""
        latest_path = os.path.join(self.checkpoint_dir, f"{name}_latest.json")
        if not os.path.exists(latest_path):
            return None
        meta = WeightStore.load_json(latest_path)
        return WeightStore.load_json(meta["path"])

    def _next_version(self, name: str) -> int:
        """Find the next version number."""
        import glob
        pattern = os.path.join(self.checkpoint_dir, f"{name}_v*.json")
        existing = glob.glob(pattern)
        if not existing:
            return 1
        versions = []
        for p in existing:
            base = os.path.basename(p)
            try:
                v = int(base.split('_v')[1].split('.')[0])
                versions.append(v)
            except (IndexError, ValueError):
                pass
        return max(versions, default=0) + 1
