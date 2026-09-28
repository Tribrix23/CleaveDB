use std::sync::Arc;
use crate::error::{StorageError, StorageResult};
use crate::buffer_pool::BufferPool;
use crate::wal::WriteAheadLog;
use super::{Catalog, ShardManager, InvertedIndex, Document, derive::derive};

/// High-level Database coordinating shards, catalogs, and indexes.
pub struct Database {
    pub catalog: Catalog,
    pub shards: ShardManager,
    pub inverted: InvertedIndex,
    // pool and wal are kept alive by Arcs in ShardManager and BTree
}

impl Database {
    pub fn put(&self, mut doc: Document) -> StorageResult<()> {
        // 1. Derive indexable fields
        let derivation = derive(&doc.body);
        
        // 2. Validate bonds
        let trie = self.catalog.to_trie();
        // (Bond validation logic omitted for brevity in prototype)
        
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
        let shard = self.shards.get_shard(gid);
        // Cascade delete logic would go here (fetch doc, check bonds, BFS cascade)
        shard.delete(gid.as_bytes())
    }
}
