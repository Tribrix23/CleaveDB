use std::sync::Arc;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use crate::error::{StorageError, StorageResult};
use crate::page::{Page, PageId, PageType, PAGE_SIZE};
use crate::buffer_pool::{BufferPool, PinnedPage};
use crate::wal::WriteAheadLog;

pub mod cursor;
pub mod bulk;

/// Maximum allowed tree depth. Prevents infinite loops on corrupt data (cyclic child pointers).
const MAX_BTREE_DEPTH: usize = 64;

/// The B+Tree core operations
pub struct BTree {
    pub pool: Arc<BufferPool>,
    pub wal: Arc<WriteAheadLog>,
    pub tree_name: String,
    pub file_path: PathBuf,
    pub root_page_id: AtomicU64,
    pub next_page_id: AtomicU64,
}

impl BTree {
    /// Initializes the BTree.
    pub fn new(
        pool: Arc<BufferPool>,
        wal: Arc<WriteAheadLog>,
        tree_name: String,
        file_path: PathBuf,
    ) -> StorageResult<Self> {
        let is_empty = !file_path.exists() || std::fs::metadata(&file_path).map(|m| m.len()).unwrap_or(0) == 0;
        
        let tree = Self {
            pool,
            wal,
            tree_name,
            file_path: file_path.clone(),
            root_page_id: AtomicU64::new(0),
            next_page_id: AtomicU64::new(0),
        };

        if is_empty {
            let root_id = 0;
            tree.next_page_id.store(1, Ordering::SeqCst);
            let pinned = tree.pool.fetch_or_create(&tree.file_path, root_id, PageType::Leaf)?;
            let mut guard = pinned.write();
            let page = guard.as_mut().unwrap();
            page.set_page_type(PageType::Leaf);
            pinned.mark_dirty();
            tree.root_page_id.store(root_id, Ordering::SeqCst);
        } else {
            tree.root_page_id.store(0, Ordering::SeqCst);
            if let Ok(meta) = std::fs::metadata(&file_path) {
                let pages = meta.len() / (PAGE_SIZE as u64);
                tree.next_page_id.store(pages.max(1), Ordering::SeqCst);
            }
        }

        Ok(tree)
    }

    /// Point lookup
    pub fn get(&self, key: &[u8]) -> StorageResult<Option<Vec<u8>>> {
        let mut curr_id = self.root_page_id.load(Ordering::SeqCst);
        let mut depth = 0;
        
        loop {
            if depth >= MAX_BTREE_DEPTH {
                return Err(StorageError::Corruption("B+Tree depth exceeds maximum — possible cycle in child pointers".into()));
            }
            let pinned = self.pool.fetch(&self.file_path, curr_id)?;
            let guard = pinned.read();
            let page = guard.as_ref().unwrap();
            
            if page.page_type() == PageType::Leaf {
                return Ok(page.get(key).map(|v| v.to_vec()));
            } else if page.page_type() == PageType::Internal {
                curr_id = page.search_child(key);
                depth += 1;
            } else {
                return Err(StorageError::Corruption("Invalid page type in traversal".into()));
            }
        }
    }

