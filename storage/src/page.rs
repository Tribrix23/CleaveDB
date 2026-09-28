use crate::error::{StorageError, StorageResult};
use byteorder::{ByteOrder, LittleEndian};
use crc32fast::Hasher;
use lz4_flex;

pub const PAGE_SIZE: usize = 16384;
pub const PAGE_HEADER_SIZE: usize = 36; // 36 bytes to fit all fields requested
pub const SLOT_ENTRY_SIZE: usize = 4;
pub const PAGE_MAGIC: u32 = 0xC1EA_DB03;

pub type PageId = u64;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum PageType {
    Internal = 1,
    Leaf = 2,
    Overflow = 3,
    Free = 4,
}

impl PageType {
    pub fn from_u8(v: u8) -> Option<Self> {
        match v {
            1 => Some(PageType::Internal),
            2 => Some(PageType::Leaf),
            3 => Some(PageType::Overflow),
            4 => Some(PageType::Free),
            _ => None,
        }
    }
}

pub struct Page {
    pub data: Box<[u8; PAGE_SIZE]>,
}

impl Page {
    pub fn new(page_id: PageId, page_type: PageType) -> Self {
        let mut page = Page {
            data: Box::new([0; PAGE_SIZE]),
        };
        page.set_magic(PAGE_MAGIC);
        page.set_page_id(page_id);
        page.set_page_type(page_type);
        page.set_n_entries(0);
        page.set_free_space_offset(PAGE_HEADER_SIZE as u16);
        page.set_data_end_offset(PAGE_SIZE as u16);
        page.set_right_sibling(0);
        page.set_lsn(0);
        page.set_checksum(0);
        page.data[35] = 0; // _reserved
        page
    }

    pub fn from_bytes(data: [u8; PAGE_SIZE]) -> StorageResult<Self> {
        let page = Page { data: Box::new(data) };
        if page.magic() != PAGE_MAGIC {
            return Err(StorageError::InvalidPageMagic);
        }
        page.verify_checksum()?;
        Ok(page)
    }

    pub fn magic(&self) -> u32 {
        LittleEndian::read_u32(&self.data[0..4])
    }
    pub fn set_magic(&mut self, val: u32) {
        LittleEndian::write_u32(&mut self.data[0..4], val);
    }

    pub fn page_id(&self) -> PageId {
        LittleEndian::read_u64(&self.data[4..12])
    }
    pub fn set_page_id(&mut self, val: PageId) {
        LittleEndian::write_u64(&mut self.data[4..12], val);
    }

    pub fn page_type(&self) -> PageType {
        PageType::from_u8(self.data[12]).unwrap_or(PageType::Free)
    }
    pub fn set_page_type(&mut self, val: PageType) {
        self.data[12] = val as u8;
    }

    pub fn n_entries(&self) -> u16 {
        LittleEndian::read_u16(&self.data[13..15])
    }
    pub fn set_n_entries(&mut self, val: u16) {
        LittleEndian::write_u16(&mut self.data[13..15], val);
    }

    pub fn free_space_offset(&self) -> u16 {
        LittleEndian::read_u16(&self.data[15..17])
    }
    pub fn set_free_space_offset(&mut self, val: u16) {
        LittleEndian::write_u16(&mut self.data[15..17], val);
    }

    pub fn data_end_offset(&self) -> u16 {
        LittleEndian::read_u16(&self.data[17..19])
    }
    pub fn set_data_end_offset(&mut self, val: u16) {
        LittleEndian::write_u16(&mut self.data[17..19], val);
    }

    pub fn right_sibling(&self) -> PageId {
        LittleEndian::read_u64(&self.data[19..27])
    }
    pub fn set_right_sibling(&mut self, val: PageId) {
        LittleEndian::write_u64(&mut self.data[19..27], val);
    }

    pub fn lsn(&self) -> u32 {
        LittleEndian::read_u32(&self.data[27..31])
    }
    pub fn set_lsn(&mut self, val: u32) {
        LittleEndian::write_u32(&mut self.data[27..31], val);
    }

    pub fn checksum(&self) -> u32 {
        LittleEndian::read_u32(&self.data[31..35])
    }
    pub fn set_checksum(&mut self, val: u32) {
        LittleEndian::write_u32(&mut self.data[31..35], val);
    }

