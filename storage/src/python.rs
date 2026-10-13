use pyo3::prelude::*;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use std::path::PathBuf;
use std::sync::Arc;
use serde_json;

use crate::buffer_pool::BufferPool;
use crate::wal::{WriteAheadLog, WalConfig, SyncMode};
use crate::btree::BTree;
use crate::engine::{
    Catalog, ShardManager, InvertedIndex, Document, Database,
};

const RESERVED_BUCKET_NAMES: &[&str] = &[
    "buckets", "bucket", "bonds", "bond", "links", "link",
    "indexes", "index", "stats", "webhooks", "views", "nodes",
    "coordinator", "raft", "meaning"
];

/// Python-facing CleaveDB handle that owns the full storage engine.
#[pyclass]
pub struct CleaveDB {
    db: Database,
    data_dir: PathBuf,
}

#[pymethods]
impl CleaveDB {
    /// Open or create a CleaveDB database at the given directory path.
    #[new]
    pub fn new(path: &str) -> PyResult<Self> {
        let data_dir = PathBuf::from(path);
        std::fs::create_dir_all(&data_dir)
            .map_err(|e| PyRuntimeError::new_err(format!("Cannot create data dir: {}", e)))?;

        // Buffer pool: 256 frames × 16 KB = 4 MB cache
        let pool = Arc::new(
            BufferPool::new(256)
        );

        // WAL
        let wal_dir = data_dir.join("wal");
        std::fs::create_dir_all(&wal_dir)
            .map_err(|e| PyRuntimeError::new_err(format!("Cannot create WAL dir: {}", e)))?;
        let wal_config = WalConfig {
            dir: wal_dir,
            sync_mode: SyncMode::Async,
            segment_max_bytes: 64 * 1024 * 1024,
            flush_interval_ms: 50,
        };
        let wal = Arc::new(
            WriteAheadLog::open(wal_config)
                .map_err(|e| PyRuntimeError::new_err(format!("WAL open failed: {}", e)))?
        );

        // Shards: 4 shards by default
        let shards_dir = data_dir.join("shards");
        std::fs::create_dir_all(&shards_dir)
            .map_err(|e| PyRuntimeError::new_err(format!("Cannot create shards dir: {}", e)))?;
        let shards = ShardManager::new(4, pool.clone(), wal.clone(), &shards_dir)
            .map_err(|e| PyRuntimeError::new_err(format!("ShardManager init failed: {}", e)))?;

        // Inverted index B+Tree
        let idx_path = data_dir.join("inverted.db");
        let idx_tree = BTree::new(
            pool.clone(), wal.clone(), "inverted_index".to_string(), idx_path,
        ).map_err(|e| PyRuntimeError::new_err(format!("InvertedIndex init failed: {}", e)))?;
        let inverted = InvertedIndex::new(idx_tree);

        // Catalog (load existing or create empty)
        let catalog_path = data_dir.join("catalog.msgpack");
        let catalog = if catalog_path.exists() {
            Catalog::load(&catalog_path)
                .unwrap_or_else(|_| Catalog::new())
        } else {
            Catalog::new()
        };
        let phantom_lattice = Arc::new(crate::engine::PhantomLattice::new());

        let db = Database {
            catalog,
            shards,
            inverted,
            phantom_lattice,
        };

        if let Ok(entries) = wal.recover() {
            for entry in entries {
                match entry {
                    crate::wal::WalEntry::Put { tree_name, key, value, .. } => {
                        if tree_name == "inverted_index" {
                            let _ = db.inverted.tree().insert_unlogged(&key, &value);
                        } else if tree_name.starts_with("shard_") {
                            if let Ok(idx) = tree_name.trim_start_matches("shard_").parse::<usize>() {
                                let all = db.shards.all_shards();
                                if idx < all.len() {
                                    let _ = all[idx].insert_unlogged(&key, &value);
                                }
                            }
                        }
                    }
                    crate::wal::WalEntry::Delete { tree_name, key, .. } => {
                        if tree_name == "inverted_index" {
                            let _ = db.inverted.tree().delete_unlogged(&key);
                        } else if tree_name.starts_with("shard_") {
                            if let Ok(idx) = tree_name.trim_start_matches("shard_").parse::<usize>() {
                                let all = db.shards.all_shards();
                                if idx < all.len() {
                                    let _ = all[idx].delete_unlogged(&key);
                                }
                            }
                        }
                    }
                    _ => {}
                }
            }
        }

        // Cold-Start Latch Warmup: Recover persisted latched shadow bonds into in-memory Phantom Lattice
        let prefix = "_bonds:".as_bytes();
        for shard in db.shards.all_shards() {
            if let Ok(mut cursor) = crate::btree::cursor::Cursor::new(shard) {
                while let Ok(Some((key, value))) = cursor.next() {
                    if key.starts_with(prefix) {
                        if let Ok(doc) = Document::from_msgpack(&value) {
                            if let Some(status) = doc.body.get("status").and_then(|s| s.as_str()) {
                                if status == "latched" {
                                    let src = doc.body.get("source").and_then(|s| s.as_str()).unwrap_or("").to_string();
                                    let tgt = doc.body.get("target").and_then(|s| s.as_str()).unwrap_or("").to_string();
                                    let rel = doc.body.get("label").and_then(|s| s.as_str()).unwrap_or("").to_string();
                                    let enf_str = doc.body.get("enforcement").and_then(|s| s.as_str()).unwrap_or("soft");
                                    let enforcement = match enf_str.to_lowercase().as_str() {
                                        "strict" => crate::engine::bucket_bond::Enforcement::Strict,
                                        "firm" => crate::engine::bucket_bond::Enforcement::Firm,
                                        _ => crate::engine::bucket_bond::Enforcement::Soft,
                                    };
                                    let created_at = doc.body.get("created_at").and_then(|v| v.as_u64()).unwrap_or(0);
                                    let lease_expiry = doc.body.get("expires_at").and_then(|v| v.as_u64());
                                    let cascade = doc.body.get("cascade").and_then(|v| v.as_bool()).unwrap_or(false);
                                    let shadow = crate::engine::phantom_lattice::ShadowRecord {
                                        src_gid: src,
                                        target_gid: tgt,
                                        rel_name: rel,
                                        enforcement,
                                        created_at_ts: created_at,
                                        lease_expiry_ts: lease_expiry,
                                        cascade_delete: cascade,
                                        status: "latched".to_string(),
                                    };
                                    let _ = db.phantom_lattice.register_shadow_bond(shadow);
                                }
                            }
                        }
                    }
                }
            }
        }

        Ok(Self { db, data_dir })
    }

