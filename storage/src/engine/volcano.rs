use crate::error::StorageResult;
use crate::engine::Document;

/// Pull-based iterator trait for Volcano-style query execution.
pub trait ExecutorNode {
    fn open(&mut self) -> StorageResult<()> { Ok(()) }
    fn next(&mut self) -> StorageResult<Option<Document>>;
    fn close(&mut self) -> StorageResult<()> { Ok(()) }
}

// ---------------------------------------------------------------------------
// FullScanNode — iterates pre-fetched key-value pairs, deserializing each
// ---------------------------------------------------------------------------
pub struct FullScanNode {
    entries: Vec<(Vec<u8>, Vec<u8>)>,
    position: usize,
}

impl FullScanNode {
    pub fn new(entries: Vec<(Vec<u8>, Vec<u8>)>) -> Self {
        Self { entries, position: 0 }
    }
}

impl ExecutorNode for FullScanNode {
    fn next(&mut self) -> StorageResult<Option<Document>> {
        while self.position < self.entries.len() {
            let (_key, value) = &self.entries[self.position];
            self.position += 1;
            if let Ok(doc) = Document::from_msgpack(value) {
                return Ok(Some(doc));
            }
            // skip entries that fail deserialization
        }
        Ok(None)
    }
}

// ---------------------------------------------------------------------------
// FilterNode — applies a predicate to each document from a child node
// ---------------------------------------------------------------------------
pub struct FilterNode {
    child: Box<dyn ExecutorNode>,
    field: String,
    op: String,
    value: serde_json::Value,
}

impl FilterNode {
    pub fn new(child: Box<dyn ExecutorNode>, field: String, op: String, value: serde_json::Value) -> Self {
        Self { child, field, op, value }
    }

    fn matches(&self, doc: &Document) -> bool {
        let doc_val = match doc.body.get(&self.field) {
            Some(v) => v,
            None => return false,
        };

        // Numeric comparison
        if let (Some(doc_num), Some(filter_num)) = (as_f64(doc_val), as_f64(&self.value)) {
            return match self.op.as_str() {
                ">"  => doc_num > filter_num,
                ">=" => doc_num >= filter_num,
                "<"  => doc_num < filter_num,
                "<=" => doc_num <= filter_num,
                "="  | "==" => (doc_num - filter_num).abs() < f64::EPSILON,
                "!=" => (doc_num - filter_num).abs() >= f64::EPSILON,
                _ => false,
            };
        }

        // String equality
        if let (Some(doc_str), Some(filter_str)) = (doc_val.as_str(), self.value.as_str()) {
            return match self.op.as_str() {
                "="  | "==" => doc_str == filter_str,
                "!=" => doc_str != filter_str,
                _ => false,
            };
        }

        false
    }
}

impl ExecutorNode for FilterNode {
    fn next(&mut self) -> StorageResult<Option<Document>> {
        while let Some(doc) = self.child.next()? {
            if self.matches(&doc) {
                return Ok(Some(doc));
            }
        }
        Ok(None)
    }
}

// ---------------------------------------------------------------------------
// TextSearchScanNode — returns pre-scored documents from text search results
// ---------------------------------------------------------------------------
pub struct TextSearchScanNode {
    results: Vec<(Document, f32)>,
    position: usize,
}

impl TextSearchScanNode {
    pub fn new(mut results: Vec<(Document, f32)>) -> Self {
        // Sort by score descending
        results.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        Self { results, position: 0 }
    }
}

impl ExecutorNode for TextSearchScanNode {
    fn next(&mut self) -> StorageResult<Option<Document>> {
        if self.position < self.results.len() {
            let (doc, _score) = &self.results[self.position];
            self.position += 1;
            Ok(Some(doc.clone()))
        } else {
            Ok(None)
        }
    }
}

// ---------------------------------------------------------------------------
// LimitNode — stops after N documents from child
// ---------------------------------------------------------------------------
pub struct LimitNode {
    child: Box<dyn ExecutorNode>,
    max: usize,
    count: usize,
}

impl LimitNode {
    pub fn new(child: Box<dyn ExecutorNode>, max: usize) -> Self {
        Self { child, max, count: 0 }
    }
}

impl ExecutorNode for LimitNode {
    fn next(&mut self) -> StorageResult<Option<Document>> {
        if self.count >= self.max {
            return Ok(None);
        }
        if let Some(doc) = self.child.next()? {
            self.count += 1;
            Ok(Some(doc))
        } else {
            Ok(None)
        }
    }
}

// ---------------------------------------------------------------------------
// TopKNode — collects all from child, sorts, returns top K
// ---------------------------------------------------------------------------
pub struct TopKNode {
    child: Box<dyn ExecutorNode>,
    k: usize,
    sort_field: String,
    ascending: bool,
    buffer: Vec<Document>,
    position: usize,
    collected: bool,
}

impl TopKNode {
    pub fn new(child: Box<dyn ExecutorNode>, k: usize, sort_field: String, ascending: bool) -> Self {
        Self { child, k, sort_field, ascending, buffer: Vec::new(), position: 0, collected: false }
    }