    pub fn free_space(&self) -> usize {
        self.data_end_offset() as usize - self.free_space_offset() as usize
    }

    fn slot_offset(&self, index: usize) -> usize {
        PAGE_HEADER_SIZE + index * SLOT_ENTRY_SIZE
    }

    fn read_slot(&self, index: usize) -> (u16, u16) {
        let offset = self.slot_offset(index);
        let rec_offset = LittleEndian::read_u16(&self.data[offset..offset + 2]);
        let rec_len = LittleEndian::read_u16(&self.data[offset + 2..offset + 4]);
        (rec_offset, rec_len)
    }

    fn write_slot(&mut self, index: usize, rec_offset: u16, rec_len: u16) {
        let offset = self.slot_offset(index);
        LittleEndian::write_u16(&mut self.data[offset..offset + 2], rec_offset);
        LittleEndian::write_u16(&mut self.data[offset + 2..offset + 4], rec_len);
    }

    pub fn get_at(&self, index: usize) -> Option<(&[u8], &[u8])> {
        if index >= self.n_entries() as usize {
            return None;
        }
        let (offset, len) = self.read_slot(index);
        let offset = offset as usize;
        let len = len as usize;
        if offset == 0 && len == 0 {
            return None; // Deleted
        }
        let key_len = LittleEndian::read_u16(&self.data[offset..offset + 2]) as usize;
        let key = &self.data[offset + 2..offset + 2 + key_len];
        let val = &self.data[offset + 2 + key_len..offset + len];
        Some((key, val))
    }

    pub fn search_index(&self, key: &[u8]) -> Result<usize, usize> {
        let mut left = 0;
        let mut right = self.n_entries() as usize;
        while left < right {
            let mid = left + (right - left) / 2;
            if let Some((m_key, _)) = self.get_at(mid) {
                use std::cmp::Ordering;
                match m_key.cmp(key) {
                    Ordering::Less => left = mid + 1,
                    Ordering::Greater => right = mid,
                    Ordering::Equal => return Ok(mid),
                }
            } else {
                // If we hit a deleted slot, linear search fallback (simplification)
                let mut found = false;
                for i in 0..self.n_entries() as usize {
                    if let Some((k, _)) = self.get_at(i) {
                        if k == key {
                            return Ok(i);
                        } else if k > key {
                            return Err(i);
                        }
                    }
                }
                return Err(self.n_entries() as usize);
            }
        }
        Err(left)
    }

    pub fn get(&self, key: &[u8]) -> Option<&[u8]> {
        match self.search_index(key) {
            Ok(idx) => self.get_at(idx).map(|(_, v)| v),
            Err(_) => None,
        }
    }

    fn compact(&mut self) {
        let mut new_data = Box::new([0; PAGE_SIZE]);
        new_data[..self.free_space_offset() as usize].copy_from_slice(&self.data[..self.free_space_offset() as usize]);

        let mut current_data_end = PAGE_SIZE;
        let mut current_slot = 0;

        for i in 0..self.n_entries() as usize {
            let (rec_offset, rec_len) = self.read_slot(i);
            if rec_offset != 0 {
                let rec_len_usize = rec_len as usize;
                current_data_end -= rec_len_usize;
                new_data[current_data_end..current_data_end + rec_len_usize]
                    .copy_from_slice(&self.data[rec_offset as usize..rec_offset as usize + rec_len_usize]);
                
                let slot_off = PAGE_HEADER_SIZE + current_slot * SLOT_ENTRY_SIZE;
                LittleEndian::write_u16(&mut new_data[slot_off..slot_off + 2], current_data_end as u16);
                LittleEndian::write_u16(&mut new_data[slot_off + 2..slot_off + 4], rec_len);
                current_slot += 1;
            }
        }

        self.data = new_data;
        self.set_n_entries(current_slot as u16);
        self.set_free_space_offset((PAGE_HEADER_SIZE + current_slot * SLOT_ENTRY_SIZE) as u16);
        self.set_data_end_offset(current_data_end as u16);
    }