    /// Insert a document: pour(bucket, doc_id, json_string)
    pub fn pour(&self, bucket: &str, doc_id: Option<&str>, json_body: &str) -> PyResult<String> {
        let b_lower = bucket.to_lowercase();
        if RESERVED_BUCKET_NAMES.contains(&b_lower.as_str()) {
            return Err(PyRuntimeError::new_err(format!(
                "Cannot use reserved keyword '{}' as a bucket name. This name is reserved for CleaveQL catalog commands.",
                bucket
            )));
        }

        let body: serde_json::Value = serde_json::from_str(json_body)
            .map_err(|e| PyValueError::new_err(format!("Invalid JSON: {}", e)))?;

        let doc = Document::new(bucket, body, doc_id);
        let gid = doc.gid.clone();
        self.db.put(doc)
            .map_err(|e| PyRuntimeError::new_err(format!("put failed: {}", e)))?;
        Ok(gid)
    }

    /// Fetch a single document by GID. Returns JSON string or None.
    pub fn get(&self, gid: &str) -> PyResult<Option<String>> {
        match self.db.get(gid) {
            Ok(Some(doc)) => {
                let json = serde_json::to_string(&doc.body)
                    .map_err(|e| PyRuntimeError::new_err(format!("serialize error: {}", e)))?;
                Ok(Some(json))
            }
            Ok(None) => Ok(None),
            Err(e) => Err(PyRuntimeError::new_err(format!("get failed: {}", e))),
        }
    }

