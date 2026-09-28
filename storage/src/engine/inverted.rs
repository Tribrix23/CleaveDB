use std::sync::Arc;
use crate::error::{StorageError, StorageResult};
use crate::btree::BTree;
use crate::btree::cursor::Cursor;

/// Inverted Index mapping Terms -> Documents with Term Frequencies
pub struct InvertedIndex {
    tree: BTree,
}

impl InvertedIndex {
    pub fn new(tree: BTree) -> Self {
        Self { tree }
    }

    /// Insert or update a term frequency for a document.
    pub fn insert(&self, term: &str, doc_id: &str, term_freq: u32) -> StorageResult<()> {
        let key = Self::make_key(term, doc_id);
        let value = term_freq.to_le_bytes();
        self.tree.insert(&key, &value)
    }

    /// Search for documents containing a term.
    /// Returns a list of (doc_id, term_freq).
    pub fn search(&self, term: &str) -> StorageResult<Vec<(String, u32)>> {
        let mut results = Vec::new();
        let prefix = format!("{}:", term).into_bytes();
        
        let mut cursor = Cursor::seek(&self.tree, &prefix)?;
        
        while let Some((k, v)) = cursor.next()? {
            if !k.starts_with(&prefix) {
                break;
            }
            // Parse doc_id
            if let Ok(key_str) = String::from_utf8(k) {
                let doc_id = key_str[prefix.len()..].to_string();
                let mut buf = [0u8; 4];
                buf.copy_from_slice(&v[0..4]);
                let tf = u32::from_le_bytes(buf);
                results.push((doc_id, tf));
            }
        }
        
        Ok(results)
    }

    /// Calculates BM25 score.
    /// Note: true BM25 requires global document frequency (df) and average doc length (avgdl).
    /// This is a simplified prototype.
    pub fn bm25_score(tf: u32, df: u32, total_docs: u32, doc_len: u32, avgdl: f32) -> f32 {
        let k1 = 1.2;
        let b = 0.75;
        
        let idf = ((total_docs as f32 - df as f32 + 0.5) / (df as f32 + 0.5) + 1.0).ln();
        let tf_f32 = tf as f32;
        
        let numerator = tf_f32 * (k1 + 1.0);
        let denominator = tf_f32 + k1 * (1.0 - b + b * (doc_len as f32 / avgdl));
        
        idf * (numerator / denominator)
    }

    fn make_key(term: &str, doc_id: &str) -> Vec<u8> {
        format!("{}:{}", term, doc_id).into_bytes()
    }
}