    pub fn insert(&mut self, key: &[u8], value: &[u8]) -> StorageResult<()> {
        let required_space = SLOT_ENTRY_SIZE + 2 + key.len() + value.len();
        if self.free_space() < required_space {
            self.compact();
            if self.free_space() < required_space {
                return Err(StorageError::PageFull { page_id: self.page_id(), capacity: self.free_space(), requested: required_space });
            }
        }

        let insert_idx = match self.search_index(key) {
            Ok(idx) => {
                // For simplicity, overwrite by marking old as deleted and inserting new
                // Real DBs might reuse space if same size, or just fail if unique.
                self.write_slot(idx, 0, 0); // mark deleted
                self.compact();
                if self.free_space() < required_space {
                    return Err(StorageError::PageFull { page_id: self.page_id(), capacity: self.free_space(), requested: required_space });
                }
                self.search_index(key).unwrap_err()
            }
            Err(idx) => idx,
        };

        // Shift slots right
        let n = self.n_entries() as usize;
        let slots_start = self.slot_offset(insert_idx);
        let slots_end = self.slot_offset(n);
        self.data.copy_within(slots_start..slots_end, slots_start + SLOT_ENTRY_SIZE);

        let rec_len = (2 + key.len() + value.len()) as u16;
        let data_end = self.data_end_offset() - rec_len;
        self.set_data_end_offset(data_end);

        let offset = data_end as usize;
        LittleEndian::write_u16(&mut self.data[offset..offset + 2], key.len() as u16);
        self.data[offset + 2..offset + 2 + key.len()].copy_from_slice(key);
        self.data[offset + 2 + key.len()..offset + rec_len as usize].copy_from_slice(value);

        self.write_slot(insert_idx, data_end, rec_len);

        self.set_n_entries((n + 1) as u16);
        self.set_free_space_offset(self.free_space_offset() + SLOT_ENTRY_SIZE as u16);

        Ok(())
    }

    pub fn delete(&mut self, key: &[u8]) -> bool {
        if let Ok(idx) = self.search_index(key) {
            self.write_slot(idx, 0, 0);
            true
        } else {
            false
        }
    }

    pub fn split(&mut self) -> StorageResult<Page> {
        self.compact();
        let n = self.n_entries() as usize;
        if n < 2 {
            return Err(StorageError::PageFull { page_id: self.page_id(), capacity: self.free_space(), requested: 0 }); // Cannot split
        }

        let mut new_page = Page::new(0, self.page_type()); // ID will be set by caller
        new_page.set_right_sibling(self.right_sibling());

        let mid = n / 2;
        
        for i in mid..n {
            if let Some((k, v)) = self.get_at(i) {
                new_page.insert(k, v)?;
                self.write_slot(i, 0, 0); // mark deleted in original
            }
        }

        self.compact();
        Ok(new_page)
    }

    pub fn finalize(&mut self) {
        self.set_checksum(0);
        let mut hasher = Hasher::new();
        hasher.update(self.data.as_ref());
        let cksum = hasher.finalize();
        self.set_checksum(cksum);
    }

    pub fn to_bytes(&self) -> &[u8; PAGE_SIZE] {
        &self.data
    }

    pub fn verify_checksum(&self) -> StorageResult<()> {
        let stored = self.checksum();
        let mut temp_data = self.data.clone();
        LittleEndian::write_u32(&mut temp_data[31..35], 0);
        
        let mut hasher = Hasher::new();
        hasher.update(temp_data.as_ref());
        let actual = hasher.finalize();
        if actual != stored {
            Err(StorageError::ChecksumMismatch { page_id: self.page_id(), expected: stored, actual })
        } else {
            Ok(())
        }
    }

    pub fn compress(&self) -> Vec<u8> {
        lz4_flex::compress_prepend_size(self.data.as_ref())
    }

    pub fn decompress(data: &[u8]) -> StorageResult<Page> {
        let uncompressed = lz4_flex::decompress_size_prepended(data)
            .map_err(|e| StorageError::SerializationError(format!("Compression error: {}", e)))?;
        if uncompressed.len() != PAGE_SIZE {
            return Err(StorageError::SerializationError(format!("Invalid page size after decompression: {} != {}", uncompressed.len(), PAGE_SIZE)));
        }
        let mut page_data = [0u8; PAGE_SIZE];
        page_data.copy_from_slice(&uncompressed);
        Page::from_bytes(page_data)
    }

