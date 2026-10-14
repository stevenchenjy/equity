from __future__ import annotations

import copy
import json
import tempfile
import hashlib
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sec_acceptance import (make_acceptance_record, reconcile_current_acceptance_records,
    AcceptanceReconciliationError, write_acceptance_index, build_acceptance_index)
from sec_acceptance_corrections import (CorrectionError, PROOFS_REL, CORRECTIONS_REL,
    make_correction, retain_proof, write_corrections, load_corrections,
    corrected_record, reconcile_with_corrections, correct_filings)
from sec_acceptance_corrections import retained_receipt_clock_valid


class HeaderCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.accession = '0001045810-26-000078'
        self.url = 'https://data.sec.gov/submissions/CIK0001045810.json'
        self.old = make_acceptance_record(accession_number=self.accession, ticker='NVDA', cik='1045810',
            filing_date='2026-09-03', accepted_at='2026-09-03T08:03:56Z', source_url=self.url)
        self.observed = make_acceptance_record(**{k:v for k,v in self.old.items() if k not in {'accepted_at','record_sha256'}},
            accepted_at='2026-09-03T16:03:56Z')
        self.clock = '20260903080356'
        self.sub = {'cik':1045810, 'tickers':['NVDA'], 'name':'NVIDIA CORP', 'filings':{'recent':{
            'accessionNumber':[self.accession], 'form':['8-K'], 'filingDate':['2026-09-03'],
            'acceptanceDateTime':['2026-09-03T16:03:56Z']}}}
        self.prefix = 'https://www.sec.gov/Archives/edgar/data/1045810/000104581026000078/' + self.accession

    def sources(self, *, clock=None, index_clock='2026-09-03 08:03:56', sub=None, observed_at='2026-09-04T13:00:00Z'):
        header = f'<PRE>&lt;SEC-HEADER&gt;{self.accession}\n&lt;ACCEPTANCE-DATETIME&gt;{clock or self.clock}\nACCESSION NUMBER:\t{self.accession}\nCONFORMED SUBMISSION TYPE:\t8-K\nFILED AS OF DATE:\t20260903\nFILER:\n COMPANY CONFORMED NAME:\tNVIDIA CORP\n CENTRAL INDEX KEY:\t0001045810\nFILING VALUES:\n&lt;/SEC-HEADER&gt;</PRE>'
        index = f'<strong>Form 8-K</strong>{self.accession}<a href="?CIK=0001045810">CIK</a><div class="infoHead">Filing Date</div><div class="info">2026-09-03</div><div class="infoHead">Accepted</div><div class="info">{index_clock}</div>'
        return {kind: retain_proof(raw, url=url, observed_at=observed_at, root=self.root)
            for kind, raw, url in [('submissions',json.dumps(sub or self.sub).encode(),self.url),
                ('header',header.encode(),self.prefix+'-index-headers.html'),
                ('index',index.encode(),self.prefix+'-index.html')]}

    def correction(self, **kwargs):
        return make_correction(historical=self.old, observed=self.observed, form='8-K', entity_name='NVIDIA CORP',
            sources=self.sources(**kwargs), root=self.root, admitted_at='2026-09-04T14:00:00Z')

    def test_exact_archive_proof_uses_middle_instant_not_eight_hour_tolerance(self):
        with self.assertRaises(AcceptanceReconciliationError):
            reconcile_current_acceptance_records(historical_records=[self.old],current_records=[self.observed],
                reconciled_at='2026-09-04T14:00:00Z')
        proof = self.correction()
        self.assertEqual(proof['corrected']['accepted_at'],'2026-09-03T12:03:56.000+00:00')
        self.assertEqual(proof['original'],self.old)
        self.assertEqual(proof['observed_submissions'],self.observed)
        self.assertEqual(corrected_record(self.observed,[proof]),proof['corrected'])
        self.assertEqual(reconcile_with_corrections(historical_records=[self.old],current_records=[proof['corrected']],
            reconciled_at='2026-09-04T14:00:00Z',corrections=[proof]),[])
        arbitrary = make_acceptance_record(**{k:v for k,v in self.old.items()if k not in {'accepted_at','record_sha256'}},
            accepted_at='2026-09-03T17:03:56Z')
        with self.assertRaises(CorrectionError): corrected_record(arbitrary,[proof])

    def test_header_and_index_disagreement_is_not_admitted(self):
        with self.assertRaises(CorrectionError): self.correction(index_clock='2026-09-03 12:03:56')

    def test_wrong_current_identity_form_or_clock_is_not_admitted(self):
        for key, wrong in [('cik',1),('name','Different issuer'),('tickers',['MU'])]:
            with self.subTest(key=key):
                changed=copy.deepcopy(self.sub);changed[key]=wrong
                with self.assertRaises(CorrectionError): self.correction(sub=changed)
        for field,wrong in [('form','10-Q'),('filingDate','2026-09-04'),('acceptanceDateTime','2026-09-03T17:03:56Z')]:
            with self.subTest(field=field):
                changed=copy.deepcopy(self.sub);changed['filings']['recent'][field]=[wrong]
                with self.assertRaises(CorrectionError): self.correction(sub=changed)

    def test_bound_bytes_tampering_fails_even_when_declared_header_matches(self):
        sources=self.sources();(self.root/sources['header']['raw_path']).write_text('changed')
        with self.assertRaises(CorrectionError):
            make_correction(historical=self.old,observed=self.observed,form='8-K',entity_name='NVIDIA CORP',
                sources=sources,root=self.root,admitted_at='2026-09-04T14:00:00Z')

    def test_future_observation_or_foreign_provenance_fails(self):
        with self.assertRaises(CorrectionError): self.correction(observed_at='2026-09-05T00:00:00Z')
        sources=self.sources();sources['index']['url']='https://example.com/index.html'
        with self.assertRaises(CorrectionError):
            make_correction(historical=self.old,observed=self.observed,form='8-K',entity_name='NVIDIA CORP',
                sources=sources,root=self.root,admitted_at='2026-09-04T14:00:00Z')

    def test_append_only_chain_preserves_knowledge_time_and_immutable_index(self):
        proof=self.correction()
        path=self.root/'03_source_data/equity_research/sec_submission_acceptance_index.json'
        write_acceptance_index(build_acceptance_index(new_records=[self.old],generated_at='2026-09-04T12:00:00Z'),path)
        old_bytes=path.read_bytes()
        write_corrections(self.root,[proof],[self.old]);artifact=self.root/CORRECTIONS_REL/'sec_acceptance_correction_v1.json'
        first=artifact.read_bytes();write_corrections(self.root,[proof],[self.old])
        self.assertEqual(first,artifact.read_bytes());self.assertEqual(old_bytes,path.read_bytes())
        before=datetime(2026,9,4,13,59,tzinfo=timezone.utc)
        self.assertEqual(load_corrections(self.root,[self.old],as_of=before),[])
        self.assertEqual(len(load_corrections(self.root,[self.old])),1)
        filings=[{'accession_number':self.accession,'form':'8-K','filing_date':'2026-09-03','accepted_at':self.observed['accepted_at']}]
        self.assertEqual(correct_filings(filings,ticker='NVDA',cik=1045810,root=self.root,as_of=before),filings)
        self.assertEqual(correct_filings(filings,ticker='NVDA',cik=1045810,root=self.root)[0]['accepted_at'],proof['corrected']['accepted_at'])

    def test_wrong_original_binding_or_mutated_chain_fails(self):
        proof=self.correction();write_corrections(self.root,[proof],[self.old])
        wrong=copy.deepcopy(self.old);wrong['ticker']='MU'
        with self.assertRaises(Exception):load_corrections(self.root,[wrong])
        path=self.root/CORRECTIONS_REL/'sec_acceptance_correction_v1.json';payload=json.loads(path.read_text());payload['previous_artifact_sha256']='broken';path.write_text(json.dumps(payload))
        with self.assertRaises(CorrectionError):load_corrections(self.root,[self.old])

    def test_retained_signed_source_keeps_original_clock_but_new_admission_requires_truth(self):
        from thesis_evidence import _validate_filing_bytes, ThesisValidationError
        proof=self.correction()
        prefix=f'02_filings/issuer_filings/NVDA/{self.accession}/'
        raw=self.root/(prefix+'primary_document.raw');raw.parent.mkdir(parents=True);raw.write_text('original primary bytes')
        normalized=self.root/(prefix+'normalized_text.txt');normalized.write_text('original normalized bytes')
        source={'source_id':'retained-source','ticker':'NVDA','accession':self.accession,
            'url':f'https://www.sec.gov/Archives/edgar/data/1045810/000104581026000078/nvda.htm',
            'primary_document':'nvda.htm','form':'8-K','published_at':self.old['accepted_at'],
            'fetched_at':'2026-09-03T14:00:00Z','raw_path':raw.relative_to(self.root).as_posix(),
            'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),
            'normalized_path':normalized.relative_to(self.root).as_posix(),
            'normalized_sha256':hashlib.sha256(normalized.read_bytes()).hexdigest()}
        context={'acceptance':{self.accession:{**proof['corrected'],'form':'8-K'}},
            'historical_acceptance':{self.accession:self.old},'acceptance_corrections':[proof],
            'artifacts':{'retained-source':source}}
        before=dict(source)
        reviewed=datetime(2026,9,3,15,tzinfo=timezone.utc)
        _validate_filing_bytes(source,'NVDA',reviewed,self.root,context,admission=False)
        self.assertEqual(source,before)
        with self.assertRaises(ThesisValidationError):
            _validate_filing_bytes(source,'NVDA',datetime(2026,9,4,15,tzinfo=timezone.utc),self.root,context,admission=True)
        canonical={**source,'published_at':proof['corrected']['accepted_at']}
        _validate_filing_bytes(canonical,'NVDA',datetime(2026,9,4,15,tzinfo=timezone.utc),self.root,context,admission=True)
        with self.assertRaises(ThesisValidationError):
            _validate_filing_bytes(canonical,'NVDA',reviewed,self.root,context,admission=True)
        too_early={**source,'fetched_at':'2026-09-03T10:00:00Z'}
        with self.assertRaises(ThesisValidationError):
            _validate_filing_bytes(too_early,'NVDA',reviewed,self.root,context,admission=False)

    def test_unchanged_pre_correction_earnings_receipt_uses_exact_proof_only(self):
        proof=self.correction()
        path=self.root/'03_source_data/equity_research/sec_submission_acceptance_index.json'
        write_acceptance_index(build_acceptance_index(new_records=[self.old],generated_at='2026-09-04T12:00:00Z'),path)
        write_corrections(self.root,[proof],[self.old])
        receipt={'accepted_at':self.old['accepted_at'],'fetched_at':'2026-09-03T14:00:00Z'}
        before=copy.deepcopy(receipt)
        args=dict(canonical_accepted_at=proof['corrected']['accepted_at'],ticker='NVDA',cik=1045810,
            accession=self.accession,root=self.root,as_of=datetime(2026,9,4,15,tzinfo=timezone.utc))
        self.assertTrue(retained_receipt_clock_valid(receipt=receipt,**args))
        self.assertEqual(receipt,before)
        for wrong in [dict(receipt,accepted_at='2026-09-03T09:03:56Z'),
                      dict(receipt,fetched_at='2026-09-03T10:00:00Z'),
                      dict(receipt,fetched_at='2026-09-04T14:01:00Z')]:
            self.assertFalse(retained_receipt_clock_valid(receipt=wrong,**args))
        self.assertFalse(retained_receipt_clock_valid(receipt=receipt,**dict(args,ticker='MU')))
        self.assertTrue(retained_receipt_clock_valid(receipt=dict(receipt,accepted_at=proof['corrected']['accepted_at']),**args))


if __name__ == '__main__': unittest.main()
