from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import PROJECT_ROOT
from daily_common import canonical_sha256
from investment_reasoning import research_method_template
from test_thesis_evidence import AS_OF, fixture
from thesis_evidence import SCHEMA, ThesisValidationError, evaluate_thesis, seal_review, validate_review, validate_store


def method_fixture(root: Path, record: dict) -> dict:
    """An authored conditional analysis, not calibrated return/probability."""
    from test_valuation_input_bundle import _bundle
    from valuation_input_bundle import seal_bundle
    result = deepcopy(record)
    bundle = _bundle(root, ticker="ABC")
    bundle["records"][0]["inputs"]["share_price"]["period"] = "2026-09-23 close"
    path = root / "04_data/equity_research/valuation_source_review.local.json"
    path.write_text(json.dumps(seal_bundle(bundle)))
    result["valuation"]["status"] = "reviewed_scenarios"
    result["valuation_model"] = {"relative_path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "assumptions_reason": "Company-specific growth and terminal assumptions reviewed.",
        "countercase_reason": "Share compensation reduces per-share outcomes.", "claim_ids": ["growth", "dilution"]}
    method = research_method_template()
    method["price_implied_conditions"].update(status="assessed", summary="Price depends on cash conversion and terminal multiple.",
        method="Conditional scenario sensitivity using the retained model, not observed market consensus.",
        conditions=["Cash conversion must persist for the scenario to hold."], assumptions=["Terminal multiple remains stable."],
        claim_ids=["growth", "dilution"], horizon_years=3, reference_price={"value": 10.0, "date": "2026-09-23"},
        model_reference={key: result["valuation_model"][key] for key in ("relative_path", "sha256")})
    method["differentiated_view"].update(status="hypothesis", summary="Per-share growth may lag headline growth.",
        comparison_basis="price_implied_conditions", claim_ids=["growth", "dilution"],
        falsifier="Cash per share grows faster despite sustained dilution.")
    method["loss_analysis"].update(status="assessed", paths=[{
        "path_id": "cash_dilution", "steps": ["Growth requires more cash", "Equity funding increases shares"],
        "impairment": "Persistent per-share value loss", "early_warning": "Cash conversion and share count diverge",
        "claim_ids": ["growth", "dilution"], "unknowns": ["Funding needs remain uncertain"]}],
        fragile_assumptions=[{"assumption": "Cash conversion holds", "adverse_change": "Capital spending outruns cash receipts",
            "consequence": "Lower per-share value", "claim_ids": ["dilution"], "unknowns": []}],
        shared_exposures=[{"risk_tag": "enterprise_capex", "mechanism": "Shared customer investment cycle",
            "claim_ids": ["growth"], "unknowns": ["No numerical joint-loss estimate"]}])
    result["research_method"] = method
    return seal_review(result)


def consensus_fixture(root: Path) -> dict:
    text = "A survey of 12 analysts estimates next-year revenue growth of 15 percent."
    path = root / "03_source_data/equity_research/retained_consensus.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {"status": "sourced_observation", "summary": "The documented sample expects 15 percent growth.",
        "sample_scope": "12 surveyed analysts; not evidence of all investors' expectations", "claim_ids": [],
        "unknowns": ["Positioning and unsurveyed expectations are not observed."],
        "observation": {"kind": "analyst_consensus", "source_url": "https://example.org/analyst-survey",
            "relative_path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "published_at": "2026-09-23T12:00:00+00:00", "observed_at": "2026-09-24T12:00:00+00:00",
            "char_start": 0, "char_end": len(text), "excerpt": text}}


class InvestmentReasoningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record, self.context = fixture(self.root)

    def validate(self, record, *, now=AS_OF):
        validate_review(seal_review(record), self.root, self.context, now)

    def test_legacy_and_explicit_unknown_remain_usable_without_promoting_authority(self):
        self.validate(self.record)
        record = deepcopy(self.record)
        record["research_method"] = research_method_template()
        self.validate(record)
        record = seal_review(record)
        view = evaluate_thesis({"schema_version": SCHEMA, "records": [record]}, "ABC", AS_OF,
            self.root, context=self.context, incorporation={"status": "incorporated", "latest_report_period_end": "2026-06-30"})
        self.assertEqual(view["status"], "reviewed")
        self.assertEqual(view["valuation_readiness"], "unresolved")
        self.assertFalse(view["recommendation_authority"])
        self.assertFalse(view["automatic_action_allowed"])

    def test_assessed_model_accepts_string_numeric_quote_and_retains_unknown_consensus(self):
        record = method_fixture(self.root, self.record)
        self.validate(record)
        self.assertEqual(record["research_method"]["market_consensus"]["status"], "unknown")

    def test_price_analysis_cannot_substitute_unreviewed_model_wrong_price_or_horizon(self):
        record = method_fixture(self.root, self.record)
        changes = (("reference_price", {"value": 20, "date": "2026-09-23"}),
                   ("reference_price", {"value": 10, "date": "2026-09-25"}),
                   ("reference_price", {"value": True, "date": "2026-09-23"}),
                   ("reference_price", {"value": float("nan"), "date": "2026-09-23"}),
                   ("horizon_years", 0), ("horizon_years", float("inf")),
                   ("model_reference", {"relative_path": "04_data/equity_research/other.json", "sha256": "0"*64}))
        for key, value in changes:
            with self.subTest(key=key, value=value):
                altered = deepcopy(record)
                altered["research_method"]["price_implied_conditions"][key] = value
                with self.assertRaises(ValueError):
                    self.validate(altered)
        altered = deepcopy(record)
        altered["valuation"]["status"] = "unresolved"
        altered["valuation_model"] = None
        with self.assertRaisesRegex(ThesisValidationError, "exact reviewed valuation"):
            self.validate(altered)

    def test_consensus_requires_retained_external_observation_and_scope(self):
        record = method_fixture(self.root, self.record)
        record["research_method"]["market_consensus"] = consensus_fixture(self.root)
        self.validate(record)
        for kind in ("issuer_guidance", "price_implied", "analyst_inference"):
            altered = deepcopy(record)
            altered["research_method"]["market_consensus"]["observation"]["kind"] = kind
            with self.assertRaisesRegex(ThesisValidationError, "not market consensus"):
                self.validate(altered)
        for key, value in (("sample_scope", ""), ("observation", None)):
            altered = deepcopy(record)
            altered["research_method"]["market_consensus"][key] = value
            with self.assertRaises(ThesisValidationError):
                self.validate(altered)

    def test_consensus_rejects_changed_bytes_future_observation_and_path_escape(self):
        record = method_fixture(self.root, self.record)
        record["research_method"]["market_consensus"] = consensus_fixture(self.root)
        for key, value in (("observed_at", "2026-09-25T12:00:00+00:00"),
                           ("relative_path", "03_source_data/equity_research/../../../outside.txt"),
                           ("excerpt", "invented consensus")):
            altered = deepcopy(record)
            altered["research_method"]["market_consensus"]["observation"][key] = value
            with self.assertRaises(ThesisValidationError):
                self.validate(altered)
        receipt = record["research_method"]["market_consensus"]["observation"]
        (self.root / receipt["relative_path"]).write_text("changed content")
        with self.assertRaisesRegex(ThesisValidationError, "consensus source hash"):
            self.validate(record)

    def test_difference_needs_comparison_counterevidence_and_falsifier(self):
        record = method_fixture(self.root, self.record)
        for key, value in (("comparison_basis", "market_consensus"), ("claim_ids", ["growth"]), ("falsifier", "")):
            altered = deepcopy(record)
            altered["research_method"]["differentiated_view"][key] = value
            with self.assertRaises(ThesisValidationError):
                self.validate(altered)

    def test_loss_requires_mechanism_evidence_and_no_invented_probability_field(self):
        record = method_fixture(self.root, self.record)
        for field in ("steps", "early_warning", "claim_ids"):
            altered = deepcopy(record)
            altered["research_method"]["loss_analysis"]["paths"][0][field] = [] if field != "early_warning" else ""
            with self.assertRaises(ThesisValidationError):
                self.validate(altered)
        altered = deepcopy(record)
        altered["research_method"]["loss_analysis"]["paths"][0]["probability"] = 0.2
        with self.assertRaisesRegex(ThesisValidationError, "fields differ"):
            self.validate(altered)
        altered = deepcopy(record)
        altered["research_method"]["loss_analysis"]["shared_exposures"][0]["claim_ids"] = ["nonexistent"]
        with self.assertRaisesRegex(ThesisValidationError, "unknown or duplicate claims"):
            self.validate(altered)

    def test_authored_time_does_not_renew_financial_review_or_due_date(self):
        record = method_fixture(self.root, self.record)
        record["research_method"]["authored_at"] = "2026-09-26T21:00:00+00:00"
        self.validate(record, now="2026-09-26T22:00:00+00:00")
        self.assertEqual(record["reviewed_at"], AS_OF)
        self.assertEqual(record["next_review_at"], self.record["next_review_at"])
        record["research_method"]["authored_at"] = "2026-09-23T21:00:00+00:00"
        with self.assertRaisesRegex(ThesisValidationError, "authored timestamp"):
            validate_store({"schema_version": SCHEMA, "records": [seal_review(record)]})
        record["research_method"]["authored_at"] = "2026-09-27T21:00:00+00:00"
        with self.assertRaisesRegex(ThesisValidationError, "authored timestamp"):
            self.validate(record, now="2026-09-26T22:00:00+00:00")

    def test_later_financial_review_can_carry_exact_method_but_cannot_backdate_edits(self):
        original = method_fixture(self.root, self.record)
        original["research_method"]["authored_at"] = AS_OF
        original = seal_review(original)
        later = deepcopy(original)
        later.update(version=2, review_id="abc-review-2", reviewed_at="2026-09-26T21:00:00+00:00",
                     supersedes_sha256=original["record_sha256"])
        later = seal_review(later)
        validate_store({"schema_version": SCHEMA, "records": [original, later]})
        self.validate(later, now="2026-09-26T22:00:00+00:00")
        self.assertEqual(later["research_method"]["authored_at"], AS_OF)
        later["research_method"]["differentiated_view"]["summary"] = "A newly revised hypothesis."
        with self.assertRaisesRegex(ThesisValidationError, "cannot backdate"):
            validate_store({"schema_version": SCHEMA, "records": [original, seal_review(later)]})

    def test_carried_method_cannot_reuse_ids_with_later_or_changed_evidence(self):
        original = method_fixture(self.root, self.record)
        original["research_method"]["authored_at"] = AS_OF
        original = seal_review(original)
        later = deepcopy(original)
        later.update(version=2, review_id="abc-review-2", reviewed_at="2026-09-26T21:00:00+00:00",
                     supersedes_sha256=original["record_sha256"])
        later["sources"][0]["fetched_at"] = "2026-09-25T20:00:00+00:00"
        with self.assertRaisesRegex(ThesisValidationError, "after authorship"):
            self.validate(later, now="2026-09-26T22:00:00+00:00")
        later["sources"] = deepcopy(original["sources"])
        later["claims"][0]["statement"] = "A newly authored reinterpretation of the old evidence."
        with self.assertRaisesRegex(ThesisValidationError, "cannot backdate"):
            validate_store({"schema_version": SCHEMA, "records": [original, seal_review(later)]})
        later["claims"] = deepcopy(original["claims"])
        later["claims"].append({**deepcopy(original["claims"][0]), "claim_id": "unrelated_new_claim"})
        validate_store({"schema_version": SCHEMA, "records": [original, seal_review(later)]})

    def test_new_method_on_preserved_financial_review_requires_explicit_authorship(self):
        original = self.record
        later = deepcopy(original)
        later.update(version=2, review_id="abc-review-2", supersedes_sha256=original["record_sha256"])
        later["research_method"] = research_method_template()
        with self.assertRaisesRegex(ThesisValidationError, "explicit authored_at"):
            validate_store({"schema_version": SCHEMA, "records": [original, seal_review(later)]})
        later["research_method"]["authored_at"] = "2026-09-25T21:00:00+00:00"
        validate_store({"schema_version": SCHEMA, "records": [original, seal_review(later)]})

    def test_current_quote_receipt_binds_exact_model_ancestor_price_and_horizon(self):
        prior = method_fixture(self.root, self.record)
        observation = {"schema_version": "equity_company_valuation_observation_v1",
            "automatic_action_allowed": False,
            "admission": {"ticker": "ABC", "model_sha256": prior["valuation_model"]["sha256"],
                          "status": "admitted_current", "immutable_assumptions": True,
                          "review_record_sha256": prior["record_sha256"]},
            "projection": {"ticker": "ABC", "status": "complete", "current_price": 9.5, "as_of_market_session": "2026-09-25",
                           "metric_interpretation": {"horizon": "Three fiscal years"}}}
        digest = canonical_sha256(observation)
        observation.update(observed_at="2026-09-25T21:00:00+00:00", observation_sha256=digest)
        path = self.root / "04_data/equity_research/company_valuation_observations.local" / (digest + ".json")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(observation))
        record = deepcopy(prior)
        record.update(version=2, review_id="abc-review-2", supersedes_sha256=prior["record_sha256"])
        method = record["research_method"]
        method["authored_at"] = "2026-09-26T21:00:00+00:00"
        price = method["price_implied_conditions"]
        price["reference_price"] = {"value": 9.5, "date": "2026-09-25"}
        price["observation_reference"] = {"relative_path": str(path.relative_to(self.root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "review_record_sha256": prior["record_sha256"],
            "horizon": "Three fiscal years"}
        record = seal_review(record)
        self.validate(record, now="2026-09-26T22:00:00+00:00")
        validate_store({"schema_version": SCHEMA, "records": [prior, record]})
        for key, value in (("horizon", "One fiscal year"), ("review_record_sha256", "0"*64)):
            altered = deepcopy(record)
            altered["research_method"]["price_implied_conditions"]["observation_reference"][key] = value
            with self.assertRaises(ThesisValidationError):
                self.validate(altered, now="2026-09-26T22:00:00+00:00")
        wrong_ancestor = deepcopy(prior)
        wrong_ancestor["ticker"] = "XYZ"
        wrong_ancestor = seal_review(wrong_ancestor)
        record["supersedes_sha256"] = ""
        record["version"] = 1
        with self.assertRaisesRegex(ThesisValidationError, "earlier same-company"):
            validate_store({"schema_version": SCHEMA, "records": [wrong_ancestor, seal_review(record)]})
        observation["projection"]["current_price"] = 8
        path.write_text(json.dumps(observation))
        record["research_method"]["price_implied_conditions"]["observation_reference"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ThesisValidationError, "observation seal"):
            self.validate(record, now="2026-09-26T22:00:00+00:00")

    def test_cli_template_is_unknown_read_only_and_cannot_apply(self):
        from update_thesis_review import main
        output = io.StringIO()
        with patch("sys.argv", ["update_thesis_review", "--research-method-template"]), redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(output.getvalue())["research_method"], research_method_template())
        with patch("sys.argv", ["update_thesis_review", "--research-method-template", "--apply"]), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                main()


if __name__ == "__main__":
    unittest.main()
