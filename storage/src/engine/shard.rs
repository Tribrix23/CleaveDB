use std::sync::Arc;
use xxhash_rust::xxh3::xxh3_64;
use crate::error::StorageResult;
use crate::btree::BTree;
use crate::buffer_pool::BufferPool;
use crate::wal::WriteAheadLog;
use std::path::PathBuf;

/// Manages multiple shards (B+Trees) for document storage.
pub struct ShardManager {
    shards: Vec<BTree>,
    num_shards: usize,
}

impl ShardManager {
    pub fn new(
        num_shards: usize,
        pool: Arc<BufferPool>,
        wal: Arc<WriteAheadLog>,
        base_path: &std::path::Path,
    ) -> StorageResult<Self> {
        let mut shards = Vec::with_capacity(num_shards);
        for i in 0..num_shards {
            let tree_name = format!("shard_{}", i);
            let mut path = PathBuf::from(base_path);
            path.push(format!("{}.db", tree_name));
            
            let btree = BTree::new(pool.clone(), wal.clone(), tree_name, path)?;
            shards.push(btree);
        }
        
        Ok(Self { shards, num_shards })
    }

    /// Determines which shard a given Global ID (gid) belongs to using consistent hashing.
    pub fn get_shard_index(&self, gid: &str) -> usize {
        let hash = xxh3_64(gid.as_bytes());
        (hash % (self.num_shards as u64)) as usize
    }

    /// Gets the B+Tree instance for the given GID.
    pub fn get_shard(&self, gid: &str) -> &BTree {
        &self.shards[self.get_shard_index(gid)]
    }
    
    /// Iterates over all shards.
    pub fn all_shards(&self) -> &[BTree] {
        &self.shards
    }
}
