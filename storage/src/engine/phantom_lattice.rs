use crate::error::StorageResult;
use crate::engine::bucket_bond::Enforcement;
use serde::{Deserialize, Serialize};
use dashmap::DashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

/// A ShadowRecord represents a late-binding bond whose target document has not yet arrived.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct ShadowRecord {
    #[serde(default)]
    pub bond_gid: Option<String>,
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
    /// Invariant: Record MUST be inserted into the concurrent DashMap registry before
    /// incrementing the LatchFilter counter, ensuring any reader observing a positive
    /// filter will find the record in the registry.
    pub fn register_shadow_bond(&self, mut record: ShadowRecord) -> StorageResult<()> {
        record.status = "latched".to_string();
        let target_gid = record.target_gid.clone();

        // Publish the counter before releasing the same shard guard that publishes
        // the record. A resolver/sweeper cannot remove an uncounted record.
        let mut entry = self.latches.entry(target_gid.clone()).or_insert_with(Vec::new);
        entry.push(record);
        self.filter.increment(&target_gid);
        self.total_latched.fetch_add(1, Ordering::Relaxed);

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
        self.resolve_with_clock(target_gid, || std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs())
    }

    fn resolve_with_clock(&self, target_gid: &str, clock: impl FnOnce() -> u64) -> Vec<ShadowRecord> {
        if !self.has_pending_latches(target_gid) {
            return Vec::new();
        }

        if let dashmap::mapref::entry::Entry::Occupied(entry) = self.latches.entry(target_gid.to_owned()) {
            let now = clock(); // Decision time is sampled while holding the shard lock.
            let records = entry.remove();
            let mut resolved = Vec::new();
            for mut record in records {
                self.filter.decrement(target_gid);
                if record.lease_expiry_ts.is_some_and(|deadline| now >= deadline) {
                    self.total_expired.fetch_add(1, Ordering::Relaxed);
                } else {
                    record.status = "fused".to_owned();
                    resolved.push(record);
                }
            }
            self.total_snapped.fetch_add(resolved.len() as u64, Ordering::Relaxed);
            resolved
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
            // Registration may have appended since iter_mut released its guard.
            self.latches.remove_if(&k, |_, records| records.is_empty());
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
#[cfg(test)]
mod correctness_tests {
    use super::*;
    use std::sync::{Arc, Barrier};

    fn record(id: usize, deadline: Option<u64>) -> ShadowRecord {
        ShadowRecord { bond_gid: None, src_gid: format!("source:{id}"), target_gid: "target:1".into(),
            rel_name: "r".into(), enforcement: Enforcement::Firm, created_at_ts: 0,
            lease_expiry_ts: deadline, cascade_delete: false, status: "latched".into() }
    }

    #[test]
    fn resolves_every_source_and_checks_exact_deadline() {
        let lattice = PhantomLattice::new();
        for i in 0..64 { lattice.register_shadow_bond(record(i, Some(100))).unwrap(); }
        let found = lattice.resolve_with_clock("target:1", || 99);
        assert_eq!(found.len(), 64);
        assert!(found.iter().all(|r| r.status == "fused"));
        assert!(!lattice.filter.might_contain("target:1"));
        lattice.register_shadow_bond(record(65, Some(100))).unwrap();
        assert!(lattice.resolve_with_clock("target:1", || 100).is_empty());
        assert_eq!(lattice.stats()["total_expired_bonds"], 1);
    }

    #[test]
    fn concurrent_register_resolve_sweep_conserves_records() {
        for _ in 0..100 {
            let lattice = Arc::new(PhantomLattice::new());
            let barrier = Arc::new(Barrier::new(4));
            std::thread::scope(|scope| {
                for worker in 0..2 {
                    let (lattice, barrier) = (lattice.clone(), barrier.clone());
                    scope.spawn(move || { barrier.wait(); for i in 0..64 {
                        lattice.register_shadow_bond(record(worker * 64 + i, Some(100))).unwrap();
                    }});
                }
                let (l, b) = (lattice.clone(), barrier.clone());
                scope.spawn(move || { b.wait(); for _ in 0..64 { l.resolve_with_clock("target:1", || 99); }});
                barrier.wait();
                for _ in 0..64 { lattice.sweep_expired(100); }
            });
            lattice.sweep_expired(100);
            let stats = lattice.stats();
            assert_eq!(stats["total_snapped_bonds"].as_u64().unwrap() + stats["total_expired_bonds"].as_u64().unwrap(), 128);
            assert_eq!(stats["active_pending_latches"], 0);
            assert!(!lattice.filter.might_contain("target:1"));
        }
    }

    #[test]
    fn soft_without_deadline_survives_sweep() {
        let l = PhantomLattice::new();
        l.register_shadow_bond(record(0, None)).unwrap();
        assert!(l.sweep_expired(u64::MAX).is_empty());
        assert_eq!(l.resolve_with_clock("target:1", || u64::MAX).len(), 1);
    }
}
