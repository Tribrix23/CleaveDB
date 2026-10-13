use std::collections::{HashMap, HashSet, VecDeque};
use serde::{Serialize, Deserialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PathVerificationResult {
    pub authorized: bool,
    pub path_length: Option<usize>,
    pub evaluated_edges: usize,
    pub reason: String,
}

/// Graph-SAT Invariant & Epistemic Path Access Control Engine.
/// Enforces topological acyclicity/reachability invariants on write
/// and evaluates dynamic path-dependent field masking on read.
pub struct GraphSatEngine;

impl GraphSatEngine {
    /// Detects if adding edge (new_src -> new_tgt) creates a forbidden directed cycle.
    pub fn verify_acyclic(existing_edges: &[(String, String)], new_src: &str, new_tgt: &str) -> Result<(), String> {
        if new_src == new_tgt {
            return Err(format!(
                "Graph-SAT Invariant Violation: Self-referential cycle detected on '{}'",
                new_src
            ));
        }

        // Build adjacency graph of existing edges
        let mut adj: HashMap<&str, Vec<&str>> = HashMap::new();
        for (u, v) in existing_edges {
            adj.entry(u.as_str()).or_default().push(v.as_str());
        }

        // Check if there is already a path from new_tgt to new_src (which would form a cycle)
        let mut visited: HashSet<&str> = HashSet::new();
        let mut queue: VecDeque<&str> = VecDeque::new();
        queue.push_back(new_tgt);
        visited.insert(new_tgt);

        while let Some(curr) = queue.pop_front() {
            if curr == new_src {
                return Err(format!(
                    "Graph-SAT Invariant Violation: Edge '{}' -> '{}' creates a forbidden directed cycle via reachability back to '{}'",
                    new_src, new_tgt, new_src
                ));
            }

            if let Some(neighbors) = adj.get(curr) {
                for &nxt in neighbors {
                    if visited.insert(nxt) {
                        queue.push_back(nxt);
                    }
                }
            }
        }

        Ok(())
    }

    /// Evaluates dynamic epistemic authorization: checks if a valid relationship path
    /// connects requester_gid to target_gid within max_depth hops.
    pub fn verify_epistemic_path(
        edges: &[(String, String, String)], // (src, tgt, label)
        requester_gid: &str,
        target_gid: &str,
        allowed_label: &str,
        max_depth: usize,
    ) -> PathVerificationResult {
        if requester_gid == target_gid {
            return PathVerificationResult {
                authorized: true,
                path_length: Some(0),
                evaluated_edges: 0,
                reason: "Self-access identity match".to_string(),
            };
        }

        let mut adj: HashMap<&str, Vec<(&str, &str)>> = HashMap::new();
        for (u, v, lbl) in edges {
            if allowed_label == "*" || lbl == allowed_label {
                adj.entry(u.as_str()).or_default().push((v.as_str(), lbl.as_str()));
            }
        }

        let mut queue: VecDeque<(&str, usize)> = VecDeque::new();
        let mut visited: HashSet<&str> = HashSet::new();
        queue.push_back((requester_gid, 0));
        visited.insert(requester_gid);

        let mut evaluated_edges = 0;

        while let Some((curr, depth)) = queue.pop_front() {
            if depth >= max_depth {
                continue;
            }

            if let Some(neighbors) = adj.get(curr) {
                for &(nxt, _) in neighbors {
                    evaluated_edges += 1;
                    if nxt == target_gid {
                        return PathVerificationResult {
                            authorized: true,
                            path_length: Some(depth + 1),
                            evaluated_edges,
                            reason: format!(
                                "Authorized via {}-hop '{}' path",
                                depth + 1,
                                allowed_label
                            ),
                        };
                    }

                    if visited.insert(nxt) {
                        queue.push_back((nxt, depth + 1));
                    }
                }
            }
        }

        PathVerificationResult {
            authorized: false,
            path_length: None,
            evaluated_edges,
            reason: format!(
                "No valid path of label '{}' exists within depth {}",
                allowed_label, max_depth
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cycle_detection() {
        let edges = vec![
            ("a".into(), "b".into()),
            ("b".into(), "c".into()),
        ];

        // Adding c -> a should be rejected
        let res = GraphSatEngine::verify_acyclic(&edges, "c", "a");
        assert!(res.is_err());

        // Adding c -> d should be allowed
        let res = GraphSatEngine::verify_acyclic(&edges, "c", "d");
        assert!(res.is_ok());
    }

    #[test]
    fn test_epistemic_path() {
        let edges = vec![
            ("doctor:alice".into(), "dept:oncology".into(), "member".into()),
            ("dept:oncology".into(), "patient:bob".into(), "manages".into()),
        ];

        // 2 hops via * label
        let auth = GraphSatEngine::verify_epistemic_path(
            &edges,
            "doctor:alice",
            "patient:bob",
            "*",
            2,
        );
        assert!(auth.authorized);
        assert_eq!(auth.path_length, Some(2));

        // 1 hop should fail
        let auth_short = GraphSatEngine::verify_epistemic_path(
            &edges,
            "doctor:alice",
            "patient:bob",
            "*",
            1,
        );
        assert!(!auth_short.authorized);
    }
}
