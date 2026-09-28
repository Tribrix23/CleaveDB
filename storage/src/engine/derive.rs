use serde_json::Value;
use std::collections::HashMap;

/// Result of document derivation
pub struct Derivation {
    pub text_terms: HashMap<String, u32>, // term -> frequency
    pub numericals: HashMap<String, f64>, // path -> value
    pub bond_edges: Vec<String>,          // extracted GIDs for bonds
}

pub fn derive(body: &Value) -> Derivation {
    let mut derivation = Derivation {
        text_terms: HashMap::new(),
        numericals: HashMap::new(),
        bond_edges: Vec::new(),
    };
    
    fn traverse(val: &Value, path: &str, drv: &mut Derivation) {
        match val {
            Value::String(s) => {
                // Extremely basic tokenization
                for token in s.to_lowercase().split_whitespace() {
                    *drv.text_terms.entry(token.to_string()).or_insert(0) += 1;
                }
                
                // If it looks like a hex GID and the path contains 'bond' or similar, extract it
                // (Very simplified prototype logic)
                if s.len() == 16 && s.chars().all(|c| c.is_ascii_hexdigit()) {
                    drv.bond_edges.push(s.clone());
                }
            }
            Value::Number(n) => {
                if let Some(f) = n.as_f64() {
                    drv.numericals.insert(path.to_string(), f);
                }
            }
            Value::Object(obj) => {
                for (k, v) in obj {
                    let new_path = if path.is_empty() { k.clone() } else { format!("{}.{}", path, k) };
                    traverse(v, &new_path, drv);
                }
            }
            Value::Array(arr) => {
                for (i, v) in arr.iter().enumerate() {
                    let new_path = format!("{}[{}]", path, i);
                    traverse(v, &new_path, drv);
                }
            }
            _ => {}
        }
    }
    
    traverse(body, "", &mut derivation);
    derivation
}
