import copy
import json
import unittest

from plan_summary import SCHEMA, catalog, matching_summary, source_hash, validate_catalog


class PlanSummaryTests(unittest.TestCase):
    def setUp(self):
        self.plan = dict(ticker='ABC', plan_id='ABC-review', version=1, record_hash='a'*64,
                         reason='Historical close $12.34.', counterargument='No live quote.',
                         purpose=dict(entry_validity='No new entry.', failure_condition='Reassess below $11.00.',
                                      exit_rule='Review by October 2 15:30 ET; no automatic sell.'))
        self.entry = {**{k:self.plan[k] for k in ('ticker','plan_id','version','record_hash')},
                      'source_sha256':source_hash(self.plan),
                      'sections':{k:[dict(label='要点',text='历史信息，仅供复核。')] for k in ('reason','counterargument','conditions')}}
        self.payload = dict(schema_version=SCHEMA, entries=[self.entry])

    def test_exact_source_and_plan_binding_admit_only_matching_summary(self):
        entries = validate_catalog(self.payload, [self.plan])
        self.assertEqual(matching_summary(self.plan,entries),self.entry['sections'])
        for field,value in [('ticker','XYZ'),('plan_id','different'),('version',2),('record_hash','b'*64)]:
            with self.subTest(field=field):
                p={**self.plan,field:value}
                self.assertIsNone(matching_summary(p,entries))

    def test_any_changed_source_field_rejects_old_notes_even_with_same_record_hash(self):
        for field in ('reason','counterargument','entry_validity','failure_condition','exit_rule'):
            with self.subTest(field=field):
                p=copy.deepcopy(self.plan)
                if field in p:p[field]='Changed evidence.'
                else:p['purpose'][field]='Changed condition.'
                self.assertIsNone(matching_summary(p,[self.entry]))
                with self.assertRaisesRegex(ValueError,'summary_source_changed'):
                    validate_catalog(self.payload,[p])

    def test_corrupt_missing_and_wrong_schema_notes_fall_back(self):
        for raw in (None,b'{',b'[]',b'{"schema_version":"old","entries":[]}'):
            self.assertEqual(catalog(raw),[])
        self.assertEqual(catalog(json.dumps(self.payload).encode()),[self.entry])

    def test_empty_oversized_and_malformed_sections_are_not_displayed(self):
        for points in ([],[{'label':'','text':'test'}],[{'label':'valid','text':{}}],
                       [{'label':'x','text':'y'}]*6,[{'label':'x','text':'y'*401}]):
            p=copy.deepcopy(self.payload);p['entries'][0]['sections']['reason']=points
            self.assertEqual(catalog(json.dumps(p).encode()),[])

    def test_duplicate_binding_and_false_version_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate_summary'):
            validate_catalog({**self.payload,'entries':[self.entry,self.entry]})
        p=copy.deepcopy(self.payload);p['entries'][0]['version']=True
        with self.assertRaisesRegex(ValueError,'invalid_summary_version'):validate_catalog(p)
