//! # CleaveDB3 Storage Engine
//!
//! A custom storage engine built from scratch — no SQLite, no external databases.
//!
//! ## Components
//!
//! - **Page**: 16KB fixed-size pages with checksums and LZ4 compression
//! - **BufferPool**: CLOCK-sweep page cache with pin/unpin semantics
//! - **WAL**: Write-ahead log with leader-follower group commit
//! - **BPlusTree**: Persistent B+Tree for documents, indexes, and bond edges
//!
//! ## Safety
//!
//! All code is safe Rust unless explicitly marked unsafe (with documented justification).
//! The buffer pool uses `Arc` and `parking_lot` locks for thread safety.
//! The WAL uses `crossbeam::queue::SegQueue` for lock-free group commit.

pub mod error;
pub mod page;
pub mod buffer_pool;
pub mod crypto;
pub mod wal;
pub mod btree;
pub mod bloom;
pub mod simd_ffi;
pub mod engine;
pub mod python;
pub mod coordinator_ffi;

// Re-export key types
pub use error::{StorageError, StorageResult};
pub use page::{Page, PageId, PageType, PAGE_SIZE};
pub use buffer_pool::{BufferPool, PinnedPage};
pub use wal::{WriteAheadLog, WalConfig, SyncMode};
pub use btree::BTree;
pub use btree::cursor::Cursor;
pub use simd_ffi::{dot_product, softmax, gelu, layer_norm, matmul};

