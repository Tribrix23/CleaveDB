use std::fs::{self, File, OpenOptions};
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

use byteorder::{LittleEndian, ReadBytesExt, WriteBytesExt};
use crc32fast::Hasher;
use parking_lot::Mutex;

use crate::error::{StorageError, StorageResult};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SyncMode {
    Sync,
    Async,
    NoSync,
}

#[derive(Debug, Clone)]
pub struct WalConfig {
    pub dir: PathBuf,
    pub sync_mode: SyncMode,
    pub segment_max_bytes: u64,
    pub flush_interval_ms: u64,
}

impl Default for WalConfig {
    fn default() -> Self {
        WalConfig {
            dir: PathBuf::from("wal"),
            sync_mode: SyncMode::Sync,
            segment_max_bytes: 64 * 1024 * 1024,
            flush_interval_ms: 50,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WalEntry {
    Put {
        lsn: u64,
        tree_name: String,
        key: Vec<u8>,
        value: Vec<u8>,
    },
    Delete {
        lsn: u64,
        tree_name: String,
        key: Vec<u8>,
    },
    Checkpoint {
        lsn: u64,
    },
}

const RECORD_TYPE_PUT: u8 = 0;
const RECORD_TYPE_DELETE: u8 = 1;
const RECORD_TYPE_CHECKPOINT: u8 = 2;

impl WalEntry {
    pub fn lsn(&self) -> u64 {
        match self {
            WalEntry::Put { lsn, .. } => *lsn,
            WalEntry::Delete { lsn, .. } => *lsn,
            WalEntry::Checkpoint { lsn } => *lsn,
        }
    }

    pub fn serialize(&self, buf: &mut Vec<u8>) {
        let mut payload = Vec::new();

        let record_type = match self {
            WalEntry::Put { tree_name, key, value, .. } => {
                payload.write_u16::<LittleEndian>(tree_name.len() as u16).unwrap();
                payload.write_all(tree_name.as_bytes()).unwrap();
                payload.write_u32::<LittleEndian>(key.len() as u32).unwrap();
                payload.write_all(key).unwrap();
                payload.write_u32::<LittleEndian>(value.len() as u32).unwrap();
                payload.write_all(value).unwrap();
                RECORD_TYPE_PUT
            }
            WalEntry::Delete { tree_name, key, .. } => {
                payload.write_u16::<LittleEndian>(tree_name.len() as u16).unwrap();
                payload.write_all(tree_name.as_bytes()).unwrap();
                payload.write_u32::<LittleEndian>(key.len() as u32).unwrap();
                payload.write_all(key).unwrap();
                RECORD_TYPE_DELETE
            }
            WalEntry::Checkpoint { .. } => {
                RECORD_TYPE_CHECKPOINT
            }
        };

        let lsn = self.lsn();
        let mut header = Vec::with_capacity(9);
        header.push(record_type);
        header.write_u64::<LittleEndian>(lsn).unwrap();

        let mut hasher = Hasher::new();
        hasher.update(&header);
        hasher.update(&payload);
        let checksum = hasher.finalize();

        buf.write_all(&header).unwrap();
        buf.write_u32::<LittleEndian>(checksum).unwrap();
        buf.write_all(&payload).unwrap();
    }

    pub fn deserialize(reader: &mut impl Read) -> StorageResult<Option<WalEntry>> {
        let record_type = match reader.read_u8() {
            Ok(rt) => rt,
            Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => return Ok(None),
            Err(e) => return Err(StorageError::Io(e)),
        };

        let mut header = vec![record_type];
        let lsn = reader.read_u64::<LittleEndian>().map_err(StorageError::Io)?;
        header.write_u64::<LittleEndian>(lsn).unwrap();

        let checksum_expected = reader.read_u32::<LittleEndian>().map_err(StorageError::Io)?;

        let mut hasher = Hasher::new();
        hasher.update(&header);

        let entry = match record_type {
            RECORD_TYPE_PUT => {
                let tree_name_len = reader.read_u16::<LittleEndian>().map_err(StorageError::Io)?;
                let mut tree_name_bytes = vec![0u8; tree_name_len as usize];
                reader.read_exact(&mut tree_name_bytes).map_err(StorageError::Io)?;
                let tree_name = String::from_utf8(tree_name_bytes).map_err(|_| StorageError::Corruption("Invalid UTF-8 in tree name".to_string()))?;

                let key_len = reader.read_u32::<LittleEndian>().map_err(StorageError::Io)?;
                let mut key = vec![0u8; key_len as usize];
                reader.read_exact(&mut key).map_err(StorageError::Io)?;

                let value_len = reader.read_u32::<LittleEndian>().map_err(StorageError::Io)?;
                let mut value = vec![0u8; value_len as usize];
                reader.read_exact(&mut value).map_err(StorageError::Io)?;

                let mut payload = Vec::new();
                payload.write_u16::<LittleEndian>(tree_name_len).unwrap();
                payload.write_all(tree_name.as_bytes()).unwrap();
                payload.write_u32::<LittleEndian>(key_len).unwrap();
                payload.write_all(&key).unwrap();
                payload.write_u32::<LittleEndian>(value_len).unwrap();
                payload.write_all(&value).unwrap();
                hasher.update(&payload);

                WalEntry::Put { lsn, tree_name, key, value }
            }
            RECORD_TYPE_DELETE => {
                let tree_name_len = reader.read_u16::<LittleEndian>().map_err(StorageError::Io)?;
                let mut tree_name_bytes = vec![0u8; tree_name_len as usize];
                reader.read_exact(&mut tree_name_bytes).map_err(StorageError::Io)?;
                let tree_name = String::from_utf8(tree_name_bytes).map_err(|_| StorageError::Corruption("Invalid UTF-8 in tree name".to_string()))?;

                let key_len = reader.read_u32::<LittleEndian>().map_err(StorageError::Io)?;
                let mut key = vec![0u8; key_len as usize];
                reader.read_exact(&mut key).map_err(StorageError::Io)?;

                let mut payload = Vec::new();
                payload.write_u16::<LittleEndian>(tree_name_len).unwrap();
                payload.write_all(tree_name.as_bytes()).unwrap();
                payload.write_u32::<LittleEndian>(key_len).unwrap();
                payload.write_all(&key).unwrap();
                hasher.update(&payload);

                WalEntry::Delete { lsn, tree_name, key }
            }
            RECORD_TYPE_CHECKPOINT => {
                WalEntry::Checkpoint { lsn }
            }
            _ => return Err(StorageError::Corruption(format!("Unknown record type: {}", record_type))),
        };

        if hasher.finalize() != checksum_expected {
            return Err(StorageError::Corruption("Checksum mismatch in WAL entry".to_string()));
        }

        Ok(Some(entry))
    }
}

struct WalSegment {
    file: BufWriter<File>,
    path: PathBuf,
    written_bytes: u64,
    sequence_number: u64,
    last_flush: Instant,
}

impl WalSegment {
    fn new(dir: &Path, sequence_number: u64) -> StorageResult<Self> {
        let filename = format!("wal-{:06}.log", sequence_number);
        let path = dir.join(filename);
        let file = OpenOptions::new().create(true).append(true).open(&path).map_err(StorageError::Io)?;
        let metadata = file.metadata().map_err(StorageError::Io)?;
        
        Ok(WalSegment {
            file: BufWriter::new(file),
            path,
            written_bytes: metadata.len(),
            sequence_number,
            last_flush: Instant::now(),
        })
    }

    fn write_entry(&mut self, entry: &WalEntry) -> StorageResult<()> {
        let mut buf = Vec::new();
        entry.serialize(&mut buf);
        self.file.write_all(&buf).map_err(StorageError::Io)?;
        self.written_bytes += buf.len() as u64;
        Ok(())
    }

    fn flush(&mut self, sync_mode: SyncMode, flush_interval_ms: u64) -> StorageResult<()> {
        self.file.flush().map_err(StorageError::Io)?;
        
        match sync_mode {
            SyncMode::Sync => {
                self.file.get_ref().sync_data().map_err(StorageError::Io)?;
            }
            SyncMode::Async => {
                if self.last_flush.elapsed() >= Duration::from_millis(flush_interval_ms) {
                    self.file.get_ref().sync_data().map_err(StorageError::Io)?;
                    self.last_flush = Instant::now();
                }
            }
            SyncMode::NoSync => {}
        }
        Ok(())
    }
}

pub struct WriteAheadLog {
    config: WalConfig,
    current_lsn: AtomicU64,
    checkpoint_lsn: AtomicU64,
    active_segment: Mutex<WalSegment>,
    segment_counter: AtomicU64,
}

impl WriteAheadLog {
    pub fn open(config: WalConfig) -> StorageResult<Self> {
        if !config.dir.exists() {
            fs::create_dir_all(&config.dir).map_err(StorageError::Io)?;
        }

        let mut segment_files = Self::find_segment_files(&config.dir)?;
        let mut sequence_number = 1;
        let mut current_lsn = 0;
        let mut checkpoint_lsn = 0;

        if let Some(last_file) = segment_files.last() {
            if let Some(seq) = Self::parse_sequence_number(last_file) {
                sequence_number = seq;
            }
            
            for file in &segment_files {
                let mut f = BufReader::new(File::open(file).map_err(StorageError::Io)?);
                loop {
                    match WalEntry::deserialize(&mut f) {
                        Ok(Some(entry)) => {
                            let lsn = entry.lsn();
                            if lsn > current_lsn {
                                current_lsn = lsn;
                            }
                            if let WalEntry::Checkpoint { lsn: c_lsn } = entry {
                                if c_lsn > checkpoint_lsn {
                                    checkpoint_lsn = c_lsn;
                                }
                            }
                        }
                        Ok(None) => break,
                        Err(_) => break, // Truncated or corrupted entry, stop reading this file
                    }
                }
            }
        }

        let active_segment = WalSegment::new(&config.dir, sequence_number)?;

        Ok(WriteAheadLog {
            config,
            current_lsn: AtomicU64::new(current_lsn),
            checkpoint_lsn: AtomicU64::new(checkpoint_lsn),
            active_segment: Mutex::new(active_segment),
            segment_counter: AtomicU64::new(sequence_number),
        })
    }

    fn find_segment_files(dir: &Path) -> StorageResult<Vec<PathBuf>> {
        let mut files = Vec::new();
        for entry in fs::read_dir(dir).map_err(StorageError::Io)? {
            let entry = entry.map_err(StorageError::Io)?;
            let path = entry.path();
            if path.is_file() {
                if let Some(filename) = path.file_name().and_then(|n| n.to_str()) {
                    if filename.starts_with("wal-") && filename.ends_with(".log") {
                        files.push(path);
                    }
                }
            }
        }
        files.sort();
        Ok(files)
    }

    fn parse_sequence_number(path: &Path) -> Option<u64> {
        let filename = path.file_name()?.to_str()?;
        let num_part = filename.strip_prefix("wal-")?.strip_suffix(".log")?;
        num_part.parse().ok()
    }

    pub fn log_put(&self, tree_name: &str, key: &[u8], value: &[u8]) -> StorageResult<u64> {
        let lsn = self.current_lsn.fetch_add(1, Ordering::SeqCst) + 1;
        let entry = WalEntry::Put {
            lsn,
            tree_name: tree_name.to_string(),
            key: key.to_vec(),
            value: value.to_vec(),
        };

        self.write_and_flush(entry)?;
        Ok(lsn)
    }

    pub fn log_delete(&self, tree_name: &str, key: &[u8]) -> StorageResult<u64> {
        let lsn = self.current_lsn.fetch_add(1, Ordering::SeqCst) + 1;
        let entry = WalEntry::Delete {
            lsn,
            tree_name: tree_name.to_string(),
            key: key.to_vec(),
        };

        self.write_and_flush(entry)?;
        Ok(lsn)
    }

    pub fn checkpoint(&self) -> StorageResult<u64> {
        let lsn = self.current_lsn.fetch_add(1, Ordering::SeqCst) + 1;
        let entry = WalEntry::Checkpoint { lsn };

        self.write_and_flush(entry)?;
        self.checkpoint_lsn.store(lsn, Ordering::SeqCst);
        Ok(lsn)
    }

    fn write_and_flush(&self, entry: WalEntry) -> StorageResult<()> {
        let mut segment = self.active_segment.lock();
        
        if segment.written_bytes >= self.config.segment_max_bytes {
            self.rotate_segment(&mut segment)?;
        }

        segment.write_entry(&entry)?;
        segment.flush(self.config.sync_mode, self.config.flush_interval_ms)?;
        
        Ok(())
    }

    pub fn recover(&self) -> StorageResult<Vec<WalEntry>> {
        let segment_files = Self::find_segment_files(&self.config.dir)?;
        let checkpoint_lsn = self.checkpoint_lsn.load(Ordering::SeqCst);
        let mut entries = Vec::new();
        // Safety limit: refuse to load more than 10M entries to prevent OOM.
        // In production, recovery should be streamed/batched.
        const MAX_RECOVERY_ENTRIES: usize = 10_000_000;

        for file in segment_files {
            let mut f = match File::open(&file) {
                Ok(f) => BufReader::new(f),
                Err(_) => continue,
            };

            loop {
                match WalEntry::deserialize(&mut f) {
                    Ok(Some(entry)) => {
                        if entry.lsn() > checkpoint_lsn {
                            entries.push(entry);
                            if entries.len() >= MAX_RECOVERY_ENTRIES {
                                log::warn!("WAL recovery hit {} entry limit — checkpoint more frequently", MAX_RECOVERY_ENTRIES);
                                return Ok(entries);
                            }
                        }
                    }
                    Ok(None) => break,
                    Err(_) => break, // Stop reading on corruption or EOF
                }
            }
        }

        Ok(entries)
    }

    pub fn current_lsn(&self) -> u64 {
        self.current_lsn.load(Ordering::SeqCst)
    }

    pub fn checkpoint_lsn_val(&self) -> u64 {
        self.checkpoint_lsn.load(Ordering::SeqCst)
    }

    fn rotate_segment(&self, segment: &mut WalSegment) -> StorageResult<()> {
        segment.flush(SyncMode::Sync, 0)?; // Always sync on rotate

        let next_seq = self.segment_counter.fetch_add(1, Ordering::SeqCst) + 1;
        let new_segment = WalSegment::new(&self.config.dir, next_seq)?;
        
        *segment = new_segment;
        Ok(())
    }

    pub fn cleanup_old_segments(&self) -> StorageResult<usize> {
        let segment_files = Self::find_segment_files(&self.config.dir)?;
        let checkpoint_lsn = self.checkpoint_lsn.load(Ordering::SeqCst);
        let mut deleted = 0;

        // Don't delete the last segment (active segment)
        let len = segment_files.len();
        if len <= 1 {
            return Ok(0);
        }

        for file in segment_files.into_iter().take(len - 1) {
            let mut max_lsn = 0;
            let mut f = match File::open(&file) {
                Ok(f) => BufReader::new(f),
                Err(_) => continue,
            };

            loop {
                match WalEntry::deserialize(&mut f) {
                    Ok(Some(entry)) => {
                        if entry.lsn() > max_lsn {
                            max_lsn = entry.lsn();
                        }
                    }
                    Ok(None) => break,
                    Err(_) => break,
                }
            }

            if max_lsn <= checkpoint_lsn {
                if fs::remove_file(&file).is_ok() {
                    deleted += 1;
                }
            }
        }

        Ok(deleted)
    }

    pub fn segment_files(&self) -> StorageResult<Vec<PathBuf>> {
        Self::find_segment_files(&self.config.dir)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use tempfile::tempdir;

    #[test]
    fn test_write_and_recover_100_entries() {
        let dir = tempdir().unwrap();
        let config = WalConfig {
            dir: dir.path().to_path_buf(),
            sync_mode: SyncMode::Sync,
            segment_max_bytes: 1024 * 1024,
            flush_interval_ms: 0,
        };

        let wal = WriteAheadLog::open(config.clone()).unwrap();
        for i in 1..=100 {
            wal.log_put("test_tree", format!("key{}", i).as_bytes(), format!("val{}", i).as_bytes()).unwrap();
        }

        let entries = wal.recover().unwrap();
        assert_eq!(entries.len(), 100);
        assert_eq!(wal.current_lsn(), 100);
        assert_eq!(entries[0].lsn(), 1);
        assert_eq!(entries[99].lsn(), 100);
    }

    #[test]
    fn test_checkpoint_recovery() {
        let dir = tempdir().unwrap();
        let config = WalConfig {
            dir: dir.path().to_path_buf(),
            sync_mode: SyncMode::Sync,
            segment_max_bytes: 1024 * 1024,
            flush_interval_ms: 0,
        };

        let wal = WriteAheadLog::open(config.clone()).unwrap();
        for i in 1..=50 {
            wal.log_put("test_tree", format!("key{}", i).as_bytes(), format!("val{}", i).as_bytes()).unwrap();
        }
        
        wal.checkpoint().unwrap(); // LSN 51
        
        for i in 52..=101 {
            wal.log_put("test_tree", format!("key{}", i).as_bytes(), format!("val{}", i).as_bytes()).unwrap();
        }

        let entries = wal.recover().unwrap();
        assert_eq!(entries.len(), 50); // Entries 52..=101
        assert_eq!(entries[0].lsn(), 52);
    }

    #[test]
    fn test_segment_rotation() {
        let dir = tempdir().unwrap();
        let config = WalConfig {
            dir: dir.path().to_path_buf(),
            sync_mode: SyncMode::Sync,
            segment_max_bytes: 1024, // Very small size to force rotation
            flush_interval_ms: 0,
        };

        let wal = WriteAheadLog::open(config.clone()).unwrap();
        for i in 1..=50 {
            wal.log_put("test_tree", format!("long_key_name_{}", i).as_bytes(), format!("very_long_value_string_{}", i).as_bytes()).unwrap();
        }

        let segments = wal.segment_files().unwrap();
        assert!(segments.len() > 1); // Should have rotated multiple times
    }

    #[test]
    fn test_corruption_skipping() {
        let dir = tempdir().unwrap();
        let config = WalConfig {
            dir: dir.path().to_path_buf(),
            sync_mode: SyncMode::Sync,
            segment_max_bytes: 1024 * 1024,
            flush_interval_ms: 0,
        };

        let wal = WriteAheadLog::open(config.clone()).unwrap();
        wal.log_put("test_tree", b"key1", b"val1").unwrap();
        wal.log_put("test_tree", b"key2", b"val2").unwrap();

        let segments = wal.segment_files().unwrap();
        let active = segments.last().unwrap();
        
        // Corrupt the end of the file
        let mut file = OpenOptions::new().append(true).open(active).unwrap();
        file.write_all(b"garbage_data").unwrap();
        file.sync_all().unwrap();

        let entries = wal.recover().unwrap();
        assert_eq!(entries.len(), 2); // Should recover the two valid entries and skip the garbage
    }

    #[test]
    fn test_cleanup_old_segments() {
        let dir = tempdir().unwrap();
        let config = WalConfig {
            dir: dir.path().to_path_buf(),
            sync_mode: SyncMode::Sync,
            segment_max_bytes: 1024, // Small to ensure multiple segments
            flush_interval_ms: 0,
        };

        let wal = WriteAheadLog::open(config.clone()).unwrap();
        for i in 1..=50 {
            wal.log_put("test_tree", format!("key{}", i).as_bytes(), b"val").unwrap();
        }

        let segments_before = wal.segment_files().unwrap().len();
        assert!(segments_before > 1);

        wal.checkpoint().unwrap();
        
        // Write one more to ensure checkpoint is in an older segment than active
        for i in 51..=100 {
            wal.log_put("test_tree", format!("key{}", i).as_bytes(), b"val").unwrap();
        }

        let deleted = wal.cleanup_old_segments().unwrap();
        assert!(deleted > 0);

        let segments_after = wal.segment_files().unwrap().len();
        assert!(segments_after < segments_before);
    }

    #[test]
    fn test_lsn_monotonicity() {
        let dir = tempdir().unwrap();
        let config = WalConfig {
            dir: dir.path().to_path_buf(),
            sync_mode: SyncMode::Sync,
            segment_max_bytes: 1024 * 1024,
            flush_interval_ms: 0,
        };

        let wal = WriteAheadLog::open(config.clone()).unwrap();
        let lsn1 = wal.log_put("test", b"k1", b"v1").unwrap();
        let lsn2 = wal.log_put("test", b"k2", b"v2").unwrap();
        let lsn3 = wal.checkpoint().unwrap();
        let lsn4 = wal.log_delete("test", b"k1").unwrap();

        assert!(lsn1 < lsn2);
        assert!(lsn2 < lsn3);
        assert!(lsn3 < lsn4);
    }

    #[test]
    fn test_concurrent_writes() {
        use std::sync::Arc;

        let dir = tempdir().unwrap();
        let config = WalConfig {
            dir: dir.path().to_path_buf(),
            sync_mode: SyncMode::Sync,
            segment_max_bytes: 1024 * 1024,
            flush_interval_ms: 0,
        };

        let wal = Arc::new(WriteAheadLog::open(config.clone()).unwrap());
        let mut handles = vec![];

        for t in 0..4 {
            let wal_clone = Arc::clone(&wal);
            let handle = thread::spawn(move || {
                for i in 0..25 {
                    wal_clone.log_put("test_tree", format!("k{}_{}", t, i).as_bytes(), b"v").unwrap();
                }
            });
            handles.push(handle);
        }

        for handle in handles {
            handle.join().unwrap();
        }

        let entries = wal.recover().unwrap();
        assert_eq!(entries.len(), 100);
        assert_eq!(wal.current_lsn(), 100);
    }
}
