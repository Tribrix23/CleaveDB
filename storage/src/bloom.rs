//! Bloom filter implementation with AVX2 acceleration.

extern "C" {
    fn bloom_probe_avx2(filter: *const u8, hashes: *const u32, n: usize, results: *mut u8);
}

/// A Bloom filter using a bit array.
pub struct BloomFilter {
    bits: Vec<u8>,
    num_bits: usize,
}

impl BloomFilter {
    /// Creates a new BloomFilter with `num_bits` bits.
    /// `num_bits` MUST be a power of 2 (e.g. 1024, 2048, 4096).
    pub fn new(num_bits: usize) -> Self {
        assert!(num_bits > 0 && (num_bits & (num_bits - 1)) == 0, "num_bits must be a power of 2");
        // Allocate 4 extra bytes of padding for safe AVX2 gather operations
        let num_bytes = (num_bits + 7) / 8 + 4;
        Self {
            bits: vec![0; num_bytes],
            num_bits,
        }
    }

    /// Adds a hash to the bloom filter. Sets 3 bits.
    pub fn add(&mut self, hash: u32) {
        // Assuming num_bits is a power of 2 like 1024
        let mask = (self.num_bits - 1) as u32;
        let h1 = (hash & mask) as usize;
        let h2 = ((hash >> 10) & mask) as usize;
        let h3 = ((hash >> 20) & mask) as usize;

        self.bits[h1 / 8] |= 1 << (h1 % 8);
        self.bits[h2 / 8] |= 1 << (h2 % 8);
        self.bits[h3 / 8] |= 1 << (h3 % 8);
    }

    /// Probes the bloom filter for a batch of hashes using AVX2.
    pub fn probe_batch(&self, hashes: &[u32]) -> Vec<bool> {
        let mut results = vec![0u8; hashes.len()];
        unsafe {
            bloom_probe_avx2(
                self.bits.as_ptr(),
                hashes.as_ptr(),
                hashes.len(),
                results.as_mut_ptr(),
            );
        }
        results.into_iter().map(|b| b != 0).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bloom_filter() {
        let mut filter = BloomFilter::new(1024);
        filter.add(42);
        filter.add(100);

        let hashes = vec![42, 100, 999, 123];
        let results = filter.probe_batch(&hashes);
        
        assert!(results[0]);
        assert!(results[1]);
    }
}
