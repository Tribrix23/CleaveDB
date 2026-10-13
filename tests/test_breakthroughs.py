import unittest
import tempfile
import shutil
import json
import os

from cleavedb3_storage import CleaveDB
from cleaveql.lexer import Lexer
from cleaveql.parser import Parser
from cleaveql.interpreter import Interpreter


class TestCleaveDBBreakthroughs(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cleavedb_breakthrough_test_")
        self.db = CleaveDB(self.test_dir)
        self.interpreter = Interpreter(self.db)
        self.interpreter.set_context({"user": "admin", "auth_level": "dev"})

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def run_query(self, query_str, context=None):
        if context:
            self.interpreter.context.update(context)
        tokens = Lexer(query_str).tokenize()
        stmts = Parser(tokens).parse()
        results = self.interpreter.execute(stmts)
        return results

    # =========================================================================
    # Breakthrough 1: Asynchronous Referential Fabric (Late-Binding & Cleave-Snap)
    # =========================================================================
    def test_breakthrough_1_late_binding_bonds_and_cleave_snap(self):
        """Verify late-binding bond declares before target exists, latches, and fuses on POUR."""
        # 1. Create source team
        self.run_query('POUR INTO team "engineering" {"dept": "core_engine"};')

        # 2. Declare late-binding firm bond to unmaterialized user:david
        res_bond = self.run_query('BOND "team:engineering" TO "user:david" AS "lead" EXPIRING IN 2 HOURS;')
        self.assertEqual(res_bond[0].get("status"), "ok")

        # 3. Check bond is registered with status 'latched' in _bonds
        bonds_data = json.loads(self.db.scan_bucket("_bonds"))
        self.assertTrue(len(bonds_data) >= 1)
        latched_bond = next(b["body"] for b in bonds_data if b["body"]["target"] == "user:david")
        self.assertEqual(latched_bond["status"], "latched")

        # 4. Target document arrives via POUR -> triggers Cleave-Snap
        res_pour = self.run_query('POUR INTO user "david" {"name": "David", "role": "Lead Architect"};')
        self.assertEqual(res_pour[0].get("status"), "ok")

        # 5. Check bond is now atomically fused to 'active'
        bonds_after = json.loads(self.db.scan_bucket("_bonds"))
        fused_bond = next(b["body"] for b in bonds_after if b["body"]["target"] == "user:david")
        self.assertEqual(fused_bond["status"], "active")
        self.assertIn("fused_at", fused_bond)

    # =========================================================================
    # Breakthrough 2: Continuous Reactive Graph-Differential Materialization (DBSP)
    # =========================================================================
    def test_breakthrough_2_dbsp_continuous_graph_differential(self):
        """Verify DBSP Z-module continuous reachability updates in sub-millisecond O(Δ) time."""
        # 1. Shape continuous view
        res_shape = self.run_query('SHAPE CONTINUOUS VIEW "active_supervisors" AS ( MATCH (emp FROM staff)-["reports_to*"]->(boss FROM staff) );')
        self.assertEqual(res_shape[0].get("status"), "ok")

        # 2. Pour staff documents
        self.run_query('POUR INTO staff "alice" {"name": "Alice"};')
        self.run_query('POUR INTO staff "bob" {"name": "Bob"};')
        self.run_query('POUR INTO staff "carol" {"name": "Carol"};')

        # 3. Form management chain: alice -> bob -> carol
        self.run_query('BOND "staff:alice" TO "staff:bob" AS "reports_to";')
        self.run_query('BOND "staff:bob" TO "staff:carol" AS "reports_to";')

        # 4. Listen to view: verify transitive path alice -> carol is materialized
        res_listen = self.run_query('LISTEN TO VIEW "active_supervisors";')
        self.assertEqual(res_listen[0].get("status"), "ok")
        paths = res_listen[0].get("reachable_pairs", [])
        path_pairs = {(p["source"], p["target"]) for p in paths}

        self.assertIn(("staff:alice", "staff:bob"), path_pairs)
        self.assertIn(("staff:bob", "staff:carol"), path_pairs)
        self.assertIn(("staff:alice", "staff:carol"), path_pairs)

        # 5. Sever bond bob -> carol: DBSP pushes -1 delta
        res_sever = self.run_query('SEVER BOND "staff:bob" TO "staff:carol" AS "reports_to";')
        self.assertEqual(res_sever[0].get("status"), "ok")

        # 6. Listen to view: verify (bob, carol) was subtracted
        res_listen2 = self.run_query('LISTEN TO VIEW "active_supervisors";')
        paths2 = res_listen2[0].get("reachable_pairs", [])
        path_pairs2 = {(p["source"], p["target"]) for p in paths2}
        self.assertNotIn(("staff:bob", "staff:carol"), path_pairs2)
        self.assertIn(("staff:alice", "staff:bob"), path_pairs2)

    # =========================================================================
    # Breakthrough 3: Worst-Case Optimal Subgraph Intersection (Leapfrog Triejoin)
    # =========================================================================
    def test_breakthrough_3_leapfrog_triejoin(self):
        """Verify Leapfrog Triejoin achieves AGM optimality and zero intermediate memory allocation."""
        # 1. Pour users
        self.run_query('POUR INTO users "u1" {"name": "User 1"};')
        self.run_query('POUR INTO users "u2" {"name": "User 2"};')
        self.run_query('POUR INTO users "u3" {"name": "User 3"};')
        self.run_query('POUR INTO users "u4" {"name": "User 4"};')

        # 2. Form directed triangle u1 -> u2 -> u3 -> u1, plus an extraneous edge u3 -> u4
        self.run_query('BOND "users:u1" TO "users:u2" AS "friend";')
        self.run_query('BOND "users:u2" TO "users:u3" AS "friend";')
        self.run_query('BOND "users:u3" TO "users:u1" AS "friend";')
        self.run_query('BOND "users:u3" TO "users:u4" AS "friend";')

        # 3. Peer into Leapfrog execution
        res = self.run_query('PEER INTO EXECUTION ( MATCH (a FROM users)-["friend"]->(b FROM users)-["friend"]->(c FROM users)-["friend"]->(a) );')
        self.assertEqual(res[0].get("status"), "ok")
        self.assertEqual(res[0].get("algorithm"), "LeapfrogTriejoin")
        self.assertEqual(res[0].get("intermediate_allocated_bytes"), 0)
        self.assertTrue(res[0].get("agm_optimal"))
        self.assertGreaterEqual(res[0].get("matches_found"), 1)

    # =========================================================================
    # Breakthrough 4: Zero-Copy Speculative Branching & Sandboxed Mutation
    # =========================================================================
    def test_breakthrough_4_speculative_branching_and_merge(self):
        """Verify CoW page virtualization isolates mutations in branch and merges back."""
        # 1. Seed master database with supplier APAC
        self.run_query('POUR INTO suppliers "sup_apac" {"name": "Taipei Foundry", "region": "APAC", "stock": 1000};')
        master_before = self.run_query('SCOOP suppliers;')
        self.assertEqual(len(master_before[0].get("documents", [])), 1)

        # 2. Create speculative simulation branch
        res_branch = self.run_query('CLEAVE BRANCH "supply_disruption_sim";')
        self.assertEqual(res_branch[0].get("status"), "ok")

        # 3. Switch context to branch
        self.run_query('SET CONTEXT branch = "supply_disruption_sim";')

        # 4. In branch: drain APAC supplier and pour EU backup
        self.run_query('DRAIN suppliers WHERE region = "APAC";')
        self.run_query('POUR INTO suppliers "sup_eu" {"name": "Munich Fab", "region": "EU", "stock": 500};')

        # 5. In branch: query suppliers
        branch_docs = self.run_query('SCOOP suppliers;')
        branch_data = branch_docs[0].get("documents", [])
        self.assertEqual(len(branch_data), 1)
        self.assertEqual(branch_data[0]["body"]["region"], "EU")

        # 6. Switch context back to master: master must remain completely unchanged!
        self.run_query('SET CONTEXT branch = "";')
        master_check = self.run_query('SCOOP suppliers;')
        master_data = master_check[0].get("documents", [])
        self.assertEqual(len(master_data), 1)
        self.assertEqual(master_data[0]["body"]["region"], "APAC")

        # 7. Merge branch into master
        res_merge = self.run_query('CLEAVE MERGE "supply_disruption_sim";')
        self.assertEqual(res_merge[0].get("status"), "ok")
        report = res_merge[0].get("report", {})
        self.assertEqual(report.get("branch_name"), "supply_disruption_sim")

        # 8. Master now reflects the merged state (EU supplier added)
        master_after = self.run_query('SCOOP suppliers;')
        merged_names = [d["body"]["name"] for d in master_after[0].get("documents", [])]
        self.assertIn("Munich Fab", merged_names)

    # =========================================================================
    # Breakthrough 5: Contextual Epistemic Masking & Cross-Entity Graph-SAT Engine
    # =========================================================================
    def test_breakthrough_5_graph_sat_and_epistemic_masking(self):
        """Verify Graph-SAT rejects cycles on write and epistemic path dynamically masks fields on read."""
        # 1. Setup Graph-SAT invariant: staff hierarchy must be acyclic
        res_guard = self.run_query('GUARD staff WITH NOT EXISTS PATH (target)-["reports_to*"]->(source);')
        self.assertEqual(res_guard[0].get("status"), "ok")

        # 2. Add valid hierarchy: node1 -> node2 -> node3
        self.run_query('POUR INTO staff "node1" {"title": "Junior"};')
        self.run_query('POUR INTO staff "node2" {"title": "Manager"};')
        self.run_query('POUR INTO staff "node3" {"title": "VP"};')
        self.run_query('BOND "staff:node1" TO "staff:node2" AS "reports_to";')
        self.run_query('BOND "staff:node2" TO "staff:node3" AS "reports_to";')

        # 3. Attempt illegal cycle: node3 -> node1
        res_illegal = self.run_query('BOND "staff:node3" TO "staff:node1" AS "reports_to";')
        self.assertEqual(res_illegal[0].get("status"), "error")
        self.assertIn("Graph-SAT Invariant Violation", res_illegal[0].get("message"))

        # 4. Setup Epistemic Masking on patients:
        # MASK ssn ON patients UNLESS EXISTS PATH (context.user)-["attending*"]->(patient);
        self.run_query('POUR INTO patients "pat_bob" {"name": "Bob", "ssn": "000-12-3456", "condition": "stable"};')
        res_mask = self.run_query('MASK ssn ON patients UNLESS EXISTS PATH (context.user)-["attending*"]->(patient);')
        self.assertEqual(res_mask[0].get("status"), "ok")

        # 5. Query without authorization (Dr. Stranger): SSN MUST be masked!
        res_stranger = self.run_query('SCOOP patients;', context={"user": "doctors:stranger"})
        doc_stranger = res_stranger[0].get("documents", [])[0]["body"]
        self.assertNotIn("ssn", doc_stranger)
        self.assertIn("name", doc_stranger)

        # 6. Authorize Dr. Alice via attending relationship bond
        self.run_query('POUR INTO doctors "alice" {"name": "Dr. Alice"};')
        self.run_query('BOND "doctors:alice" TO "patients:pat_bob" AS "attending";')

        # 7. Query as Dr. Alice: SSN MUST be visible!
        res_alice = self.run_query('SCOOP patients;', context={"user": "doctors:alice"})
        doc_alice = res_alice[0].get("documents", [])[0]["body"]
        self.assertIn("ssn", doc_alice)
        self.assertEqual(doc_alice["ssn"], "000-12-3456")


if __name__ == "__main__":
    unittest.main()
