//! Error types for the CleaveDB3 storage engine.
//!
//! All errors are non-panicking. The engine never calls `unwrap()` on fallible
//! operations in production paths — every error is propagated via `Result`.

use std::fmt;
use std::io;

/// All possible storage engine errors.
#[derive(Debug)]
pub enum StorageError {
    /// I/O error from the filesystem (disk full, permission denied, etc.)
    Io(io::Error),

    /// Page magic number doesn't match — not a CleaveDB3 page.
    InvalidPageMagic,

    /// Page is currently pinned and cannot be evicted.
    PagePinned,

    /// Data corruption detected (WAL, index, or page).
    Corruption(String),

    /// Page checksum mismatch — data corruption detected.
    /// The page is NOT applied; the WAL can replay to recover.
    ChecksumMismatch {
        page_id: u64,
        expected: u32,
        actual: u32,
    },

    /// Page is full and cannot accept more entries.
    PageFull {
        page_id: u64,
        capacity: usize,
        requested: usize,
    },

    /// Key is too large for the configured maximum.
    KeyTooLarge {
        size: usize,
        max: usize,
    },

    /// Value is too large to fit in a single page.
    ValueTooLarge {
        size: usize,
        max: usize,
    },

    /// Buffer pool is exhausted — all frames are pinned.
    /// This means too many concurrent operations are holding pages.
    BufferPoolExhausted {
        capacity: usize,
        pinned: usize,
    },

    /// WAL is corrupted — recovery cannot proceed.
    WalCorrupted {
        segment: u64,
        offset: u64,
        reason: String,
    },

    /// WAL segment file is missing.
    WalSegmentMissing {
        segment: u64,
    },

    /// Attempted to write to a read-only page (e.g., during recovery).
    ReadOnly,

    /// The database directory does not exist or is not accessible.
    InvalidPath(String),

    /// A B+Tree invariant was violated (internal bug).
    BTreeInvariantViolation(String),

    /// Serialization/deserialization error.
    SerializationError(String),

    /// Generic internal error (should not happen in correct code).
    Internal(String),
}

impl fmt::Display for StorageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StorageError::Io(e) => write!(f, "I/O error: {}", e),
            StorageError::InvalidPageMagic => write!(f, "Invalid page magic number"),
            StorageError::PagePinned => write!(f, "Page is currently pinned"),
            StorageError::Corruption(msg) => write!(f, "Data corruption: {}", msg),
            StorageError::ChecksumMismatch { page_id, expected, actual } => {
                write!(f, "Checksum mismatch on page {}: expected 0x{:08X}, got 0x{:08X}", 
                       page_id, expected, actual)
            }
            StorageError::PageFull { page_id, capacity, requested } => {
                write!(f, "Page {} is full: capacity={}, requested={}", 
                       page_id, capacity, requested)
            }
            StorageError::KeyTooLarge { size, max } => {
                write!(f, "Key too large: {} bytes (max {})", size, max)
            }
            StorageError::ValueTooLarge { size, max } => {
                write!(f, "Value too large: {} bytes (max {})", size, max)
            }
            StorageError::BufferPoolExhausted { capacity, pinned } => {
                write!(f, "Buffer pool exhausted: {}/{} frames pinned", pinned, capacity)
            }
            StorageError::WalCorrupted { segment, offset, reason } => {
                write!(f, "WAL corrupted at segment {} offset {}: {}", segment, offset, reason)
            }
            StorageError::WalSegmentMissing { segment } => {
                write!(f, "WAL segment {} is missing", segment)
            }
            StorageError::ReadOnly => write!(f, "Database is read-only"),
            StorageError::InvalidPath(p) => write!(f, "Invalid database path: {}", p),
            StorageError::BTreeInvariantViolation(msg) => {
                write!(f, "B+Tree invariant violated: {}", msg)
            }
            StorageError::SerializationError(msg) => {
                write!(f, "Serialization error: {}", msg)
            }
            StorageError::Internal(msg) => write!(f, "Internal error: {}", msg),
        }
    }
}

impl std::error::Error for StorageError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            StorageError::Io(e) => Some(e),
            _ => None,
        }
    }
}

impl From<io::Error> for StorageError {
    fn from(e: io::Error) -> Self {
        StorageError::Io(e)
    }
}

/// Convenience type alias.
pub type StorageResult<T> = Result<T, StorageError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_display() {
        let e = StorageError::ChecksumMismatch {
            page_id: 42,
            expected: 0xDEADBEEF,
            actual: 0xCAFEBABE,
        };
        let s = format!("{}", e);
        assert!(s.contains("page 42"));
        assert!(s.contains("DEADBEEF"));
        assert!(s.contains("CAFEBABE"));
    }

    #[test]
    fn test_io_error_conversion() {
        let io_err = io::Error::new(io::ErrorKind::NotFound, "file missing");
        let storage_err: StorageError = io_err.into();
        assert!(matches!(storage_err, StorageError::Io(_)));
        assert!(format!("{}", storage_err).contains("file missing"));
    }

    #[test]
    fn test_error_source() {
        let io_err = io::Error::new(io::ErrorKind::Other, "disk full");
        let storage_err = StorageError::Io(io_err);
        assert!(std::error::Error::source(&storage_err).is_some());

        let other_err = StorageError::ReadOnly;
        assert!(std::error::Error::source(&other_err).is_none());
    }
}
