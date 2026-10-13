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
        let dbsp = Arc::new(crate::engine::DifferentialCircuit::new());
        let branches = Arc::new(crate::engine::BranchManager::new());

        let db = Database {
            catalog,
            shards,
            inverted,
            phantom_lattice,
            dbsp,
            branches,
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

    // =========================================================================
    // Breakthrough 2: Continuous Graph-DBSP Engine
    // =========================================================================

    /// Registers a continuous recursive or direct graph view.
    #[pyo3(signature = (name, edge_label="*", is_recursive=true))]
    pub fn create_continuous_view(&self, name: &str, edge_label: &str, is_recursive: bool) -> PyResult<String> {
        self.db.dbsp.register_view(name, edge_label, is_recursive);
        Ok(format!("Continuous view '{}' registered successfully.", name))
    }

    /// Pushes a graph difference (+1 for bond creation, -1 for severance).
    #[pyo3(signature = (src, tgt, label, weight))]
    pub fn push_edge_delta(&self, src: &str, tgt: &str, label: &str, weight: i64) -> PyResult<String> {
        let deltas = self.db.dbsp.push_edge_delta(src, tgt, label, weight);
        serde_json::to_string_pretty(&deltas)
            .map_err(|e| PyRuntimeError::new_err(format!("Serialization error: {}", e)))
    }

    /// Queries the current materialized reachable paths for a given continuous view.
    pub fn get_continuous_view(&self, name: &str) -> PyResult<String> {
        match self.db.dbsp.get_view_paths(name) {
            Some(paths) => {
                let formatted: Vec<serde_json::Value> = paths.into_iter()
                    .map(|(s, t)| serde_json::json!({"source": s, "target": t}))
                    .collect();
                serde_json::to_string_pretty(&formatted)
                    .map_err(|e| PyRuntimeError::new_err(format!("Serialization error: {}", e)))
            }
            None => Err(PyRuntimeError::new_err(format!("Continuous view '{}' not found", name))),
        }
    }

    /// Lists all registered continuous views.
    pub fn list_continuous_views(&self) -> PyResult<String> {
        let views = self.db.dbsp.list_views();
        serde_json::to_string_pretty(&views)
            .map_err(|e| PyRuntimeError::new_err(format!("Serialization error: {}", e)))
    }

    // =========================================================================
    // Breakthrough 3: Worst-Case Optimal Subgraph Intersection (Leapfrog Triejoin)
    // =========================================================================

    /// Executes Leapfrog Triejoin (LTJ) over a given list of edge pairs [[src, tgt], ...]
    /// or collects edges directly from _bonds. Returns AGM-optimal triangle matches and stats.
    #[pyo3(signature = (edges_json=None))]
    pub fn execute_leapfrog_join(&self, edges_json: Option<&str>) -> PyResult<String> {
        let mut edges: Vec<(String, String)> = Vec::new();

        if let Some(raw) = edges_json {
            let parsed: Vec<Vec<String>> = serde_json::from_str(raw)
                .map_err(|e| PyValueError::new_err(format!("Invalid edges JSON: {}", e)))?;
            for pair in parsed {
                if pair.len() >= 2 {
                    edges.push((pair[0].clone(), pair[1].clone()));
                }
            }
        } else {
            // Scan live bonds from _bonds bucket
            let prefix = "_bonds:".as_bytes();
            for shard in self.db.shards.all_shards() {
                if let Ok(mut cursor) = crate::btree::cursor::Cursor::new(shard) {
                    while let Ok(Some((key, value))) = cursor.next() {
                        if key.starts_with(prefix) {
                            if let Ok(doc) = Document::from_msgpack(&value) {
                                if let (Some(s), Some(t)) = (
                                    doc.body.get("source").and_then(|v| v.as_str()),
                                    doc.body.get("target").and_then(|v| v.as_str())
                                ) {
                                    edges.push((s.to_string(), t.to_string()));
                                }
                            }
                        }
                    }
                }
            }
        }

        let ltj = crate::engine::leapfrog::LeapfrogTriejoin::new(edges);
        let (triangles, stats) = ltj.find_triangles();

        let out = serde_json::json!({
            "triangles": triangles,
            "stats": stats,
        });

        serde_json::to_string_pretty(&out)
            .map_err(|e| PyRuntimeError::new_err(format!("Serialization error: {}", e)))
    }

    // =========================================================================
    // Breakthrough 4: Zero-Copy Speculative Branching & Sandboxed Mutation
    // =========================================================================

    /// Creates an isolated speculative branch in microseconds.
    pub fn branch_create(&self, name: &str) -> PyResult<String> {
        self.db.branches.create_branch(name)
            .map_err(|e| PyRuntimeError::new_err(format!("branch_create failed: {}", e)))?;
        Ok(format!("Branch '{}' created.", name))
    }

    /// Discards a speculative branch instantly in O(1) time.
    pub fn branch_discard(&self, name: &str) -> PyResult<bool> {
        Ok(self.db.branches.discard_branch(name))
    }

    /// Writes a document into a speculative branch without mutating master pages.
    pub fn branch_pour(&self, branch_name: &str, bucket: &str, doc_id: Option<&str>, json_body: &str) -> PyResult<String> {
        let body: serde_json::Value = serde_json::from_str(json_body)
            .map_err(|e| PyValueError::new_err(format!("Invalid JSON: {}", e)))?;
        let doc = Document::new(bucket, body, doc_id);
        let gid = doc.gid.clone();
        self.db.branches.branch_put(branch_name, doc)
            .map_err(|e| PyRuntimeError::new_err(format!("branch_pour failed: {}", e)))?;
        Ok(gid)
    }

    /// Reads a document from a speculative branch (checks branch deltas first, falls back to master).
    pub fn branch_get(&self, branch_name: &str, gid: &str) -> PyResult<Option<String>> {
        match self.db.branches.branch_get(branch_name, gid, &self.db) {
            Ok(Some(doc)) => {
                let json = serde_json::to_string(&doc.body)
                    .map_err(|e| PyRuntimeError::new_err(format!("serialize error: {}", e)))?;
                Ok(Some(json))
            }
            Ok(None) => Ok(None),
            Err(e) => Err(PyRuntimeError::new_err(format!("branch_get failed: {}", e))),
        }
    }

    /// Soft-deletes a document inside a speculative branch.
    pub fn branch_delete(&self, branch_name: &str, gid: &str) -> PyResult<bool> {
        self.db.branches.branch_delete(branch_name, gid)
            .map_err(|e| PyRuntimeError::new_err(format!("branch_delete failed: {}", e)))
    }

    /// Scans a bucket within a branch, overlaying branch mutations on master data.
    pub fn branch_scan_bucket(&self, branch_name: &str, bucket: &str) -> PyResult<String> {
        let docs = self.db.branches.branch_scan_bucket(branch_name, bucket, &self.db)
            .map_err(|e| PyRuntimeError::new_err(format!("branch_scan_bucket failed: {}", e)))?;
        serde_json::to_string(&docs)
            .map_err(|e| PyRuntimeError::new_err(format!("serialize error: {}", e)))
    }

    /// Merges branch mutations back into the master database atomically.
    #[pyo3(signature = (branch_name, conflict_resolution=None))]
    pub fn branch_merge(&self, branch_name: &str, conflict_resolution: Option<&str>) -> PyResult<String> {
        let strat = conflict_resolution.unwrap_or("last_write_wins");
        let report = self.db.branches.merge_branch(branch_name, &self.db, strat)
            .map_err(|e| PyRuntimeError::new_err(format!("branch_merge failed: {}", e)))?;
        serde_json::to_string_pretty(&report)
            .map_err(|e| PyRuntimeError::new_err(format!("serialize error: {}", e)))
    }

    /// Lists active speculative branches.
    pub fn branch_list(&self) -> PyResult<String> {
        let list = self.db.branches.list_branches();
        serde_json::to_string_pretty(&list)
            .map_err(|e| PyRuntimeError::new_err(format!("serialize error: {}", e)))
    }

    // =========================================================================
    // Breakthrough 5: Contextual Epistemic Masking & Path-Dependent Invariant Guards
    // =========================================================================

    /// Checks if adding (new_src -> new_tgt) creates a forbidden directed cycle.
    pub fn verify_graph_sat_acyclic(&self, edges_json: &str, new_src: &str, new_tgt: &str) -> PyResult<()> {
        let parsed: Vec<Vec<String>> = serde_json::from_str(edges_json)
            .map_err(|e| PyValueError::new_err(format!("Invalid edges JSON: {}", e)))?;
        let edges: Vec<(String, String)> = parsed.into_iter()
            .filter(|p| p.len() >= 2)
            .map(|p| (p[0].clone(), p[1].clone()))
            .collect();

        crate::engine::graph_sat::GraphSatEngine::verify_acyclic(&edges, new_src, new_tgt)
            .map_err(|err_msg| PyValueError::new_err(err_msg))
    }

    /// Evaluates epistemic authorization: checks if a valid path connects requester to target.
    #[pyo3(signature = (edges_json, requester, target, label="*", max_depth=3))]
    pub fn verify_epistemic_path(&self, edges_json: &str, requester: &str, target: &str, label: &str, max_depth: usize) -> PyResult<String> {
        let parsed: Vec<Vec<String>> = serde_json::from_str(edges_json)
            .map_err(|e| PyValueError::new_err(format!("Invalid edges JSON: {}", e)))?;
        let edges: Vec<(String, String, String)> = parsed.into_iter()
            .filter(|p| p.len() >= 3)
            .map(|p| (p[0].clone(), p[1].clone(), p[2].clone()))
            .collect();

        let res = crate::engine::graph_sat::GraphSatEngine::verify_epistemic_path(
            &edges, requester, target, label, max_depth
        );
        serde_json::to_string_pretty(&res)
            .map_err(|e| PyRuntimeError::new_err(format!("serialize error: {}", e)))
    }
}

#[pymodule]
fn cleavedb3_storage(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CleaveDB>()?;
    Ok(())
}
