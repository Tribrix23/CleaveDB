use crate::error::StorageResult;
use crate::engine::Document;

/// Volcano-style execution trait
pub trait ExecutorNode {
    fn open(&mut self) -> StorageResult<()>;
    fn next(&mut self) -> StorageResult<Option<Document>>;
    fn close(&mut self) -> StorageResult<()>;
}

pub struct FullScanNode {
    // cursor: Cursor,
}

impl ExecutorNode for FullScanNode {
    fn open(&mut self) -> StorageResult<()> { Ok(()) }
    fn next(&mut self) -> StorageResult<Option<Document>> { Ok(None) }
    fn close(&mut self) -> StorageResult<()> { Ok(()) }
}

pub struct TextSearchScan {
    // term: String,
    // inverted_index: InvertedIndex,
}

impl ExecutorNode for TextSearchScan {
    fn open(&mut self) -> StorageResult<()> { Ok(()) }
    fn next(&mut self) -> StorageResult<Option<Document>> { Ok(None) }
    fn close(&mut self) -> StorageResult<()> { Ok(()) }
}

pub struct NumericProbe {}
impl ExecutorNode for NumericProbe {
    fn open(&mut self) -> StorageResult<()> { Ok(()) }
    fn next(&mut self) -> StorageResult<Option<Document>> { Ok(None) }
    fn close(&mut self) -> StorageResult<()> { Ok(()) }
}

pub struct BondJoin {
    pub left: Box<dyn ExecutorNode>,
    pub right: Box<dyn ExecutorNode>,
}

impl ExecutorNode for BondJoin {
    fn open(&mut self) -> StorageResult<()> {
        self.left.open()?;
        self.right.open()
    }
    
    fn next(&mut self) -> StorageResult<Option<Document>> {
        // Hash join or nested loop logic goes here
        self.left.next()
    }
    
    fn close(&mut self) -> StorageResult<()> {
        self.left.close()?;
        self.right.close()
    }
}
