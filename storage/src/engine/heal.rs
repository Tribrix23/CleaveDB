use crate::error::StorageResult;
use crate::engine::{Database, Document};
use crate::engine::derive::derive;
use crate::btree::cursor::Cursor;

impl Database {
    /// Rebuild all indexes from raw document data.
    ///
    /// Scans every shard, deserializes every document, extracts text terms
    /// via `derive()`, and re-inserts them into the inverted index.
    /// Also logs progress for each shard.
    pub fn heal_all(&self) -> StorageResult<()> {
        log::info!("heal_all: starting full index rebuild");

        let shards = self.shards.all_shards();
        let mut total_docs = 0u64;
        let mut total_terms = 0u64;

        for (shard_idx, shard) in shards.iter().enumerate() {
            let mut cursor = Cursor::new(shard)?;
            let mut shard_docs = 0u64;

            while let Some((_key, value)) = cursor.next()? {
                if let Ok(doc) = Document::from_msgpack(&value) {
                    let derivation = derive(&doc.body);

                    for (term, freq) in &derivation.text_terms {
                        let _ = self.inverted.insert(term, &doc.gid, *freq);
                        total_terms += 1;
                    }

                    shard_docs += 1;
                }
            }

            log::info!(
                "heal_all: shard {} — rebuilt index for {} documents",
                shard_idx, shard_docs
            );
            total_docs += shard_docs;
        }

        log::info!(
            "heal_all: complete — {} documents, {} term entries rebuilt",
            total_docs, total_terms
        );
        Ok(())
    }

    /// Sweep expired firm bonds from the Phantom Lattice whose lease duration has elapsed.
    pub fn sweep_expired_bonds(&self, current_ts: Option<u64>) -> Vec<crate::engine::ShadowRecord> {
        let ts = current_ts.unwrap_or_else(|| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs()
        });
        let expired = self.phantom_lattice.sweep_expired(ts);
        log::info!("sweep_expired_bonds: swept {} expired shadow bonds", expired.len());
        expired
    }
}
