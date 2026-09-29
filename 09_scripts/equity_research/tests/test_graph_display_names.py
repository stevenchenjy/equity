from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / 'repair_graph_display_names.py'
spec = importlib.util.spec_from_file_location('repair_graph_display_names', MODULE_PATH)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class GraphDisplayNamesTests(unittest.TestCase):
    def fixture(self, root):
        source = '00_project_control/dynamic_weight_policy.md'
        path = root / source
        path.parent.mkdir(parents=True)
        path.write_text('# Equity Research — Dynamic Weight Policy\n\nExisting limits.\n')
        old = repair.OLD_HEADINGS[source]
        nodes = [
            {'id': 'legacy_policy_id', 'label': old, 'norm_label': old.lower(),
             'source_file': source, 'source_location': 'L1', 'community': 1},
            {'id': 'historic_id', 'label': old, 'source_file': '11_archive/original.md',
             'source_location': 'L1', 'community': 2},
            {'id': 'current_file', 'label': 'current_documents.md',
             'source_file': '00_project_control/current_documents.md',
             'source_location': 'L1', 'community': 3},
            {'id': 'unrelated_id', 'label': 'process_current_data',
             'source_file': '09_scripts/process.py', 'source_location': 'L2', 'community': 4},
        ]
        graph = {'nodes': nodes, 'links': [
            {'source': 'legacy_policy_id', 'target': 'historic_id', 'relation': 'references'},
            {'source': 'current_file', 'target': 'unrelated_id', 'relation': 'references'},
        ], 'built_at_commit': 'preserved'}
        labels = {'1': old, '2': old, '3': 'Phase 5R — current document entrypoints',
                  '4': 'Phase 5R-C5 Verification Report'}
        return graph, labels

    def test_source_identity_and_historical_members_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, labels = self.fixture(root)
            original = deepcopy(graph)
            fixed, named, changes = repair.plan_repair(root, graph, labels)
            self.assertEqual(graph, original)
            self.assertEqual(fixed['links'], original['links'])
            self.assertEqual([n['id'] for n in fixed['nodes']], [n['id'] for n in original['nodes']])
            self.assertEqual(fixed['nodes'][1], original['nodes'][1])
            self.assertEqual(named['2'], labels['2'])
            self.assertEqual(named['1'], 'Equity Research — Dynamic Weight Policy')
            self.assertEqual(named['3'], 'current_documents.md')
            self.assertEqual(named['4'], 'process_current_data')
            self.assertEqual(len(changes), 4)
            self.assertEqual(repair.plan_repair(root, fixed, named)[2], [])

    def test_repeated_cache_reuse_cannot_resurrect_current_phase_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, labels = self.fixture(root)
            fixed, named, _ = repair.plan_repair(root, graph, labels)
            # AST updates retain document nodes but reuse numeric cache labels.
            named['4'] = 'Phase 5R AI operating decision'
            again, renamed, changes = repair.plan_repair(root, fixed, named)
            self.assertEqual(again, fixed)
            self.assertEqual(renamed['4'], 'process_current_data')
            self.assertEqual(len(changes), 1)
            self.assertEqual(repair.plan_repair(root, again, renamed)[2], [])

    def test_missing_or_unmigrated_source_is_not_silently_relabelled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, labels = self.fixture(root)
            path = root / '00_project_control/dynamic_weight_policy.md'
            path.write_text('# A different title\n')
            with self.assertRaisesRegex(ValueError, 'has not migrated'):
                repair.plan_repair(root, graph, labels)
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                repair.plan_repair(root, graph, labels)


if __name__ == '__main__':
    unittest.main()
