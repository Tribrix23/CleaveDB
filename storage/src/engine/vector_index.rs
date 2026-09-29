use crate::error::StorageResult;
use crate::simd_ffi::dot_product;

/// Flat (brute-force) vector index for semantic search.
///
/// Stores document embeddings and performs exact nearest-neighbor search
/// using SIMD-accelerated dot product from the C++ layer.
pub struct VectorIndex {
    vectors: Vec<(String, Vec<f32>)>,
    dim: usize,
}

impl VectorIndex {
    pub fn new(dim: usize) -> Self {
        Self {
            vectors: Vec::new(),
            dim,
        }
    }

    /// Insert a document embedding. Returns error if dimension mismatches.
    pub fn insert(&mut self, doc_id: &str, embedding: Vec<f32>) -> StorageResult<()> {
        if embedding.len() != self.dim {
            return Err(crate::error::StorageError::Corruption(
                format!(
                    "VectorIndex: expected {}-dim embedding, got {}",
                    self.dim,
                    embedding.len()
                ),
            ));
        }
        // Remove existing entry for this doc_id (upsert semantics)
        self.vectors.retain(|(id, _)| id != doc_id);
        self.vectors.push((doc_id.to_string(), embedding));
        Ok(())
    }

    /// Delete a document's embedding by ID.
    pub fn delete(&mut self, doc_id: &str) {
        self.vectors.retain(|(id, _)| id != doc_id);
    }

    /// Search for the top-k most similar documents to the query vector.
    ///
    /// Uses cosine similarity (via dot product on normalized vectors).
    /// Returns `(doc_id, score)` pairs sorted by score descending.
    pub fn search(&self, query: &[f32], top_k: usize) -> Vec<(String, f32)> {
        if query.len() != self.dim || self.vectors.is_empty() {
            return Vec::new();
        }

        let query_norm = l2_norm(query);
        if query_norm < f32::EPSILON {
            return Vec::new();
        }

        let mut scored: Vec<(String, f32)> = self
            .vectors
            .iter()
            .map(|(id, vec)| {
                let vec_norm = l2_norm(vec);
                let raw_dot = dot_product(query, vec);
                let cosine = if vec_norm > f32::EPSILON {
                    raw_dot / (query_norm * vec_norm)
                } else {
                    0.0
                };
                (id.clone(), cosine)
            })
            .collect();

        // Sort by score descending
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(top_k);
        scored
    }

    pub fn len(&self) -> usize {
        self.vectors.len()
    }

    pub fn is_empty(&self) -> bool {
        self.vectors.is_empty()
    }
}

fn l2_norm(v: &[f32]) -> f32 {
    v.iter().map(|x| x * x).sum::<f32>().sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_insert_search() {
        let dim = 4;
        let mut idx = VectorIndex::new(dim);

        // Insert some vectors
        idx.insert("a", vec![1.0, 0.0, 0.0, 0.0]).unwrap();
        idx.insert("b", vec![0.0, 1.0, 0.0, 0.0]).unwrap();
        idx.insert("c", vec![0.9, 0.1, 0.0, 0.0]).unwrap();

        // Query close to "a" and "c"
        let results = idx.search(&[1.0, 0.0, 0.0, 0.0], 2);
        assert_eq!(results.len(), 2);
        // "a" should be first (exact match)
        assert_eq!(results[0].0, "a");
        assert!((results[0].1 - 1.0).abs() < 0.01);
    }

    #[test]
    fn test_delete() {
        let mut idx = VectorIndex::new(2);
        idx.insert("x", vec![1.0, 0.0]).unwrap();
        idx.insert("y", vec![0.0, 1.0]).unwrap();
        assert_eq!(idx.len(), 2);

        idx.delete("x");
        assert_eq!(idx.len(), 1);
        let results = idx.search(&[1.0, 0.0], 5);
        assert!(results.iter().all(|(id, _)| id != "x"));
    }

    #[test]
    fn test_dim_mismatch() {
        let mut idx = VectorIndex::new(3);
        assert!(idx.insert("bad", vec![1.0, 2.0]).is_err());
    }
}
