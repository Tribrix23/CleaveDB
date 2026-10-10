from typing import List, Optional, Set
from .ast import *
import difflib

class SemanticError:
    def __init__(self, message: str, line: int = 0, column: int = 0, suggestion: str = None):
        self.message = message
        self.line = line
        self.column = column
        self.suggestion = suggestion

class SemanticAnalyzer:
    def __init__(self, known_buckets: Set[str] = None, known_bonds: Set[str] = None, known_indexes: Set[str] = None):
        self.known_buckets = known_buckets or set()
        self.known_bonds = known_bonds or set()
        self.known_indexes = known_indexes or set()
        self.errors: List[SemanticError] = []

    def analyze(self, stmts: list) -> List[SemanticError]:
        self.errors = []
        for stmt in stmts:
            self._analyze_stmt(stmt)
        return self.errors

    def _analyze_stmt(self, stmt):
        stmt_type = type(stmt).__name__
        if stmt_type in ('ScoopStmt', 'CountStmt', 'DistillStmt', 'PourStmt', 'DrainStmt', 'IndexStmt'):
            if hasattr(stmt, 'bucket'):
                self._check_bucket(stmt.bucket)
                
        if stmt_type in ('BondStmt', 'LinkStmt'):
            if hasattr(stmt, 'from_bucket') and stmt.from_bucket:
                self._check_bucket(stmt.from_bucket)
            elif hasattr(stmt, 'source_gid') and stmt.source_gid and ':' in stmt.source_gid:
                self._check_bucket(stmt.source_gid.split(':', 1)[0])
            if hasattr(stmt, 'to_bucket') and stmt.to_bucket:
                self._check_bucket(stmt.to_bucket)
            elif hasattr(stmt, 'target_gid') and stmt.target_gid and ':' in stmt.target_gid:
                self._check_bucket(stmt.target_gid.split(':', 1)[0])
                
        if stmt_type == 'FollowStmt':
            if hasattr(stmt, 'bond_name') and stmt.bond_name:
                self._check_bond(stmt.bond_name)

    def _check_bucket(self, name: str):
        if not self.known_buckets:
            return
        if name not in self.known_buckets:
            matches = difflib.get_close_matches(name, self.known_buckets)
            suggestion = matches[0] if matches else None
            self.errors.append(SemanticError(f"Unknown bucket '{name}'", suggestion=suggestion))
            
    def _check_bond(self, name: str):
        if not self.known_bonds:
            return
        if name not in self.known_bonds:
            matches = difflib.get_close_matches(name, self.known_bonds)
            suggestion = matches[0] if matches else None
            self.errors.append(SemanticError(f"Unknown bond '{name}'", suggestion=suggestion))
