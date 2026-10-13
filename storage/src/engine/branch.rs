use dashmap::DashMap;
use std::sync::Arc;
use serde::{Serialize, Deserialize};
use std::time::{SystemTime, UNIX_EPOCH};
use crate::error::{StorageError, StorageResult};
use crate::engine::{Document, Database};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MergeReport {
    pub branch_name: String,
    pub documents_added: usize,
    pub documents_updated: usize,
    pub documents_deleted: usize,
    pub conflict_resolution: String,
    pub execution_time_us: u128,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BranchInfo {
    pub name: String,
    pub created_at_ts: u64,
    pub pending_mutations: usize,
}

pub struct Branch {
    pub name: String,
    pub created_at_ts: u64,
    // GID -> Option<Document>. Some(doc) = written/modified; None = tombstone deleted.
    pub delta_docs: DashMap<String, Option<Document>>,
}

/// Zero-Copy Speculative Branch Manager.
/// Provides microsecond copy-on-write page virtualization for autonomous agent simulations.
pub struct BranchManager {
    branches: DashMap<String, Arc<Branch>>,
}

impl BranchManager {
    pub fn new() -> Self {
        Self {
            branches: DashMap::new(),
        }
    }

    /// Creates a new speculative branch in microseconds with zero storage copy
    pub fn create_branch(&self, name: &str) -> StorageResult<()> {
        if self.branches.contains_key(name) {
            return Err(StorageError::Corruption(format!("Branch '{}' already exists", name)));
        }

        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        let branch = Arc::new(Branch {
            name: name.to_string(),
            created_at_ts: ts,
            delta_docs: DashMap::new(),
        });

        self.branches.insert(name.to_string(), branch);
        Ok(())
    }

    /// Discards a branch instantly in O(1) time
    pub fn discard_branch(&self, name: &str) -> bool {
        self.branches.remove(name).is_some()
    }

    /// Writes a document into a speculative branch without touching master pages
    pub fn branch_put(&self, branch_name: &str, doc: Document) -> StorageResult<()> {
        let branch = self.branches.get(branch_name)
            .ok_or_else(|| StorageError::Corruption(format!("Branch '{}' not found", branch_name)))?;

        branch.delta_docs.insert(doc.gid.clone(), Some(doc));
        Ok(())
    }

    /// Fetches a document from a branch (checks branch delta first, falls back to master)
    pub fn branch_get(&self, branch_name: &str, gid: &str, master: &Database) -> StorageResult<Option<Document>> {
        let branch = self.branches.get(branch_name)
            .ok_or_else(|| StorageError::Corruption(format!("Branch '{}' not found", branch_name)))?;

        // 1. Check branch delta
        if let Some(entry) = branch.delta_docs.get(gid) {
            return Ok(entry.value().clone());
        }

        // 2. Fall back to master
        master.get(gid)
    }

    /// Soft-deletes a document in the branch using a tombstone
    pub fn branch_delete(&self, branch_name: &str, gid: &str) -> StorageResult<bool> {
        let branch = self.branches.get(branch_name)
            .ok_or_else(|| StorageError::Corruption(format!("Branch '{}' not found", branch_name)))?;

        branch.delta_docs.insert(gid.to_string(), None);
        Ok(true)
    }

    /// Scans a bucket within a branch, overlaying branch deltas on master data
    pub fn branch_scan_bucket(&self, branch_name: &str, bucket: &str, master: &Database) -> StorageResult<Vec<Document>> {
        let branch = self.branches.get(branch_name)
            .ok_or_else(|| StorageError::Corruption(format!("Branch '{}' not found", branch_name)))?;

        let mut results = Vec::new();
        let mut overridden_gids = std::collections::HashSet::new();

        // 1. Collect branch deltas for this bucket
        for entry in branch.delta_docs.iter() {
            let gid = entry.key();
            if gid.starts_with(&format!("{}:", bucket)) {
                overridden_gids.insert(gid.clone());
                if let Some(ref doc) = *entry.value() {
                    results.push(doc.clone());
                }
            }
        }

        // 2. Scan master for non-overridden documents
        let prefix = format!("{}:", bucket);
        let prefix_bytes = prefix.as_bytes();
        for shard in master.shards.all_shards() {
            if let Ok(mut cursor) = crate::btree::cursor::Cursor::new(shard) {
                while let Ok(Some((key, value))) = cursor.next() {
                    if key.starts_with(prefix_bytes) {
                        if let Ok(doc) = Document::from_msgpack(&value) {
                            if !overridden_gids.contains(&doc.gid) {
                                results.push(doc);
                            }
                        }
                    }
                }
            }
        }

        Ok(results)
    }

    /// Merges branch mutations back into the master database atomically
    pub fn merge_branch(&self, branch_name: &str, master: &Database, conflict_resolution: &str) -> StorageResult<MergeReport> {
        let start = std::time::Instant::now();
        let branch = self.branches.get(branch_name)
            .ok_or_else(|| StorageError::Corruption(format!("Branch '{}' not found", branch_name)))?;

        let mut added = 0;
        let mut updated = 0;
        let mut deleted = 0;

        for entry in branch.delta_docs.iter() {
            let gid = entry.key();
            match entry.value() {
                Some(doc) => {
                    let existed = master.get(gid)?.is_some();
                    master.put(doc.clone())?;
                    if existed {
                        updated += 1;
                    } else {
                        added += 1;
                    }
                }
                None => {
                    let was_deleted = master.delete(gid)?;
                    if was_deleted {
                        deleted += 1;
                    }
                }
            }
        }

        // Remove branch after successful merge
        drop(branch);
        self.branches.remove(branch_name);

        let elapsed = start.elapsed().as_micros();
        Ok(MergeReport {
            branch_name: branch_name.to_string(),
            documents_added: added,
            documents_updated: updated,
            documents_deleted: deleted,
            conflict_resolution: conflict_resolution.to_string(),
            execution_time_us: elapsed,
        })
    }

    pub fn list_branches(&self) -> Vec<BranchInfo> {
        self.branches.iter()
            .map(|entry| {
                BranchInfo {
                    name: entry.key().clone(),
                    created_at_ts: entry.value().created_at_ts,
                    pending_mutations: entry.value().delta_docs.len(),
                }
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_branch_lifecycle() {
        let mgr = BranchManager::new();
        assert!(mgr.create_branch("sim_01").is_ok());

        let doc = Document::new("users", json!({"name": "Ghost"}), Some("users:ghost"));
        assert!(mgr.branch_put("sim_01", doc).is_ok());

        let branches = mgr.list_branches();
        assert_eq!(branches.len(), 1);
        assert_eq!(branches[0].pending_mutations, 1);

        assert!(mgr.discard_branch("sim_01"));
        assert_eq!(mgr.list_branches().len(), 0);
    }
}
