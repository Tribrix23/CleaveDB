use pyo3::prelude::*;
use crate::engine::Database;

#[pyclass]
pub struct CleaveDB {
    db: Database,
}

#[pymethods]
impl CleaveDB {
    #[new]
    pub fn new(path: &str) -> PyResult<Self> {
        // Mock init for PyO3 wrapper
        Err(pyo3::exceptions::PyNotImplementedError::new_err("Mock prototype: use Rust API"))
    }

    pub fn scoop(&self, bucket: &str, limit: Option<usize>) -> PyResult<Vec<String>> {
        Ok(vec!["dummy_doc".to_string()])
    }
}

#[pymodule]
fn cleavedb3(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CleaveDB>()?;
    Ok(())
}
