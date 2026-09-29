use std::fs::OpenOptions;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;

use dashmap::DashMap;
use log::{debug, warn};
use parking_lot::{RwLock, RwLockReadGuard, RwLockWriteGuard};

use crate::error::{StorageError, StorageResult};
use crate::page::{Page, PageId, PageType, PAGE_SIZE};

/// Statistics for the Buffer Pool.
#[derive(Debug, Clone, Copy)]
pub struct BufferPoolStats {
    pub capacity: usize,
    pub in_use: usize,
    pub dirty_count: usize,
    pub pinned_count: usize,
}

/// A frame holding a single page in memory, along with metadata for the CLOCK-sweep algorithm.
pub struct PageFrame {
    data: RwLock<Option<Page>>,
    file_path: RwLock<Option<PathBuf>>,
    page_id: AtomicU64,
    referenced: AtomicBool,
    pin_count: AtomicI32,
    dirty: AtomicBool,
    page_lsn: AtomicU64,
}

impl PageFrame {
    fn new() -> Self {
        Self {
            data: RwLock::new(None),
            file_path: RwLock::new(None),
            page_id: AtomicU64::new(0),
            referenced: AtomicBool::new(false),
            pin_count: AtomicI32::new(0),
            dirty: AtomicBool::new(false),
            page_lsn: AtomicU64::new(0),
        }
    }
}

/// An RAII guard for a pinned page. When dropped, decrements the pin count.
pub struct PinnedPage<'a> {
    pool: &'a BufferPool,
    frame_idx: usize,
}

impl<'a> PinnedPage<'a> {
    /// Read access to the page data.
    pub fn read(&self) -> RwLockReadGuard<'_, Option<Page>> {
        self.pool.frames[self.frame_idx].data.read()
    }

    /// Write access to the page data. Automatically marks the page as dirty.
    pub fn write(&self) -> RwLockWriteGuard<'_, Option<Page>> {
        self.mark_dirty();
        self.pool.frames[self.frame_idx].data.write()
    }

    /// Manually mark the page as dirty.
    pub fn mark_dirty(&self) {
        self.pool.frames[self.frame_idx]
            .dirty
            .store(true, Ordering::Release);
    }
}

impl<'a> Drop for PinnedPage<'a> {
    fn drop(&mut self) {
        self.pool.frames[self.frame_idx]
            .pin_count
            .fetch_sub(1, Ordering::SeqCst);
    }
}

/// The CLOCK-sweep buffer pool.
pub struct BufferPool {
    capacity: usize,
    frames: Vec<PageFrame>,
    page_table: DashMap<(PathBuf, PageId), usize>,
    clock_hand: AtomicUsize,
    frame_count: AtomicUsize,
}

impl BufferPool {
    /// Creates a new buffer pool with the given capacity.
    pub fn new(capacity: usize) -> Self {
        let mut frames = Vec::with_capacity(capacity);
        for _ in 0..capacity {
            frames.push(PageFrame::new());
        }

        Self {
            capacity,
            frames,
            page_table: DashMap::new(),
            clock_hand: AtomicUsize::new(0),
            frame_count: AtomicUsize::new(0),
        }
    }

    /// Fetches a page from the buffer pool or loads it from disk if not present.
    pub fn fetch(&self, file_path: &Path, page_id: PageId) -> StorageResult<PinnedPage> {
        let key = (file_path.to_path_buf(), page_id);
        
        // Check if page is already in the pool
        if let Some(frame_ref) = self.page_table.get(&key) {
            let frame_idx = *frame_ref;
            let frame = &self.frames[frame_idx];
            
            // Pin the page and mark it as referenced for the CLOCK algorithm
            frame.pin_count.fetch_add(1, Ordering::SeqCst);
            frame.referenced.store(true, Ordering::Release);
            
            return Ok(PinnedPage {
                pool: self,
                frame_idx,
            });
        }

        // Page not in pool, load from disk
        self.load_from_disk(file_path, page_id, None)
    }

    /// Fetches a page from the buffer pool, or creates a new one if it doesn't exist on disk.
    pub fn fetch_or_create(&self, file_path: &Path, page_id: PageId, page_type: PageType) -> StorageResult<PinnedPage> {
        let key = (file_path.to_path_buf(), page_id);
        
        if let Some(frame_ref) = self.page_table.get(&key) {
            let frame_idx = *frame_ref;
            let frame = &self.frames[frame_idx];
            
            frame.pin_count.fetch_add(1, Ordering::SeqCst);
            frame.referenced.store(true, Ordering::Release);
            
            return Ok(PinnedPage {
                pool: self,
                frame_idx,
            });
        }

        self.load_from_disk(file_path, page_id, Some(page_type))
    }

