use std::collections::HashMap;

pub struct HyperLogLog {
    registers: Vec<u8>,
    b: usize,
    m: usize,
}

impl HyperLogLog {
    pub fn new(b: usize) -> Self {
        let m = 1 << b;
        Self {
            registers: vec![0; m],
            b,
            m,
        }
    }

    pub fn add(&mut self, hash: u64) {
        let idx = (hash >> (64 - self.b)) as usize;
        let mut w = hash << self.b;
        let mut count = 1;
        while w & 0x8000_0000_0000_0000 == 0 && count <= 64 - self.b as u8 {
            w <<= 1;
            count += 1;
        }
        if count > self.registers[idx] {
            self.registers[idx] = count;
        }
    }

    pub fn count(&self) -> u64 {
        let mut z = 0.0;
        let mut zeros = 0;
        for &r in &self.registers {
            z += 2.0f64.powi(-(r as i32));
            if r == 0 {
                zeros += 1;
            }
        }
        z = 1.0 / z;

        let alpha_m = match self.m {
            16 => 0.673,
            32 => 0.697,
            64 => 0.709,
            _ => 0.7213 / (1.0 + 1.079 / (self.m as f64)),
        };

        let m_f = self.m as f64;
        let mut e = alpha_m * m_f * m_f * z;

        if e <= 2.5 * m_f {
            if zeros > 0 {
                e = m_f * (m_f / zeros as f64).ln();
            }
        } else if e > (1.0 / 30.0) * 2.0f64.powi(32) {
            e = -2.0f64.powi(32) * (1.0 - e / 2.0f64.powi(32)).ln();
        }

        e as u64
    }
}

pub struct Histogram {
    num_buckets: usize,
    boundaries: Vec<f64>,
}

impl Histogram {
    pub fn new(num_buckets: usize) -> Self {
        Self {
            num_buckets,
            boundaries: Vec::new(),
        }
    }

    pub fn build(&mut self, sorted_values: &[f64]) {
        if sorted_values.is_empty() {
            return;
        }
        let n = sorted_values.len();
        let num_b = self.num_buckets.max(1);
        self.boundaries.clear();
        for i in 0..=num_b {
            let mut idx = (i * n) / num_b;
            if idx >= n {
                idx = n - 1;
            }
            self.boundaries.push(sorted_values[idx]);
        }
    }

    pub fn estimate_selectivity(&self, low: f64, high: f64) -> f64 {
        if self.boundaries.is_empty() {
            return 0.0;
        }
        
        let num_buckets = self.boundaries.len() - 1;
        if num_buckets == 0 {
            return 0.0;
        }
        
        let mut fraction_sum = 0.0;
        
        for i in 0..num_buckets {
            let b_low = self.boundaries[i];
            let b_high = self.boundaries[i+1];
            
            if low > b_high || high < b_low {
                continue;
            }
            if b_low >= low && b_high <= high {
                fraction_sum += 1.0;
            } else {
                let overlap_low = b_low.max(low);
                let overlap_high = b_high.min(high);
                let bucket_range = b_high - b_low;
                if bucket_range > 0.0 {
                    fraction_sum += (overlap_high - overlap_low) / bucket_range;
                } else if overlap_low <= overlap_high {
                    fraction_sum += 1.0;
                }
            }
        }
        fraction_sum / (num_buckets as f64)
    }
}

pub struct StatsManager {
    hlls: HashMap<String, HyperLogLog>,
    histograms: HashMap<String, Histogram>,
    values: HashMap<String, Vec<f64>>,
}

impl StatsManager {
    pub fn new() -> Self {
        Self {
            hlls: HashMap::new(),
            histograms: HashMap::new(),
            values: HashMap::new(),
        }
    }

    pub fn refresh_stats(&mut self) {
        println!("Refreshing stats...");
        for (field, vals) in &mut self.values {
            vals.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let mut hist = Histogram::new(10);
            hist.build(vals);
            self.histograms.insert(field.clone(), hist);
        }
    }

    pub fn add_value(&mut self, field: &str, value: f64) {
        self.values.entry(field.to_string()).or_insert_with(Vec::new).push(value);
    }

    pub fn add_hash(&mut self, field: &str, hash: u64) {
        let hll = self.hlls.entry(field.to_string()).or_insert_with(|| HyperLogLog::new(12));
        hll.add(hash);
    }

    pub fn get_cardinality(&self, field: &str) -> u64 {
        if let Some(hll) = self.hlls.get(field) {
            hll.count()
        } else {
            0
        }
    }

    pub fn get_selectivity(&self, field: &str, low: f64, high: f64) -> f64 {
        if let Some(hist) = self.histograms.get(field) {
            hist.estimate_selectivity(low, high)
        } else {
            0.0
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};

    #[test]
    fn test_hll() {
        let mut hll = HyperLogLog::new(12);
        for i in 0..10000 {
            let mut hasher = DefaultHasher::new();
            i.hash(&mut hasher);
            hll.add(hasher.finish());
        }
        let count = hll.count();
        assert!(count > 9000 && count < 11000, "Count {} is not within 10% of 10000", count);
    }

    #[test]
    fn test_histogram() {
        let mut hist = Histogram::new(10);
        let vals: Vec<f64> = (0..1000).map(|x| x as f64).collect();
        hist.build(&vals);
        let sel = hist.estimate_selectivity(100.0, 200.0);
        // Approximately 10% or 0.1, due to 100 elements in range
        assert!((sel - 0.1).abs() < 0.05, "Selectivity {} is not near 0.1", sel);
    }
}