    fn collect_and_sort(&mut self) -> StorageResult<()> {
        while let Some(doc) = self.child.next()? {
            self.buffer.push(doc);
        }
        let field = self.sort_field.clone();
        let asc = self.ascending;
        self.buffer.sort_by(|a, b| {
            let va = a.body.get(&field).and_then(|v| as_f64(v)).unwrap_or(0.0);
            let vb = b.body.get(&field).and_then(|v| as_f64(v)).unwrap_or(0.0);
            if asc { va.partial_cmp(&vb).unwrap_or(std::cmp::Ordering::Equal) }
            else   { vb.partial_cmp(&va).unwrap_or(std::cmp::Ordering::Equal) }
        });
        self.buffer.truncate(self.k);
        self.collected = true;
        Ok(())
    }
}

impl ExecutorNode for TopKNode {
    fn next(&mut self) -> StorageResult<Option<Document>> {
        if !self.collected {
            self.collect_and_sort()?;
        }
        if self.position < self.buffer.len() {
            let doc = self.buffer[self.position].clone();
            self.position += 1;
            Ok(Some(doc))
        } else {
            Ok(None)
        }
    }
}

// ---------------------------------------------------------------------------
// BondJoinNode — nested loop join via bond field lookup
// ---------------------------------------------------------------------------
pub struct BondJoinNode {
    left: Box<dyn ExecutorNode>,
    bond_field: String,
    right_entries: std::collections::HashMap<String, Document>,
    pending: Option<(Document, Document)>,
}

impl BondJoinNode {
    pub fn new(left: Box<dyn ExecutorNode>, bond_field: String, right_kv: Vec<(Vec<u8>, Vec<u8>)>) -> Self {
        let mut right_entries = std::collections::HashMap::new();
        for (_k, v) in right_kv {
            if let Ok(doc) = Document::from_msgpack(&v) {
                right_entries.insert(doc.gid.clone(), doc);
            }
        }
        Self { left, bond_field, right_entries, pending: None }
    }
}

impl ExecutorNode for BondJoinNode {
    fn next(&mut self) -> StorageResult<Option<Document>> {
        while let Some(left_doc) = self.left.next()? {
            if let Some(ref_val) = left_doc.body.get(&self.bond_field) {
                let ref_id = match ref_val.as_str() {
                    Some(s) => s.to_string(),
                    None => ref_val.to_string().trim_matches('"').to_string(),
                };
                if let Some(right_doc) = self.right_entries.get(&ref_id) {
                    // Merge right doc fields into left doc body
                    let mut merged = left_doc.clone();
                    if let serde_json::Value::Object(ref right_map) = right_doc.body {
                        if let serde_json::Value::Object(ref mut left_map) = merged.body {
                            for (k, v) in right_map {
                                left_map.entry(format!("_joined_{}", k)).or_insert(v.clone());
                            }
                        }
                    }
                    return Ok(Some(merged));
                }
            }
        }
        Ok(None)
    }
}

// ---------------------------------------------------------------------------
fn as_f64(val: &serde_json::Value) -> Option<f64> {
    match val {
        serde_json::Value::Number(n) => n.as_f64(),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn make_doc(gid: &str, body: serde_json::Value) -> Document {
        let doc = Document::new("test", body, Some(gid));
        doc
    }

    fn make_entries(docs: &[Document]) -> Vec<(Vec<u8>, Vec<u8>)> {
        docs.iter()
            .map(|d| (d.gid.as_bytes().to_vec(), d.to_msgpack().unwrap()))
            .collect()
    }

    #[test]
    fn test_full_scan() {
        let docs: Vec<Document> = (0..5)
            .map(|i| make_doc(&format!("d{i}"), json!({"val": i, "name": format!("doc{i}")})))
            .collect();
        let entries = make_entries(&docs);
        let mut node = FullScanNode::new(entries);
        let mut count = 0;
        while let Ok(Some(_)) = node.next() { count += 1; }
        assert_eq!(count, 5);
    }

    #[test]
    fn test_filter_node() {
        let docs: Vec<Document> = (0..10)
            .map(|i| make_doc(&format!("d{i}"), json!({"total": i * 25})))
            .collect();
        let entries = make_entries(&docs);
        let scan = Box::new(FullScanNode::new(entries));
        let mut filter = FilterNode::new(scan, "total".into(), ">".into(), json!(100));
        let mut results = vec![];
        while let Ok(Some(doc)) = filter.next() { results.push(doc); }
        // total values: 0,25,50,75,100,125,150,175,200,225 — 5 are > 100
        assert_eq!(results.len(), 5);
    }

    #[test]
    fn test_limit_node() {
        let docs: Vec<Document> = (0..10)
            .map(|i| make_doc(&format!("d{i}"), json!({"val": i})))
            .collect();
        let entries = make_entries(&docs);
        let scan = Box::new(FullScanNode::new(entries));
        let mut limit = LimitNode::new(scan, 3);
        let mut count = 0;
        while let Ok(Some(_)) = limit.next() { count += 1; }
        assert_eq!(count, 3);
    }

    #[test]
    fn test_topk_node() {
        let docs: Vec<Document> = (0..10)
            .map(|i| make_doc(&format!("d{i}"), json!({"score": i * 10})))
            .collect();
        let entries = make_entries(&docs);
        let scan = Box::new(FullScanNode::new(entries));
        let mut topk = TopKNode::new(scan, 3, "score".into(), false);
        let mut results = vec![];
        while let Ok(Some(doc)) = topk.next() { results.push(doc); }
        assert_eq!(results.len(), 3);
        // Top 3 scores descending: 90, 80, 70
        let scores: Vec<f64> = results.iter()
            .map(|d| d.body.get("score").unwrap().as_f64().unwrap())
            .collect();
        assert_eq!(scores, vec![90.0, 80.0, 70.0]);
    }
}
