use crate::error::{StorageError, StorageResult};
use super::{Catalog, ShardManager, InvertedIndex, Document, derive::derive};
use super::bucket_bond::Enforcement;
use super::phantom_lattice::{PhantomLattice, ShadowRecord};
use super::dbsp::DifferentialCircuit;
use super::branch::BranchManager;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

/// High-level Database coordinating shards, catalogs, indexes, Phantom Lattice, DBSP, and Speculative Branches.
pub struct Database {
    pub catalog: Catalog,
    pub shards: ShardManager,
    pub inverted: InvertedIndex,
    pub phantom_lattice: Arc<PhantomLattice>,
    pub dbsp: Arc<DifferentialCircuit>,
    pub branches: Arc<BranchManager>,
}

impl Database {
    pub fn put(&self, doc: Document) -> StorageResult<()> {
        let current_ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        // 1. Derive indexable fields
        let derivation = derive(&doc.body);
        
        // 2. Validate bonds — check targets and latch unmaterialized targets into Phantom Lattice
        let trie = self.catalog.to_trie();
        for bond_gid in &derivation.bond_edges {
            let bonds = trie.get_bonds_for_bucket(&doc.bucket);
            for bond in &bonds {
                let target_shard = self.shards.get_shard(bond_gid);
                let target_exists = target_shard.get(bond_gid.as_bytes())?.is_some();

                match bond.enforcement {
                    Enforcement::Strict => {
                        // Strict bond: target MUST exist — reject write if missing
                        if !target_exists {
                            return Err(StorageError::Corruption(
                                format!("Strict bond '{}' violated: target '{}' does not exist", bond.name, bond_gid)
                            ));
                        }
                    }
                    Enforcement::Firm => {
                        if !target_exists {
                            // Firm bond: target has not arrived yet — latch into Phantom Lattice with 24-hr default lease
                            let lease_secs = bond.to_bucket.parse::<u64>().ok().unwrap_or(86400);
                            let shadow = ShadowRecord {
                                src_gid: doc.gid.clone(),
                                target_gid: bond_gid.clone(),
                                rel_name: bond.name.clone(),
                                enforcement: Enforcement::Firm,
                                created_at_ts: current_ts,
                                lease_expiry_ts: Some(current_ts + lease_secs),
                                cascade_delete: bond.cascade_delete,
                                status: "latched".to_string(),
                            };
                            self.phantom_lattice.register_shadow_bond(shadow)?;
                            log::info!("Late-binding Firm bond '{}': latched target '{}' into Phantom Lattice (pending arrival)", bond.name, bond_gid);
                        }
                    }
                    Enforcement::Soft => {
                        if !target_exists {
                            // Soft bond: latch into Phantom Lattice without mandatory lease expiration
                            let shadow = ShadowRecord {
                                src_gid: doc.gid.clone(),
                                target_gid: bond_gid.clone(),
                                rel_name: bond.name.clone(),
                                enforcement: Enforcement::Soft,
                                created_at_ts: current_ts,
                                lease_expiry_ts: None,
                                cascade_delete: bond.cascade_delete,
                                status: "latched".to_string(),
                            };
                            self.phantom_lattice.register_shadow_bond(shadow)?;
                            log::info!("Late-binding Soft bond '{}': latched target '{}' into Phantom Lattice", bond.name, bond_gid);
                        }
                    }
                }
            }
        }
        
        // 3. Serialize
        let msgpack = doc.to_msgpack()?;
        
        // 4. Store in shard (B+Tree + WAL)
        let shard = self.shards.get_shard(&doc.gid);
        let key = doc.gid.as_bytes();
        shard.insert(key, &msgpack)?;
        
        // 5. Cleave-Snap Reactive Latching:
        // Check if other documents were waiting for this document to land!
        if self.phantom_lattice.has_pending_latches(&doc.gid) {
            let snapped = self.phantom_lattice.resolve_latches_for_target(&doc.gid);
            for rec in &snapped {
                log::info!(
                    "Cleave-Snap: Bond '{}' between source '{}' and target '{}' atomically snapped & fused",
                    rec.rel_name, rec.src_gid, rec.target_gid
                );
            }
        }

        // 6. Update inverted index
        for (term, freq) in derivation.text_terms {
            self.inverted.insert(&term, &doc.gid, freq)?;
        }
        
        Ok(())
    }
    
    pub fn get(&self, gid: &str) -> StorageResult<Option<Document>> {
        let shard = self.shards.get_shard(gid);
        if let Some(data) = shard.get(gid.as_bytes())? {
            let doc = Document::from_msgpack(&data)?;
            Ok(Some(doc))
        } else {
            Ok(None)
        }
    }
    
    pub fn delete(&self, gid: &str) -> StorageResult<bool> {
        // 1. Fetch the document first so we can clean up indexes
        let doc = match self.get(gid)? {
            Some(d) => d,
            None => return Ok(false),
        };

        // 2. Check bonds — if any Strict bond points TO this doc with Restrict on-delete, block
        let trie = self.catalog.to_trie();
        let bonds = trie.get_bonds_for_bucket(&doc.bucket);
        let _cascade_targets: Vec<String> = Vec::new();

        for bond in &bonds {
            if bond.to_bucket == doc.bucket && bond.cascade_delete {
                // This bond cascades: collect source docs that reference this target
                // In a real implementation we'd scan the bonds-in B+Tree for incoming edges.
                // For now, we note the intent but don't have the edge index to scan.
                log::info!("Bond '{}' cascade_delete: would cascade from '{}'", bond.name, bond.from_bucket);
            }
        }

        // 3. Clean up inverted index entries for this document
        let derivation = derive(&doc.body);
        let terms: Vec<String> = derivation.text_terms.keys().cloned().collect();
        self.inverted.delete_doc(gid, &terms)?;

        // 4. Delete the document from its shard
        let shard = self.shards.get_shard(gid);
        shard.delete(gid.as_bytes())
    }
}