    /// Delete a document by GID. Returns true if it existed.
        /// Scan all documents in a specific bucket
    pub fn scan_bucket(&self, bucket: &str) -> PyResult<String> {
        let prefix = format!("{}:", bucket);
        let prefix_bytes = prefix.as_bytes();
        let mut results = Vec::new();
        
        for shard in self.db.shards.all_shards() {
            if let Ok(mut cursor) = crate::btree::cursor::Cursor::new(shard) {
                while let Ok(Some((key, value))) = cursor.next() {
                    if key.starts_with(prefix_bytes) {
                        if let Ok(doc) = Document::from_msgpack(&value) {
                            results.push(doc);
                        }
                    }
                }
            }
        }
        
        let json = serde_json::to_string(&results)
            .map_err(|e| PyRuntimeError::new_err(format!("serialize error: {}", e)))?;
        Ok(json)
    }

    pub fn delete(&self, gid: &str) -> PyResult<bool> {
        self.db.delete(gid)
            .map_err(|e| PyRuntimeError::new_err(format!("delete failed: {}", e)))
    }

    /// Heal: rebuild all indexes from documents.
    pub fn heal(&self, _target: Option<&str>) -> PyResult<String> {
        self.db.heal_all()
            .map_err(|e| PyRuntimeError::new_err(format!("heal failed: {}", e)))?;
        Ok("heal complete".to_string())
    }

    /// Show metadata about the database.
    pub fn show(&self, target: Option<&str>) -> PyResult<String> {
        let target = target.unwrap_or("buckets");
        match target {
            "buckets" => {
                let mut unique_buckets = std::collections::HashSet::new();
                
                // Add any explicitly defined buckets from catalog
                for b in &self.db.catalog.buckets {
                    unique_buckets.insert(b.name.clone());
                }
                
                // Scan all shards to find implicit buckets (schema-less)
                for shard in self.db.shards.all_shards() {
                    if let Ok(mut cursor) = crate::btree::cursor::Cursor::new(shard) {
                        while let Ok(Some((key, _))) = cursor.next() {
                            if let Ok(key_str) = std::str::from_utf8(&key) {
                                if let Some(idx) = key_str.find(':') {
                                    let bucket_name = &key_str[..idx];
                                    unique_buckets.insert(bucket_name.to_string());
                                }
                            }
                        }
                    }
                }
                
                let mut names: Vec<String> = unique_buckets.into_iter().collect();
                names.sort();
                Ok(serde_json::to_string_pretty(&names).unwrap_or_default())
            }
            "bonds" => {
                let names: Vec<String> = self.db.catalog.bonds.iter()
                    .map(|b| b.name.clone())
                    .collect();
                Ok(serde_json::to_string_pretty(&names).unwrap_or_default())
            }
            "indexes" => {
                Ok(serde_json::to_string_pretty(&self.db.catalog.indexes).unwrap_or_default())
            }
            "pending" | "phantom" | "latches" => {
                self.phantom_stats()
            }
            _ => Ok(format!("Unknown target: {}", target)),
        }
    }

    /// Get all pending shadow bonds from the Phantom Lattice.
    #[pyo3(signature = (target_gid=None))]
    pub fn get_pending_bonds(&self, target_gid: Option<&str>) -> PyResult<String> {
        let pending = self.db.phantom_lattice.get_pending_bonds(target_gid);
        serde_json::to_string_pretty(&pending)
            .map_err(|e| PyRuntimeError::new_err(format!("Serialization error: {}", e)))
    }