    /// Inserts a key-value pair into the BTree.
    pub fn insert(&self, key: &[u8], value: &[u8]) -> StorageResult<()> {
        self.wal.log_put(&self.tree_name, key, value)?;
        
        let root_id = self.root_page_id.load(Ordering::SeqCst);
        
        // 1. Traverse down and keep track of path for bottom-up split
        let mut path = Vec::new();
        let mut curr_id = root_id;
        let mut depth = 0;
        
        loop {
            if depth >= MAX_BTREE_DEPTH {
                return Err(StorageError::Corruption("B+Tree depth exceeds maximum during insert".into()));
            }
            let pinned = self.pool.fetch(&self.file_path, curr_id)?;
            let mut guard = pinned.write();
            let page = guard.as_mut().unwrap();
            
            if page.page_type() == PageType::Leaf {
                let res = page.insert(key, value);
                
                if let Err(StorageError::PageFull { .. }) = res {
                    // Time to split
                    let mut right_page = page.split()?;
                    let right_id = self.next_page_id.fetch_add(1, Ordering::SeqCst);
                    
                    let right_pinned = self.pool.fetch_or_create(&self.file_path, right_id, PageType::Leaf)?;
                    let mut right_guard = right_pinned.write();
                    
                    // Insert the key into the appropriate half
                    let mid_key = right_page.get_at(0).map(|(k, _)| k.to_vec()).unwrap_or_default();
                    if key >= mid_key.as_slice() {
                        right_page.insert(key, value)?;
                    } else {
                        page.insert(key, value)?;
                    }
                    
                    right_page.set_page_id(right_id);
                    *right_guard.as_mut().unwrap() = right_page;
                    
                    page.set_right_sibling(right_id);
                    
                    pinned.mark_dirty();
                    right_pinned.mark_dirty();
                    
                    // Drop locks before bubbling up
                    drop(guard);
                    drop(right_guard);
                    
                    self.insert_into_parent(&mut path, &mid_key, right_id)?;
                    return Ok(());
                } else {
                    res?;
                    pinned.mark_dirty();
                    return Ok(());
                }
            } else {
                let next_id = page.search_child(key);
                drop(guard);
                path.push((curr_id, pinned));
                curr_id = next_id;
                depth += 1;
            }
        }
    }
    
    fn insert_into_parent(&self, path: &mut Vec<(PageId, PinnedPage<'_>)>, key: &[u8], child_id: u64) -> StorageResult<()> {
        if path.is_empty() {
            // Need a new root
            let left_id = self.root_page_id.load(Ordering::SeqCst);
            let new_root_id = self.next_page_id.fetch_add(1, Ordering::SeqCst);
            
            let pinned = self.pool.fetch_or_create(&self.file_path, new_root_id, PageType::Internal)?;
            let mut guard = pinned.write();
            let page = guard.as_mut().unwrap();
            page.set_page_type(PageType::Internal);
            page.set_page_id(new_root_id);
            
            // Insert empty key for left child
            page.insert_internal(&[], left_id)?;
            // Insert split key for right child
            page.insert_internal(key, child_id)?;
            
            pinned.mark_dirty();
            self.root_page_id.store(new_root_id, Ordering::SeqCst);
            return Ok(());
        }
        
        let (_parent_id, pinned_parent) = path.pop().unwrap();
        let mut guard = pinned_parent.write();
        let parent = guard.as_mut().unwrap();
        
        if let Err(StorageError::PageFull { .. }) = parent.insert_internal(key, child_id) {
            let mut right_page = parent.split()?;
            let right_id = self.next_page_id.fetch_add(1, Ordering::SeqCst);
            
            let right_pinned = self.pool.fetch_or_create(&self.file_path, right_id, PageType::Internal)?;
            let mut right_guard = right_pinned.write();
            
            let mid_key = right_page.get_at(0).map(|(k, _)| k.to_vec()).unwrap_or_default();
            
            if key >= mid_key.as_slice() {
                right_page.insert_internal(key, child_id)?;
            } else {
                parent.insert_internal(key, child_id)?;
            }
            
            right_page.set_page_id(right_id);
            *right_guard.as_mut().unwrap() = right_page;
            
            pinned_parent.mark_dirty();
            right_pinned.mark_dirty();
            
            drop(guard);
            drop(right_guard);
            
            self.insert_into_parent(path, &mid_key, right_id)?;
        } else {
            pinned_parent.mark_dirty();
        }
        Ok(())
    }

    /// Point delete
    pub fn delete(&self, key: &[u8]) -> StorageResult<bool> {
        self.wal.log_delete(&self.tree_name, key)?;
        
        let mut curr_id = self.root_page_id.load(Ordering::SeqCst);
        let mut depth = 0;
        
        loop {
            if depth >= MAX_BTREE_DEPTH {
                return Err(StorageError::Corruption("B+Tree depth exceeds maximum during delete".into()));
            }
            let pinned = self.pool.fetch(&self.file_path, curr_id)?;
            let mut guard = pinned.write();
            let page = guard.as_mut().unwrap();
            
            if page.page_type() == PageType::Leaf {
                let deleted = page.delete(key);
                if deleted {
                    pinned.mark_dirty();
                }
                return Ok(deleted);
            } else {
                let next_id = page.search_child(key);
                curr_id = next_id;
                depth += 1;
            }
        }
    }
}