    pub fn insert_internal(&mut self, key: &[u8], child_page_id: u64) -> StorageResult<()> {
        let mut val = [0u8; 8];
        LittleEndian::write_u64(&mut val, child_page_id);
        self.insert(key, &val)
    }

    pub fn search_child(&self, key: &[u8]) -> u64 {
        match self.search_index(key) {
            Ok(idx) => self.get_child_at(idx),
            Err(idx) => {
                if idx == 0 {
                    self.get_child_at(0)
                } else {
                    self.get_child_at(idx - 1)
                }
            }
        }
    }

    pub fn get_child_at(&self, index: usize) -> u64 {
        if let Some((_, v)) = self.get_at(index) {
            LittleEndian::read_u64(v)
        } else {
            0
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_and_insert() {
        let mut page = Page::new(1, PageType::Leaf);
        for i in 0..50 {
            let key = format!("key_{:03}", i).into_bytes();
            let val = format!("val_{:03}", i).into_bytes();
            page.insert(&key, &val).unwrap();
        }
        assert_eq!(page.n_entries(), 50);

        for i in 0..50 {
            let key = format!("key_{:03}", i).into_bytes();
            let val = format!("val_{:03}", i).into_bytes();
            assert_eq!(page.get(&key).unwrap(), val.as_slice());
        }
    }

    #[test]
    fn test_delete() {
        let mut page = Page::new(1, PageType::Leaf);
        let key = b"my_key";
        let val = b"my_val";
        page.insert(key, val).unwrap();
        assert_eq!(page.get(key).unwrap(), val);
        
        assert!(page.delete(key));
        assert!(page.get(key).is_none());
    }

    #[test]
    fn test_page_full() {
        let mut page = Page::new(1, PageType::Leaf);
        let mut i = 0;
        loop {
            let key = format!("k{}", i).into_bytes();
            let val = vec![0u8; 200]; // 200 bytes per record
            if page.insert(&key, &val).is_err() {
                break;
            }
            i += 1;
        }
        assert!(i > 0);
        assert!(page.n_entries() > 0);
    }

    #[test]
    fn test_split() {
        let mut page = Page::new(1, PageType::Leaf);
        for i in 0..100 {
            let key = format!("key_{:03}", i).into_bytes();
            let val = format!("val_{:03}", i).into_bytes();
            page.insert(&key, &val).unwrap();
        }
        
        let n_before = page.n_entries();
        let mut sibling = page.split().unwrap();
        sibling.set_page_id(2);
        
        assert!(page.n_entries() < n_before);
        assert!(sibling.n_entries() > 0);
        assert_eq!(page.n_entries() + sibling.n_entries(), n_before);
    }

    #[test]
    fn test_checksum() {
        let mut page = Page::new(1, PageType::Leaf);
        page.insert(b"test", b"value").unwrap();
        page.finalize();
        page.verify_checksum().unwrap();

        // Corrupt
        page.data[100] = !page.data[100];
        assert!(page.verify_checksum().is_err());
    }

    #[test]
    fn test_compression() {
        let mut page = Page::new(1, PageType::Leaf);
        page.insert(b"test", b"value").unwrap();
        page.finalize();

        let compressed = page.compress();
        assert!(compressed.len() > 0);

        let decompressed = Page::decompress(&compressed).unwrap();
        assert_eq!(decompressed.magic(), PAGE_MAGIC);
        assert_eq!(decompressed.get(b"test").unwrap(), b"value");
    }

    #[test]
    fn test_internal_page() {
        let mut page = Page::new(1, PageType::Internal);
        page.insert_internal(b"key_1", 100).unwrap();
        page.insert_internal(b"key_5", 500).unwrap();

        assert_eq!(page.search_child(b"key_0"), 100);
        assert_eq!(page.search_child(b"key_1"), 100);
        assert_eq!(page.search_child(b"key_3"), 100);
        assert_eq!(page.search_child(b"key_5"), 500);
        assert_eq!(page.search_child(b"key_9"), 500);
    }
}
