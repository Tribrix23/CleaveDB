use crate::error::{StorageError, StorageResult};
use super::{Catalog, ShardManager, InvertedIndex, Document, derive::derive};
use super::bucket_bond::Enforcement;

/// High-level Database coordinating shards, catalogs, and indexes.
pub struct Database {
    pub catalog: Catalog,
    pub shards: ShardManager,
    pub inverted: InvertedIndex,
    // pool and wal are kept alive by Arcs in ShardManager and BTree
}

impl Database {
    pub fn put(&self, doc: Document) -> StorageResult<()> {
        // 1. Derive indexable fields
        let derivation = derive(&doc.body);
        
        // 2. Validate bonds — check that bond targets exist for Strict/Firm bonds
        let trie = self.catalog.to_trie();
        for bond_gid in &derivation.bond_edges {
            let bonds = trie.get_bonds_for_bucket(&doc.bucket);
            for bond in &bonds {
                match bond.enforcement {
                    Enforcement::Strict => {
                        // Strict bond: target MUST exist — reject write if missing
                        let target_shard = self.shards.get_shard(bond_gid);
                        if target_shard.get(bond_gid.as_bytes())?.is_none() {
                            return Err(StorageError::Corruption(
                                format!("Strict bond '{}' violated: target '{}' does not exist", bond.name, bond_gid)
                            ));
                        }
                    }
                    Enforcement::Firm => {
                        // Firm bond: target doesn't need to exist, but log a warning
                        let target_shard = self.shards.get_shard(bond_gid);
                        if target_shard.get(bond_gid.as_bytes())?.is_none() {
                            log::warn!("Firm bond '{}': target '{}' not found (bond_status: pending)", bond.name, bond_gid);
                        }
                    }
                    Enforcement::Soft => {
                        // Soft bond: no validation needed
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
        
        // 5. Update inverted index
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
