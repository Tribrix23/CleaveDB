use crate::error::StorageResult;
use crate::engine::Document;

/// Flow rules allow automatic movement/copying of documents based on predicates.
pub struct FlowRule {
    pub name: String,
    pub source_bucket: String,
    pub target_bucket: String,
    pub predicate_field: String,
    pub predicate_op: String,
    pub predicate_val: f64,
    pub action: FlowAction,
}

pub enum FlowAction {
    Move,
    Copy,
}

pub struct FlowManager {
    rules: Vec<FlowRule>,
}

impl FlowManager {
    pub fn new() -> Self {
        Self { rules: Vec::new() }
    }

    pub fn add_rule(&mut self, rule: FlowRule) {
        self.rules.push(rule);
    }

    /// Triggered on document write. Returns target bucket if it should be moved/copied.
    pub fn evaluate(&self, doc: &Document) -> StorageResult<Option<(String, &FlowAction)>> {
        for rule in &self.rules {
            if doc.bucket == rule.source_bucket {
                // Mock evaluation: check if body contains the field
                if let Some(val) = doc.body.get(&rule.predicate_field) {
                    if let Some(num) = val.as_f64() {
                        let matches = match rule.predicate_op.as_str() {
                            ">" => num > rule.predicate_val,
                            ">=" => num >= rule.predicate_val,
                            "<" => num < rule.predicate_val,
                            "<=" => num <= rule.predicate_val,
                            "=" | "==" => (num - rule.predicate_val).abs() < f64::EPSILON,
                            "!=" => (num - rule.predicate_val).abs() >= f64::EPSILON,
                            _ => false,
                        };
                        if matches {
                            return Ok(Some((rule.target_bucket.clone(), &rule.action)));
                        }
                    }
                }
            }
        }
        Ok(None)
    }
}