    /// Internal method to load a page from disk or initialize it if it's new.
    fn load_from_disk(&self, file_path: &Path, page_id: PageId, create_type: Option<PageType>) -> StorageResult<PinnedPage> {
        // We might have multiple threads trying to load the same page. 
        // This simple implementation might load it multiple times or race,
        // but DashMap insertions will resolve it. For production, we'd use a load latch.
        
        let frame_idx = self.find_victim()?;
        let frame = &self.frames[frame_idx];
        
        // Evict previous contents
        self.evict(frame_idx)?;

        let page = match create_type {
            Some(ptype) => {
                // creating a new page
                Page::new(page_id, ptype)
            }
            None => {
                // reading from disk
                read_page_from_file(file_path, page_id)?
            }
        };

        // Pin it before making it visible
        frame.pin_count.store(1, Ordering::SeqCst);
        frame.referenced.store(true, Ordering::Release);
        frame.page_id.store(page_id, Ordering::Release);
        frame.dirty.store(create_type.is_some(), Ordering::Release);
        *frame.file_path.write() = Some(file_path.to_path_buf());
        *frame.data.write() = Some(page);

        // Update page table
        let key = (file_path.to_path_buf(), page_id);
        self.page_table.insert(key, frame_idx);
        
        // Increment frame count if it wasn't already at capacity (we just replaced an empty frame)
        // Note: frame_count might drift slightly with this simple approach in highly concurrent loads,
        // but it suffices for stats.
        let mut current_count = self.frame_count.load(Ordering::Relaxed);
        while current_count < self.capacity {
            if self.frame_count.compare_exchange_weak(current_count, current_count + 1, Ordering::SeqCst, Ordering::Relaxed).is_ok() {
                break;
            }
            current_count = self.frame_count.load(Ordering::Relaxed);
        }

        Ok(PinnedPage {
            pool: self,
            frame_idx,
        })
    }

    /// Finds a suitable victim frame using the CLOCK-sweep algorithm.
    fn find_victim(&self) -> StorageResult<usize> {
        let max_iterations = self.capacity * 2;
        let mut iterations = 0;

        while iterations < max_iterations {
            let current = self.clock_hand.fetch_add(1, Ordering::SeqCst) % self.capacity;
            let frame = &self.frames[current];

            if frame.pin_count.load(Ordering::SeqCst) == 0 {
                if frame.referenced.load(Ordering::Acquire) {
                    // Give it a second chance
                    frame.referenced.store(false, Ordering::Release);
                } else {
                    // Found a victim
                    return Ok(current);
                }
            }

            iterations += 1;
        }

        Err(StorageError::BufferPoolExhausted {
            capacity: self.capacity,
            pinned: self.capacity,
        })
    }

    /// Evicts the page in the given frame, flushing it if dirty.
    pub fn evict(&self, frame_idx: usize) -> StorageResult<()> {
        let frame = &self.frames[frame_idx];
        
        if frame.pin_count.load(Ordering::SeqCst) > 0 {
            return Err(StorageError::PagePinned); // Should not happen internally if find_victim works correctly
        }

        if frame.dirty.load(Ordering::Acquire) {
            self.flush_page(frame_idx)?;
        }

        // Remove from page table
        if let Some(path) = frame.file_path.read().as_ref() {
            let page_id = frame.page_id.load(Ordering::Acquire);
            self.page_table.remove(&(path.clone(), page_id));
        }

        // Clear frame
        *frame.data.write() = None;
        *frame.file_path.write() = None;
        frame.dirty.store(false, Ordering::Release);
        frame.referenced.store(false, Ordering::Release);
        
        Ok(())
    }

    /// Flushes a specific frame to disk.
    pub fn flush_page(&self, frame_idx: usize) -> StorageResult<()> {
        let frame = &self.frames[frame_idx];
        
        if let Some(path) = frame.file_path.read().as_ref() {
            if let Some(page) = frame.data.read().as_ref() {
                let page_id = frame.page_id.load(Ordering::Acquire);
                write_page_to_file(path, page_id, page)?;
                frame.dirty.store(false, Ordering::Release);
            }
        }
        
        Ok(())
    }

    /// Flushes all dirty pages to disk.
    pub fn flush_all(&self) -> StorageResult<()> {
        for i in 0..self.capacity {
            let frame = &self.frames[i];
            if frame.dirty.load(Ordering::Acquire) {
                self.flush_page(i)?;
            }
        }
        Ok(())
    }

