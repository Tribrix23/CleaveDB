use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Enforcement levels for bonds.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub enum Enforcement {
    Soft,
    Firm,
    Strict,
}

/// A bond defines a relationship between two buckets.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Bond {
    pub name: String,
    pub from_bucket: String,
    pub to_bucket: String,
    pub enforcement: Enforcement,
    pub cascade_delete: bool,
}

/// A policy defining data retention limits.
#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct RetentionPolicy {
    pub max_docs: Option<u64>,
    pub ttl_seconds: Option<u64>,
}

/// A bucket for storing data.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Bucket {
    pub name: String,
    pub parent: Option<String>,
    pub retention: RetentionPolicy,
}

/// A structure to hold buckets and their bonds, resolving hierarchies.
pub struct BucketTrie {
    pub buckets: HashMap<String, Bucket>,
    pub bonds: HashMap<String, Bond>,
}

impl BucketTrie {
    /// Creates a new, empty `BucketTrie`.
    pub fn new() -> Self {
        Self {
            buckets: HashMap::new(),
            bonds: HashMap::new(),
        }
    }

    /// Adds a bucket to the trie.
    pub fn add_bucket(&mut self, bucket: Bucket) {
        self.buckets.insert(bucket.name.clone(), bucket);
    }

    /// Retrieves a reference to a bucket by name.
    pub fn get_bucket(&self, name: &str) -> Option<&Bucket> {
        self.buckets.get(name)
    }

    /// Resolves the effective retention policy for a bucket by traversing up to its parents.
    pub fn resolve_policy(&self, bucket_name: &str) -> RetentionPolicy {
        let mut policy = RetentionPolicy::default();
        let mut current_name = Some(bucket_name.to_string());

        while let Some(name) = current_name {
            if let Some(bucket) = self.get_bucket(&name) {
                if policy.max_docs.is_none() {
                    policy.max_docs = bucket.retention.max_docs;
                }
                if policy.ttl_seconds.is_none() {
                    policy.ttl_seconds = bucket.retention.ttl_seconds;
                }
                
                if policy.max_docs.is_some() && policy.ttl_seconds.is_some() {
                    break;
                }

                current_name = bucket.parent.clone();
            } else {
                break;
            }
        }

        policy
    }

    /// Adds a bond to the trie.
    pub fn add_bond(&mut self, bond: Bond) {
        self.bonds.insert(bond.name.clone(), bond);
    }

    /// Retrieves all bonds associated with a given bucket name.
    pub fn get_bonds_for_bucket(&self, bucket_name: &str) -> Vec<&Bond> {
        self.bonds
            .values()
            .filter(|b| b.from_bucket == bucket_name || b.to_bucket == bucket_name)
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_resolve_policy() {
        let mut trie = BucketTrie::new();
        
        let parent = Bucket {
            name: "parent".to_string(),
            parent: None,
            retention: RetentionPolicy {
                max_docs: None,
                ttl_seconds: Some(3600),
            },
        };
        
        let child = Bucket {
            name: "child".to_string(),
            parent: Some("parent".to_string()),
            retention: RetentionPolicy {
                max_docs: Some(100),
                ttl_seconds: None,
            },
        };
        
        trie.add_bucket(parent);
        trie.add_bucket(child);
        
        let resolved = trie.resolve_policy("child");
        assert_eq!(resolved.max_docs, Some(100));
        assert_eq!(resolved.ttl_seconds, Some(3600));
    }

    #[test]
    fn test_get_bonds_for_bucket() {
        let mut trie = BucketTrie::new();
        
        let bond1 = Bond {
            name: "bond1".to_string(),
            from_bucket: "a".to_string(),
            to_bucket: "b".to_string(),
            enforcement: Enforcement::Firm,
            cascade_delete: true,
        };
        
        let bond2 = Bond {
            name: "bond2".to_string(),
            from_bucket: "b".to_string(),
            to_bucket: "c".to_string(),
            enforcement: Enforcement::Soft,
            cascade_delete: false,
        };
        
        trie.add_bond(bond1);
        trie.add_bond(bond2);
        
        let bonds_a = trie.get_bonds_for_bucket("a");
        assert_eq!(bonds_a.len(), 1);
        assert_eq!(bonds_a[0].name, "bond1");
        
        let bonds_b = trie.get_bonds_for_bucket("b");
        assert_eq!(bonds_b.len(), 2);
    }
}