    /// Sweep expired firm bonds whose lease duration has elapsed.
    #[pyo3(signature = (current_ts=None))]
    pub fn sweep_expired_bonds(&self, current_ts: Option<u64>) -> PyResult<String> {
        let swept = self.db.sweep_expired_bonds(current_ts);
        serde_json::to_string_pretty(&swept)
            .map_err(|e| PyRuntimeError::new_err(format!("Serialization error: {}", e)))
    }

    /// Telemetry and statistics of the Phantom Lattice.
    pub fn phantom_stats(&self) -> PyResult<String> {
        let stats = self.db.phantom_lattice.stats();
        serde_json::to_string_pretty(&stats)
            .map_err(|e| PyRuntimeError::new_err(format!("Serialization error: {}", e)))
    }

    /// Search the inverted index for a term. Returns JSON array of (doc_id, freq) pairs.
    pub fn search_text(&self, term: &str) -> PyResult<String> {
        let results = self.db.inverted.search(term)
            .map_err(|e| PyRuntimeError::new_err(format!("search failed: {}", e)))?;
        let json: Vec<serde_json::Value> = results.into_iter()
            .map(|(doc_id, freq)| serde_json::json!({"gid": doc_id, "freq": freq}))
            .collect();
        Ok(serde_json::to_string(&json).unwrap_or_default())
    }

    /// Get the data directory path.
    pub fn data_dir(&self) -> String {
        self.data_dir.to_string_lossy().into_owned()
    }

    /// Debug: iterate entire inverted index tree and return count + first 10 keys.
    pub fn debug_inverted(&self) -> PyResult<String> {
        use crate::btree::cursor::Cursor;
        let tree = self.db.inverted.tree();

        // Check root page id
        let root_id = tree.root_page_id.load(std::sync::atomic::Ordering::SeqCst);

        // Try direct get for a sample key
        let sample_result = tree.get(b"hello:d1").unwrap_or(None);

        // Check what's on the root page - slot-level detail
        let root_info = {
            let frame = tree.pool.fetch(&tree.file_path, root_id).ok();
            frame.map(|f| {
                let guard = f.read();
                let page = guard.as_ref().unwrap();
                let n = page.n_entries();
                let mut slot_info = Vec::new();
                for i in 0..n as usize {
                    let entry = page.get_at(i);
                    match entry {
                        Some((k, _v)) => {
                            let ks = String::from_utf8_lossy(k);
                            slot_info.push(format!("slot{}='{}'", i, ks));
                        }
                        None => slot_info.push(format!("slot{}=None", i)),
                    }
                }
                format!("root_id={}, type={:?}, n_entries={}, slots=[{}]",
                    root_id, page.page_type(), n, slot_info.join(", "))
            }).unwrap_or_else(|| "no root".into())
        };

        // Iterate cursor
        let mut cursor = Cursor::new(tree)
            .map_err(|e| PyRuntimeError::new_err(format!("cursor error: {}", e)))?;
        let mut count = 0;
        let mut sample_keys = Vec::new();
        while let Ok(Some((k, _v))) = cursor.next() {
            count += 1;
            if sample_keys.len() < 10 {
                if let Ok(s) = String::from_utf8(k) {
                    sample_keys.push(s);
                }
            }
        }
        Ok(format!("{}, direct_get={}, cursor_count={}, samples={:?}",
            root_info, sample_result.is_some(), count, sample_keys))
    }

    /// Computes the sum of a contiguous float32 array using AVX-512 vectorization.
    #[pyo3(signature = (a, b))]
    fn simd_dot_product(&self, a: Vec<f32>, b: Vec<f32>) -> PyResult<f32> {
        Ok(crate::simd_ffi::dot_product(&a, &b))
    }

    #[pyo3(signature = (arr))]
    fn simd_sum_avx512(&self, arr: Vec<f32>) -> PyResult<f32> {
        let n = arr.len() as std::os::raw::c_int;
        let sum = unsafe { crate::simd_ffi::cleavedb_sum_avx512(arr.as_ptr(), n) };
        Ok(sum)
    }
}

#[pymodule]
fn cleavedb3_storage(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CleaveDB>()?;
    Ok(())
}
