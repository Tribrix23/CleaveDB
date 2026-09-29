use std::sync::atomic::Ordering;
use crate::error::{StorageError, StorageResult};
use crate::page::PageType;
use crate::btree::BTree;

impl BTree {
    pub fn bulk_load(&self, sorted_iter: impl Iterator<Item = (Vec<u8>, Vec<u8>)>) -> StorageResult<()> {
        let mut leaves: Vec<(Vec<u8>, u64)> = Vec::new(); // (first_key, page_id)
        
        let mut curr_page_id = self.next_page_id.fetch_add(1, Ordering::SeqCst);
        let mut curr_pinned = self.pool.fetch_or_create(&self.file_path, curr_page_id, PageType::Leaf)?;
        let mut curr_guard = curr_pinned.write();
        let mut curr_page = curr_guard.as_mut().unwrap();
        curr_page.set_page_type(PageType::Leaf);
        curr_page.set_page_id(curr_page_id);
        
        let mut first_key_in_page: Option<Vec<u8>> = None;
        let mut any_inserted = false;

        for (key, value) in sorted_iter {
            any_inserted = true;
            if first_key_in_page.is_none() {
                first_key_in_page = Some(key.clone());
            }
            
            let res = curr_page.insert(&key, &value);
            if let Err(StorageError::PageFull { .. }) = res {
                // Page is full. Finalize it.
                leaves.push((first_key_in_page.take().unwrap(), curr_page_id));
                
                let next_page_id = self.next_page_id.fetch_add(1, Ordering::SeqCst);
                curr_page.set_right_sibling(next_page_id);
                curr_pinned.mark_dirty();
                
                // Drop current page locks
                drop(curr_guard);
                
                // Create new page
                curr_page_id = next_page_id;
                curr_pinned = self.pool.fetch_or_create(&self.file_path, curr_page_id, PageType::Leaf)?;
                curr_guard = curr_pinned.write();
                curr_page = curr_guard.as_mut().unwrap();
                curr_page.set_page_type(PageType::Leaf);
                curr_page.set_page_id(curr_page_id);
                
                // Insert the key that didn't fit
                first_key_in_page = Some(key.clone());
                curr_page.insert(&key, &value)?; // Assuming it fits in a completely empty page
            }
        }
        
        if any_inserted {
            // Push the last page
            leaves.push((first_key_in_page.unwrap_or_default(), curr_page_id));
            curr_pinned.mark_dirty();
        } else {
            // No data. Just set root to the empty leaf.
            curr_pinned.mark_dirty();
            self.root_page_id.store(curr_page_id, Ordering::SeqCst);
            return Ok(());
        }
        drop(curr_guard);

        // Now build internal pages level by level
        let mut current_level = leaves;
        
        while current_level.len() > 1 {
            let mut next_level: Vec<(Vec<u8>, u64)> = Vec::new();
            
            let mut curr_page_id = self.next_page_id.fetch_add(1, Ordering::SeqCst);
            let mut curr_pinned = self.pool.fetch_or_create(&self.file_path, curr_page_id, PageType::Internal)?;
            let mut curr_guard = curr_pinned.write();
            let mut curr_page = curr_guard.as_mut().unwrap();
            curr_page.set_page_type(PageType::Internal);
            curr_page.set_page_id(curr_page_id);
            
            let mut first_key_in_page: Option<Vec<u8>> = None;
            let mut is_first_in_page = true;
            
            for (key, child_id) in current_level.into_iter() {
                if first_key_in_page.is_none() {
                    first_key_in_page = Some(key.clone());
                }
                
                let insert_key = if is_first_in_page {
                    &[] // first entry in any internal page must have empty key
                } else {
                    key.as_slice()
                };
                
                let res = curr_page.insert_internal(insert_key, child_id);
                if let Err(StorageError::PageFull { .. }) = res {
                    // Page is full
                    next_level.push((first_key_in_page.take().unwrap(), curr_page_id));
                    curr_pinned.mark_dirty();
                    
                    drop(curr_guard);
                    
                    curr_page_id = self.next_page_id.fetch_add(1, Ordering::SeqCst);
                    curr_pinned = self.pool.fetch_or_create(&self.file_path, curr_page_id, PageType::Internal)?;
                    curr_guard = curr_pinned.write();
                    curr_page = curr_guard.as_mut().unwrap();
                    curr_page.set_page_type(PageType::Internal);
                    curr_page.set_page_id(curr_page_id);
                    
                    first_key_in_page = Some(key.clone());
                    curr_page.insert_internal(&[], child_id)?;
                }
                is_first_in_page = false;
            }
            next_level.push((first_key_in_page.unwrap_or_default(), curr_page_id));
            curr_pinned.mark_dirty();
            drop(curr_guard);
            
            current_level = next_level;
        }
        
        if let Some((_, root_id)) = current_level.into_iter().next() {
            self.root_page_id.store(root_id, Ordering::SeqCst);
        }
        
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use tempfile::tempdir;
    use crate::buffer_pool::BufferPool;
    use crate::wal::{WriteAheadLog, WalConfig, SyncMode};

    #[test]
    fn test_bulk_load() {
        let dir = tempdir().unwrap();
        let db_path = dir.path().join("test.db");
        let wal_dir = dir.path().join("wal");

        let pool = Arc::new(BufferPool::new(100));
        let wal_config = WalConfig {
            dir: wal_dir,
            sync_mode: SyncMode::Sync,
            segment_max_bytes: 1024 * 1024,
            flush_interval_ms: 1000,
        };
        let wal = Arc::new(WriteAheadLog::open(wal_config).unwrap());

        let btree = BTree::new(pool.clone(), wal.clone(), "test_tree".to_string(), db_path.clone()).unwrap();

        let mut data = Vec::new();
        // Insert enough records to cause multiple page splits and build internal nodes
        for i in 0..5000u32 {
            let key = format!("key_{:05}", i).into_bytes();
            // 100 bytes value to ensure we fill pages
            let val = vec![i as u8; 100];
            data.push((key, val));
        }

        // Must be sorted for bulk load
        data.sort_by(|a, b| a.0.cmp(&b.0));

        btree.bulk_load(data.clone().into_iter()).unwrap();

        for (k, expected_v) in data {
            let v = btree.get(&k).unwrap().unwrap();
            assert_eq!(v, expected_v);
        }
    }
}
