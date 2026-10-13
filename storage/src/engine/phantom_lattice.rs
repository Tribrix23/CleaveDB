use crate::error::StorageResult;
use crate::engine::bucket_bond::Enforcement;
use serde::{Deserialize, Serialize};
use dashmap::DashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

/// A ShadowRecord represents a late-binding bond whose target document has not yet arrived.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct ShadowRecord {
    pub src_gid: String,
    pub target_gid: String,
    pub rel_name: String,
    pub enforcement: Enforcement,
    pub created_at_ts: u64,
    pub lease_expiry_ts: Option<u64>,
    pub cascade_delete: bool,
    pub status: String, // "phantom", "latched", "fused", "expired"
}

/// In-memory Counting Filter to rapidly test if a target GID has pending shadow latches.
struct LatchFilter {
    // 64K bucket counting filter for fast rejection of document writes
    counts: Box<[AtomicU64; 65536]>,
}

impl LatchFilter {
    fn new() -> Self {
        // Safe allocation of 64K atomic counters
        let counters: Vec<AtomicU64> = (0..65536).map(|_| AtomicU64::new(0)).collect();
        let boxed_slice = counters.into_boxed_slice();
        let raw = Box::into_raw(boxed_slice) as *mut [AtomicU64; 65536];
        let counts = unsafe { Box::from_raw(raw) };
        Self { counts }
    }

    #[inline]
    fn hash_index(gid: &str) -> usize {
        let hash = xxhash_rust::xxh3::xxh3_64(gid.as_bytes());
        (hash as usize) & 0xFFFF
    }

    pub fn increment(&self, gid: &str) {
        let idx = Self::hash_index(gid);
        self.counts[idx].fetch_add(1, Ordering::Relaxed);
    }

    pub fn decrement(&self, gid: &str) {
        let idx = Self::hash_index(gid);
        let _ = self.counts[idx].fetch_update(Ordering::Relaxed, Ordering::Relaxed, |val| {
            Some(if val > 0 { val - 1 } else { 0 })
        });
    }

    #[inline]
    pub fn might_contain(&self, gid: &str) -> bool {
        let idx = Self::hash_index(gid);
        self.counts[idx].load(Ordering::Relaxed) > 0
    }
}

/// The PhantomLattice manages unmaterialized, late-binding topological relationships.
pub struct PhantomLattice {
    // target_gid -> list of pending ShadowRecords pointing to this target
    latches: DashMap<String, Vec<ShadowRecord>>,
    // Fast O(1) filter for zero-I/O rejection on sequential writes
    filter: Arc<LatchFilter>,
    // Statistics counters
    total_latched: AtomicU64,
    total_snapped: AtomicU64,
    total_expired: AtomicU64,
}

impl PhantomLattice {
    pub fn new() -> Self {
        Self {
            latches: DashMap::new(),
            filter: Arc::new(LatchFilter::new()),
            total_latched: AtomicU64::new(0),
            total_snapped: AtomicU64::new(0),
            total_expired: AtomicU64::new(0),
        }
    }

    /// Register a late-binding shadow bond for an unmaterialized target.
    pub fn register_shadow_bond(&self, mut record: ShadowRecord) -> StorageResult<()> {
        record.status = "latched".to_string();
        let target_gid = record.target_gid.clone();

        self.filter.increment(&target_gid);
        self.total_latched.fetch_add(1, Ordering::Relaxed);

        self.latches.entry(target_gid)
            .or_insert_with(Vec::new)
            .push(record);

        Ok(())
    }

    /// Fast test: does this GID have pending shadow latches waiting for it?
    #[inline]
    pub fn has_pending_latches(&self, target_gid: &str) -> bool {
        if !self.filter.might_contain(target_gid) {
            return false;
        }
        self.latches.contains_key(target_gid)
    }

    /// Cleave-Snap: Atomically retrieve and remove all pending shadow records for a materialized target.
    pub fn resolve_latches_for_target(&self, target_gid: &str) -> Vec<ShadowRecord> {
        if !self.has_pending_latches(target_gid) {
            return Vec::new();
        }

        if let Some((_, records)) = self.latches.remove(target_gid) {
            for _ in 0..records.len() {
                self.filter.decrement(target_gid);
            }
            self.total_snapped.fetch_add(records.len() as u64, Ordering::Relaxed);
            records
        } else {
            Vec::new()
        }
    }

    /// Retrieve all currently pending shadow bonds (optionally filtered by target_gid).
    pub fn get_pending_bonds(&self, target_gid: Option<&str>) -> Vec<ShadowRecord> {
        if let Some(target) = target_gid {
            self.latches.get(target).map(|r| r.value().clone()).unwrap_or_default()
        } else {
            let mut all = Vec::new();
            for item in self.latches.iter() {
                all.extend(item.value().clone());
            }
            all
        }
    }

    /// Sweep expired firm bonds whose lease expiry timestamp has passed.
    pub fn sweep_expired(&self, current_ts: u64) -> Vec<ShadowRecord> {
        let mut expired = Vec::new();
        let mut empty_keys = Vec::new();

        for mut item in self.latches.iter_mut() {
            let target_gid = item.key().clone();
            let records = item.value_mut();
            
            let mut remaining = Vec::new();
            for rec in records.drain(..) {
                if let Some(lease) = rec.lease_expiry_ts {
                    if current_ts >= lease {
                        self.filter.decrement(&target_gid);
                        self.total_expired.fetch_add(1, Ordering::Relaxed);
                        let mut exp_rec = rec;
                        exp_rec.status = "expired".to_string();
                        expired.push(exp_rec);
                        continue;
                    }
                }
                remaining.push(rec);
            }
            *records = remaining;

            if records.is_empty() {
                empty_keys.push(target_gid);
            }
        }

        for k in empty_keys {
            self.latches.remove(&k);
        }

        expired
    }

    /// Return telemetry and statistics regarding the Phantom Lattice.
    pub fn stats(&self) -> serde_json::Value {
        let active_pending: usize = self.latches.iter().map(|item| item.value().len()).sum();
        serde_json::json!({
            "active_pending_latches": active_pending,
            "unique_pending_targets": self.latches.len(),
            "total_latched_bonds": self.total_latched.load(Ordering::Relaxed),
            "total_snapped_bonds": self.total_snapped.load(Ordering::Relaxed),
            "total_expired_bonds": self.total_expired.load(Ordering::Relaxed),
        })
    }
}