    /// Returns statistics about the buffer pool.
    pub fn stats(&self) -> BufferPoolStats {
        let mut in_use = 0;
        let mut dirty_count = 0;
        let mut pinned_count = 0;

        for frame in &self.frames {
            if frame.data.read().is_some() {
                in_use += 1;
                if frame.dirty.load(Ordering::Acquire) {
                    dirty_count += 1;
                }
                if frame.pin_count.load(Ordering::SeqCst) > 0 {
                    pinned_count += 1;
                }
            }
        }

        BufferPoolStats {
            capacity: self.capacity,
            in_use,
            dirty_count,
            pinned_count,
        }
    }
}

// ----------------------------------------------------------------------------
// File I/O Helpers
// ----------------------------------------------------------------------------

fn read_page_from_file(file_path: &Path, page_id: PageId) -> StorageResult<Page> {
    let mut file = OpenOptions::new()
        .read(true)
        .open(file_path)
        .map_err(|e| StorageError::Io(e))?;

    let enc_size = PAGE_SIZE + crate::crypto::OVERHEAD;
    let offset = (page_id as u64) * (enc_size as u64);
    file.seek(SeekFrom::Start(offset))
        .map_err(|e| StorageError::Io(e))?;

    let mut enc_buf = vec![0u8; enc_size];
    file.read_exact(&mut enc_buf)
        .map_err(|e| StorageError::Io(e))?;

    let decrypted = crate::crypto::decrypt_data(&enc_buf);
    let mut buf = [0u8; PAGE_SIZE];
    buf.copy_from_slice(&decrypted);

    Page::from_bytes(buf)
}

fn write_page_to_file(file_path: &Path, page_id: PageId, page: &Page) -> StorageResult<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create(true)
        .open(file_path)
        .map_err(|e| StorageError::Io(e))?;

    let enc_size = PAGE_SIZE + crate::crypto::OVERHEAD;
    let offset = (page_id as u64) * (enc_size as u64);
    file.seek(SeekFrom::Start(offset))
        .map_err(|e| StorageError::Io(e))?;

    let encrypted = crate::crypto::encrypt_data(page.to_bytes());
    file.write_all(&encrypted)
        .map_err(|e| StorageError::Io(e))?;

    Ok(())
}


// ----------------------------------------------------------------------------
// Tests
// ----------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;
    use std::sync::Arc;
    use std::thread;

    // Helper to setup mock types if needed, but we rely on crate types.
    // In a real crate, Page and StorageError would be defined in crate::page/error.

    #[test]
    fn test_buffer_pool_basic() {
        let pool = BufferPool::new(8);
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.db");

        // We can't really run `fetch` without `read_page_from_file` succeeding.
        // But `fetch_or_create` will skip reading from disk if we pass a type!
        
        let mut pinned_pages = Vec::new();
        for i in 0..4 {
            let p = pool.fetch_or_create(&file_path, i as PageId, PageType::Leaf).unwrap();
            pinned_pages.push(p);
        }

        let stats = pool.stats();
        assert_eq!(stats.in_use, 4);
        assert_eq!(stats.pinned_count, 4);
    }

    #[test]
    fn test_buffer_pool_eviction() {
        let pool = BufferPool::new(2);
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.db");

        // Create 2 pages
        let p1 = pool.fetch_or_create(&file_path, 1, PageType::Leaf).unwrap();
        let p2 = pool.fetch_or_create(&file_path, 2, PageType::Leaf).unwrap();
        
        assert_eq!(pool.stats().in_use, 2);

        // Try to fetch a 3rd page - should fail since both are pinned
        let res = pool.fetch_or_create(&file_path, 3, PageType::Leaf);
        assert!(res.is_err());

        // Drop p1 to unpin it
        drop(p1);

        // Now we should be able to fetch p3 (evicts p1)
        let p3 = pool.fetch_or_create(&file_path, 3, PageType::Leaf).unwrap();
        assert_eq!(pool.stats().in_use, 2);
    }

    #[test]
    fn test_dirty_page_flush() {
        let pool = BufferPool::new(2);
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test2.db");

        {
            let p1 = pool.fetch_or_create(&file_path, 1, PageType::Leaf).unwrap();
            p1.mark_dirty();
        }

        assert_eq!(pool.stats().dirty_count, 1);
        pool.flush_all().unwrap();
        assert_eq!(pool.stats().dirty_count, 0);
    }

    #[test]
    fn test_concurrent_access() {
        let pool = Arc::new(BufferPool::new(8));
        let dir = tempdir().unwrap();
        let file_path = Arc::new(dir.path().join("test3.db"));

        let mut handles = vec![];
        for i in 0..4 {
            let pool_clone = pool.clone();
            let path_clone = file_path.clone();
            handles.push(thread::spawn(move || {
                let _p = pool_clone.fetch_or_create(&path_clone, i as PageId, PageType::Leaf).unwrap();
            }));
        }

        for h in handles {
            h.join().unwrap();
        }

        let stats = pool.stats();
        assert_eq!(stats.in_use, 4);
    }
}
