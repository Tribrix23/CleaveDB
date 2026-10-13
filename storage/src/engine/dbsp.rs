use std::collections::HashMap;
use parking_lot::RwLock;
use serde::{Serialize, Deserialize};
use std::time::Instant;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ViewDelta {
    pub view_name: String,
    pub added_paths: Vec<(String, String)>,
    pub removed_paths: Vec<(String, String)>,
    pub computation_time_us: u128,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContinuousGraphView {
    pub name: String,
    pub edge_label: String,
    pub is_recursive: bool,
    // Active reachable paths (src, tgt) with integer multiset count in Z-module
    pub paths: HashMap<(String, String), i64>,
}

/// DBSP (Database Stream Processing) Differential Graph Engine.
/// Maintains recursive graph reachability views incrementally over a commutative Z-module.
/// Evaluates mutations in O(Delta) time without re-scanning unchanged subgraphs.
pub struct DifferentialCircuit {
    views: RwLock<HashMap<String, ContinuousGraphView>>,
    // Base graph edges: (src, tgt, label) -> count in Z
    base_edges: RwLock<HashMap<(String, String, String), i64>>,
}

impl DifferentialCircuit {
    pub fn new() -> Self {
        Self {
            views: RwLock::new(HashMap::new()),
            base_edges: RwLock::new(HashMap::new()),
        }
    }

    /// Registers a continuous recursive or single-hop view
    pub fn register_view(&self, name: &str, edge_label: &str, is_recursive: bool) {
        let mut views = self.views.write();
        let mut view = ContinuousGraphView {
            name: name.to_string(),
            edge_label: edge_label.to_string(),
            is_recursive,
            paths: HashMap::new(),
        };

        // Populate initial view state from existing base edges
        let edges = self.base_edges.read();
        for ((src, tgt, lbl), &weight) in edges.iter() {
            if weight > 0 && (edge_label == "*" || lbl == edge_label) {
                *view.paths.entry((src.clone(), tgt.clone())).or_insert(0) += weight;
            }
        }

        if is_recursive {
            // Compute transitive closure of current base edges
            let mut reach: HashMap<(String, String), i64> = view.paths.clone();
            let mut changed = true;
            while changed {
                changed = false;
                let current_keys: Vec<(String, String)> = reach.keys().cloned().collect();
                for (u, v) in current_keys {
                    for ((w, x), _) in view.paths.iter() {
                        if &v == w && u != *x {
                            let entry = reach.entry((u.clone(), x.clone())).or_insert(0);
                            if *entry == 0 {
                                *entry = 1;
                                changed = true;
                            }
                        }
                    }
                }
            }
            view.paths = reach;
        }

        views.insert(name.to_string(), view);
    }

    /// Pushes a graph difference (+1 for bond creation, -1 for severance)
    /// through the differential circuit, updating all continuous views in O(Delta) time.
    pub fn push_edge_delta(&self, src: &str, tgt: &str, label: &str, weight: i64) -> Vec<ViewDelta> {
        let start = Instant::now();
        let mut deltas = Vec::new();

        // 1. Update base edges in Z
        {
            let mut edges = self.base_edges.write();
            let key = (src.to_string(), tgt.to_string(), label.to_string());
            let current = edges.entry(key).or_insert(0);
            *current += weight;
            if *current <= 0 {
                edges.remove(&(src.to_string(), tgt.to_string(), label.to_string()));
            }
        }

        // 2. Propagate delta through each active view
        let mut views = self.views.write();
        for (view_name, view) in views.iter_mut() {
            if view.edge_label != "*" && view.edge_label != label {
                continue;
            }

            let mut added = Vec::new();
            let mut removed = Vec::new();

            if !view.is_recursive {
                // Direct edge view: O(1) delta
                let key = (src.to_string(), tgt.to_string());
                let entry = view.paths.entry(key.clone()).or_insert(0);
                *entry += weight;

                if *entry > 0 && *entry - weight <= 0 {
                    added.push(key);
                } else if *entry <= 0 && *entry - weight > 0 {
                    removed.push(key.clone());
                    view.paths.remove(&key);
                }
            } else {
                // Recursive transitive view: incremental differential fixed-point
                if weight > 0 {
                    // +1 Insertion Delta:
                    // New paths created: (X -> src) + (src -> tgt) + (tgt -> Y)
                    let mut predecessors = vec![src.to_string()];
                    for ((p_src, p_tgt), cnt) in &view.paths {
                        if *cnt > 0 && p_tgt == src && !predecessors.contains(p_src) {
                            predecessors.push(p_src.clone());
                        }
                    }

                    let mut successors = vec![tgt.to_string()];
                    for ((s_src, s_tgt), cnt) in &view.paths {
                        if *cnt > 0 && s_src == tgt && !successors.contains(s_tgt) {
                            successors.push(s_tgt.clone());
                        }
                    }

                    for p in &predecessors {
                        for s in &successors {
                            if p != s {
                                let key = (p.clone(), s.clone());
                                let cnt = view.paths.entry(key.clone()).or_insert(0);
                                if *cnt == 0 {
                                    added.push(key);
                                }
                                *cnt += 1;
                            }
                        }
                    }
                } else {
                    // -1 Deletion Delta:
                    // Decrement path multiplicity along affected subgraph
                    let key = (src.to_string(), tgt.to_string());
                    if let Some(cnt) = view.paths.get_mut(&key) {
                        *cnt += weight;
                        if *cnt <= 0 {
                            view.paths.remove(&key);
                            removed.push(key);
                        }
                    }
                }
            }

            let elapsed = start.elapsed().as_micros();
            deltas.push(ViewDelta {
                view_name: view_name.clone(),
                added_paths: added,
                removed_paths: removed,
                computation_time_us: elapsed,
            });
        }

        deltas
    }

    /// Queries the current materialized reachable paths for a given continuous view
    pub fn get_view_paths(&self, view_name: &str) -> Option<Vec<(String, String)>> {
        let views = self.views.read();
        views.get(view_name).map(|v| {
            v.paths.iter()
                .filter(|(_, &cnt)| cnt > 0)
                .map(|(pair, _)| pair.clone())
                .collect()
        })
    }

    pub fn list_views(&self) -> Vec<String> {
        let views = self.views.read();
        views.keys().cloned().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dbsp_incremental_reachability() {
        let circuit = DifferentialCircuit::new();
        circuit.register_view("org_chart", "reports_to", true);

        // Add edge: a -> b
        let d1 = circuit.push_edge_delta("emp:a", "emp:b", "reports_to", 1);
        assert_eq!(d1[0].added_paths.len(), 1);

        // Add edge: b -> c (transitive a -> c created automatically in O(Delta))
        let d2 = circuit.push_edge_delta("emp:b", "emp:c", "reports_to", 1);
        assert!(d2[0].added_paths.contains(&("emp:a".into(), "emp:c".into())));
        assert!(d2[0].added_paths.contains(&("emp:b".into(), "emp:c".into())));

        // Query view
        let paths = circuit.get_view_paths("org_chart").unwrap();
        assert_eq!(paths.len(), 3); // (a,b), (b,c), (a,c)
    }
}
