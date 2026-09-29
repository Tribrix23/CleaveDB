use std::sync::Arc;
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use crate::error::StorageResult;
use crate::page::{PageId, PageType};
use crate::buffer_pool::BufferPool;
use super::BTree;

/// A cursor for iterating over B+Tree entries in sorted order.
pub struct Cursor {
    pool: Arc<BufferPool>,
    file_path: PathBuf,
    current_page_id: Option<PageId>,
    current_index: usize,
}

impl Cursor {
    /// Create a cursor pointing to the first (smallest) key in the tree.
    /// Traverses the left-most children from root to leaf.
    pub fn new(tree: &BTree) -> StorageResult<Self> {
        let root_id = tree.root_page_id.load(Ordering::SeqCst);

        let mut curr_page_id = root_id;
        loop {
            let frame = tree.pool.fetch(&tree.file_path, curr_page_id)?;
            let guard = frame.read();
            let page = guard.as_ref().unwrap();

            if page.page_type() == PageType::Leaf {
                // If leaf is empty, no entries to iterate
                if page.n_entries() == 0 {
                    return Ok(Cursor {
                        pool: tree.pool.clone(),
                        file_path: tree.file_path.clone(),
                        current_page_id: None,
                        current_index: 0,
                    });
                }
                return Ok(Cursor {
                    pool: tree.pool.clone(),
                    file_path: tree.file_path.clone(),
                    current_page_id: Some(curr_page_id),
                    current_index: 0,
                });
            } else if page.page_type() == PageType::Internal {
                if page.n_entries() == 0 {
                    return Ok(Cursor {
                        pool: tree.pool.clone(),
                        file_path: tree.file_path.clone(),
                        current_page_id: None,
                        current_index: 0,
                    });
                }
                curr_page_id = page.get_child_at(0);
            } else {
                return Ok(Cursor {
                    pool: tree.pool.clone(),
                    file_path: tree.file_path.clone(),
                    current_page_id: None,
                    current_index: 0,
                });
            }
        }
    }

    /// Traverse to the leaf containing `key` (or where it would be).
    /// Sets `current_index` to the exact index (using `page.search_index`).
    pub fn seek(tree: &BTree, key: &[u8]) -> StorageResult<Self> {
        let root_id = tree.root_page_id.load(Ordering::SeqCst);

        let mut curr_page_id = root_id;
        loop {
            let frame = tree.pool.fetch(&tree.file_path, curr_page_id)?;
            let guard = frame.read();
            let page = guard.as_ref().unwrap();

            if page.page_type() == PageType::Leaf {
                let idx = match page.search_index(key) {
                    Ok(i) => i,
                    Err(i) => i,
                };
                return Ok(Cursor {
                    pool: tree.pool.clone(),
                    file_path: tree.file_path.clone(),
                    current_page_id: Some(curr_page_id),
                    current_index: idx,
                });
            } else if page.page_type() == PageType::Internal {
                curr_page_id = page.search_child(key);
            } else {
                return Ok(Cursor {
                    pool: tree.pool.clone(),
                    file_path: tree.file_path.clone(),
                    current_page_id: None,
                    current_index: 0,
                });
            }
        }
    }

    pub fn next(&mut self) -> StorageResult<Option<(Vec<u8>, Vec<u8>)>> {
        loop {
            let page_id = match self.current_page_id {
                Some(id) => id,
                None => return Ok(None),
            };

            let frame = self.pool.fetch(&self.file_path, page_id)?;
            let guard = frame.read();
            let page = guard.as_ref().unwrap();

            if self.current_index < page.n_entries() as usize {
                if let Some((k, v)) = page.get_at(self.current_index) {
                    self.current_index += 1;
                    return Ok(Some((k.to_vec(), v.to_vec())));
                } else {
                    self.current_index += 1;
                    continue;
                }
            } else {
                let right = page.right_sibling();
                if right == 0 {
                    self.current_page_id = None;
                    return Ok(None);
                } else {
                    self.current_page_id = Some(right);
                    self.current_index = 0;
                    // Loop around to read from the next page
                }
            }
        }
    }
}
