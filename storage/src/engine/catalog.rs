use serde::{Serialize, Deserialize};
use std::path::Path;
use std::fs::File;
use std::io::{Read, Write};
use crate::error::{StorageError, StorageResult};
use super::bucket_bond::{Bucket, Bond, BucketTrie};

/// The database catalog containing schema information (buckets, bonds, indexes).
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Catalog {
    /// List of all buckets.
    pub buckets: Vec<Bucket>,
    /// List of all bonds between buckets.
    pub bonds: Vec<Bond>,
    /// List of all index names.
    pub indexes: Vec<String>,
}

impl Catalog {
    /// Creates a new, empty `Catalog`.
    pub fn new() -> Self {
        Self {
            buckets: Vec::new(),
            bonds: Vec::new(),
            indexes: Vec::new(),
        }
    }

    /// Saves the catalog to the given file path.
    /// Uses a temporary file and atomic rename to ensure safety.
    pub fn save(&self, path: &Path) -> StorageResult<()> {
        let data = rmp_serde::to_vec_named(self)
            .map_err(|e| StorageError::SerializationError(e.to_string()))?;
        
        let tmp_path = path.with_extension("tmp");
        
        let mut file = File::create(&tmp_path)?;
        file.write_all(&data)?;
        file.sync_all()?;
        
        std::fs::rename(&tmp_path, path)?;
        
        Ok(())
    }

    /// Loads the catalog from the given file path.
    pub fn load(path: &Path) -> StorageResult<Self> {
        let mut file = File::open(path)?;
        let mut data = Vec::new();
        file.read_to_end(&mut data)?;
        
        let catalog: Catalog = rmp_serde::from_slice(&data)
            .map_err(|e| StorageError::SerializationError(e.to_string()))?;
            
        Ok(catalog)
    }

    /// Converts the catalog into a `BucketTrie` for fast runtime lookups.
    pub fn to_trie(&self) -> BucketTrie {
        let mut trie = BucketTrie::new();
        for bucket in &self.buckets {
            trie.add_bucket(bucket.clone());
        }
        for bond in &self.bonds {
            trie.add_bond(bond.clone());
        }
        trie
    }
}

impl Default for Catalog {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;
    use crate::engine::bucket_bond::{RetentionPolicy, Enforcement};

    #[test]
    fn test_catalog_save_load() {
        let mut catalog = Catalog::new();
        
        let bucket = Bucket {
            name: "users".to_string(),
            parent: None,
            retention: RetentionPolicy {
                max_docs: Some(1000),
                ttl_seconds: None,
            },
        };
        
        let bond = Bond {
            name: "users_to_posts".to_string(),
            from_bucket: "users".to_string(),
            to_bucket: "posts".to_string(),
            enforcement: Enforcement::Strict,
            cascade_delete: true,
        };
        
        catalog.buckets.push(bucket);
        catalog.bonds.push(bond);
        catalog.indexes.push("idx_users_name".to_string());
        
        let temp_file = NamedTempFile::new().unwrap();
        let path = temp_file.path();
        
        // Save the catalog
        catalog.save(path).unwrap();
        
        // Load it back
        let loaded_catalog = Catalog::load(path).unwrap();
        
        // Verify equality
        assert_eq!(loaded_catalog.buckets.len(), 1);
        assert_eq!(loaded_catalog.buckets[0].name, "users");
        assert_eq!(loaded_catalog.buckets[0].retention.max_docs, Some(1000));
        
        assert_eq!(loaded_catalog.bonds.len(), 1);
        assert_eq!(loaded_catalog.bonds[0].name, "users_to_posts");
        assert_eq!(loaded_catalog.bonds[0].from_bucket, "users");
        assert_eq!(loaded_catalog.bonds[0].to_bucket, "posts");
        assert_eq!(loaded_catalog.bonds[0].enforcement, Enforcement::Strict);
        assert_eq!(loaded_catalog.bonds[0].cascade_delete, true);
        
        assert_eq!(loaded_catalog.indexes.len(), 1);
        assert_eq!(loaded_catalog.indexes[0], "idx_users_name");
        
        // Test to_trie
        let trie = loaded_catalog.to_trie();
        assert!(trie.get_bucket("users").is_some());
        assert_eq!(trie.get_bonds_for_bucket("users").len(), 1);
    }
}
