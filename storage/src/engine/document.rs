use serde::{Serialize, Deserialize};
use std::time::{SystemTime, UNIX_EPOCH};
use xxhash_rust::xxh3::xxh3_64;
use crate::error::{StorageError, StorageResult};

/// The Document model representing a schemaless JSON document in a bucket.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Document {
    /// Globally unique ID
    pub gid: String,
    /// Which bucket it belongs to
    pub bucket: String,
    /// Schemaless JSON document body
    pub body: serde_json::Value,
    /// Unix timestamp in milliseconds when the document was created
    pub created_at: u64,
    /// Unix timestamp in milliseconds when the document was last updated
    pub updated_at: u64,
}

impl Document {
    /// Creates a new `Document`.
    /// 
    /// If `provided_gid` is `None`, generates a GID by hashing the bucket + body using `xxh3_64`
    /// and formatting it as a 16-character hex string.
    pub fn new(bucket: &str, body: serde_json::Value, provided_gid: Option<&str>) -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64;

        let gid = match provided_gid {
            Some(id) => id.to_string(),
            None => {
                let mut data = bucket.as_bytes().to_vec();
                let body_str = serde_json::to_string(&body).unwrap_or_default();
                data.extend_from_slice(body_str.as_bytes());
                let hash = xxh3_64(&data);
                format!("{:016x}", hash)
            }
        };

        Self {
            gid,
            bucket: bucket.to_string(),
            body,
            created_at: now,
            updated_at: now,
        }
    }

    /// Serializes the document to MessagePack format.
    pub fn to_msgpack(&self) -> StorageResult<Vec<u8>> {
        rmp_serde::to_vec_named(self)
            .map_err(|e| StorageError::SerializationError(e.to_string()))
    }

    /// Deserializes a document from MessagePack format.
    pub fn from_msgpack(data: &[u8]) -> StorageResult<Self> {
        rmp_serde::from_slice(data)
            .map_err(|e| StorageError::SerializationError(e.to_string()))
    }

    /// Updates the document body and sets the `updated_at` timestamp.
    pub fn update(&mut self, new_body: serde_json::Value) {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64;
        self.body = new_body;
        self.updated_at = now;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_document_creation_and_msgpack() {
        let body = json!({ "name": "CleaveDB", "version": 3 });
        let doc = Document::new("projects", body.clone(), Some("doc_123"));
        
        assert_eq!(doc.gid, "doc_123");
        assert_eq!(doc.bucket, "projects");
        assert_eq!(doc.body, body);
        assert!(doc.created_at > 0);
        assert_eq!(doc.created_at, doc.updated_at);

        let msgpack_data = doc.to_msgpack().expect("Failed to serialize document");
        let deserialized = Document::from_msgpack(&msgpack_data).expect("Failed to deserialize document");

        assert_eq!(doc.gid, deserialized.gid);
        assert_eq!(doc.bucket, deserialized.bucket);
        assert_eq!(doc.body, deserialized.body);
        assert_eq!(doc.created_at, deserialized.created_at);
        assert_eq!(doc.updated_at, deserialized.updated_at);
    }

    #[test]
    fn test_deterministic_gid_generation() {
        let body = json!({ "field": "value", "count": 42 });
        let doc1 = Document::new("test_bucket", body.clone(), None);
        let doc2 = Document::new("test_bucket", body.clone(), None);
        
        assert_eq!(doc1.gid, doc2.gid, "Generated GIDs should be deterministic");
        assert_eq!(doc1.gid.len(), 16, "Generated GID should be 16 characters long");
    }

    #[test]
    fn test_update_document() {
        let body1 = json!({ "status": "draft" });
        let mut doc = Document::new("articles", body1, None);
        
        let old_updated_at = doc.updated_at;
        
        let body2 = json!({ "status": "published" });
        doc.update(body2.clone());
        
        assert_eq!(doc.body, body2);
        assert!(doc.updated_at >= old_updated_at);
    }
}
