from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from detecter.core import inspect_c2pa, provisional_verdict, summarize_c2pa


def reader_module(
    *,
    success=(),
    failure=(),
    informational=(),
    source="trainedAlgorithmicMedia",
    action="c2pa.created",
    state="Trusted",
    results=None,
):
    active = {
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": action,
                            "digitalSourceType": f"http://cv.iptc.org/newscodes/digitalsourcetype/{source}",
                        }
                    ]
                },
            }
        ],
    }
    results = (
        results
        if results is not None
        else {
            "activeManifest": {
                "success": [{"code": code} for code in success],
                "failure": [{"code": code} for code in failure],
                "informational": [{"code": code} for code in informational],
            }
        }
    )
    reader = SimpleNamespace(
        json=lambda: json.dumps({"active_manifest": "test"}),
        get_active_manifest=lambda: active,
        get_validation_state=lambda: state,
        get_validation_results=lambda: results,
        close=lambda: None,
    )

    class Context:
        def __init__(self, settings=None):
            pass

        @classmethod
        def from_dict(cls, data):
            return cls()

        def close(self):
            pass

    settings = SimpleNamespace(close=lambda: None)
    return SimpleNamespace(
        Reader=SimpleNamespace(try_create=lambda *args, **kwargs: reader),
        Context=Context,
        Settings=SimpleNamespace(from_dict=lambda data: settings),
    )


class C2paProvenanceTests(unittest.TestCase):
    def test_no_implicit_trust_or_network_fetch(self):
        module = reader_module(
            success=(
                "claimSignature.validated",
                "signingCredential.trusted",
                "assertion.dataHash.match",
            )
        )
        with (
            patch.dict("sys.modules", {"c2pa": module}),
            patch.object(
                module.Context, "from_dict", wraps=module.Context.from_dict
            ) as context_factory,
        ):
            result = inspect_c2pa(Path("synthetic.png"))
        self.assertEqual(result["confirmation_state"], "cryptographically_valid")
        self.assertFalse(result["trusted"])
        settings = context_factory.call_args.args[0]
        self.assertFalse(settings["verify"]["remote_manifest_fetch"])
        self.assertFalse(settings["verify"]["ocsp_fetch"])
        self.assertFalse(settings["verify"]["verify_cert_anchors"])
        self.assertNotIn("trust", settings)

    def test_absent_and_unreadable_anchors_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            Image.new("RGB", (4, 4)).save(path)
            self.assertEqual(inspect_c2pa(path)["confirmation_state"], "absent")
            result = inspect_c2pa(path, trust_anchors=Path(directory) / "missing.pem")
        self.assertEqual(result["confirmation_state"], "unverifiable")
        self.assertIn("FileNotFoundError", result["error"])

    def test_ingredient_history_is_not_the_current_asset_generation_scope(self):
        module = reader_module(
            success=("claimSignature.validated", "assertion.dataHash.match")
        )
        active = module.Reader.try_create().get_active_manifest()
        active["ingredients"] = [{"assertions": active.pop("assertions")}]
        with patch.dict("sys.modules", {"c2pa": module}):
            result = inspect_c2pa(Path("synthetic.png"))
        self.assertEqual(result["generation_scope"], "unknown")
        self.assertFalse(result["ai_source_assertion"])

    def test_structured_checks_distinguish_trust_and_unknown_binding(self):
        cases = [
            (
                "cryptographically_valid",
                False,
                ("claimSignature.validated", "assertion.dataHash.match"),
                (),
                (),
            ),
            (
                "untrusted",
                True,
                ("claimSignature.validated", "assertion.dataHash.match"),
                (),
                ("signingCredential.untrusted",),
            ),
            (
                "binding_unknown",
                True,
                ("claimSignature.validated", "signingCredential.trusted"),
                (),
                (),
            ),
            (
                "unverifiable",
                True,
                ("assertion.dataHash.match", "signingCredential.trusted"),
                ("claimSignature.mismatch",),
                (),
            ),
            (
                "trusted",
                True,
                (
                    "claimSignature.validated",
                    "assertion.dataHash.match",
                    "signingCredential.trusted",
                ),
                (),
                (),
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            anchors = Path(directory) / "anchors.pem"
            anchors.write_text("synthetic-test-anchors")
            Image.new("RGB", (4, 4)).save(path)
            for expected, use_anchors, success, failure, informational in cases:
                with self.subTest(expected=expected):
                    module = reader_module(
                        success=success, failure=failure, informational=informational
                    )
                    with patch.dict("sys.modules", {"c2pa": module}):
                        result = inspect_c2pa(
                            path, trust_anchors=anchors if use_anchors else None
                        )
                    self.assertEqual(result["confirmation_state"], expected)
                    self.assertEqual(result["confirmed"], expected == "trusted")
                    self.assertEqual(result["generation_scope"], "full")

    def test_description_and_ingredient_success_do_not_prove_binding(self):
        module = reader_module(
            results={
                "activeManifest": {
                    "success": [
                        {
                            "code": "claimSignature.validated",
                            "explanation": "assertion.dataHash.match",
                        },
                        {"code": "signingCredential.trusted"},
                        {"code": "assertion.hashedURI.match"},
                    ]
                },
                "ingredientDeltas": [
                    {"success": [{"code": "assertion.dataHash.match"}]}
                ],
            }
        )
        with patch.dict("sys.modules", {"c2pa": module}):
            result = inspect_c2pa(Path("synthetic.png"))
        self.assertEqual(result["binding_state"], "unknown")
        self.assertFalse(result["confirmed"])

    def test_invalid_overall_result_never_becomes_confirmed(self):
        module = reader_module(
            success=(
                "claimSignature.validated",
                "signingCredential.trusted",
                "assertion.dataHash.match",
            ),
            state="Invalid",
        )
        with tempfile.TemporaryDirectory() as directory:
            anchors = Path(directory) / "anchors.pem"
            anchors.write_text("synthetic-test-anchors")
            with patch.dict("sys.modules", {"c2pa": module}):
                result = inspect_c2pa(Path("synthetic.png"), trust_anchors=anchors)
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["confirmation_state"], "unverifiable")

    def test_untrusted_signer_failure_preserves_valid_signature(self):
        module = reader_module(
            success=("claimSignature.validated", "assertion.dataHash.match"),
            failure=("signingCredential.untrusted",),
            state="Invalid",
        )
        with patch.dict("sys.modules", {"c2pa": module}):
            result = inspect_c2pa(Path("synthetic.png"))
        self.assertEqual(result["signature_state"], "valid")
        self.assertEqual(result["confirmation_state"], "untrusted")

    def test_malformed_validation_bucket_never_becomes_confirmed(self):
        module = reader_module(
            results={
                "activeManifest": {
                    "success": [
                        {"code": code}
                        for code in (
                            "claimSignature.validated",
                            "signingCredential.trusted",
                            "assertion.dataHash.match",
                        )
                    ],
                    "failure": "assertion.dataHash.mismatch",
                }
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            anchors = Path(directory) / "anchors.pem"
            anchors.write_text("synthetic-test-anchors")
            with patch.dict("sys.modules", {"c2pa": module}):
                result = inspect_c2pa(Path("synthetic.png"), trust_anchors=anchors)
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["confirmation_state"], "unverifiable")

    def test_independent_cli_records_not_checked_and_ledger_hash_mismatch(self):
        from detecter.c2pa_provenance import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            output = Path(directory) / "records.jsonl"
            Image.new("RGB", (4, 4)).save(path)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        str(path),
                        "--image-id",
                        "image-1",
                        "--skip-c2pa",
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["confirmation_state"], "not_checked")
            self.assertEqual(result["image_id"], "image-1")
            self.assertEqual(len(result["sha256"]), 64)
            self.assertEqual(json.loads(output.read_text()), result)
            with redirect_stdout(io.StringIO()):
                code = main(
                    [
                        str(path),
                        "--image-id",
                        "image-1",
                        "--skip-c2pa",
                        "--sha256",
                        "0" * 64,
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            result = json.loads(output.read_text().splitlines()[1])
            self.assertEqual(result["confirmation_state"], "hash_mismatch")
            self.assertIn("input_sha256_mismatch", result["reasons"])
            self.assertFalse(result["confirmed"])

    def test_partial_edit_has_its_own_scope_even_with_trusted_signature(self):
        module = reader_module(
            success=(
                "claimSignature.validated",
                "signingCredential.trusted",
                "assertion.dataHash.match",
            ),
            source="compositeWithTrainedAlgorithmicMedia",
            action="c2pa.edited",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            anchors = Path(directory) / "anchors.pem"
            anchors.write_text("synthetic-test-anchors")
            Image.new("RGB", (4, 4)).save(path)
            with patch.dict("sys.modules", {"c2pa": module}):
                result = inspect_c2pa(path, trust_anchors=anchors)
        self.assertEqual(result["generation_scope"], "partial")
        self.assertEqual(result["confirmation_state"], "trusted")
        verdict = provisional_verdict(result, {"status": "skipped"})
        self.assertEqual(verdict["generation_scope"], "partial")
        self.assertIn("部分編集", verdict["reason"])

    def test_hash_mismatch_cannot_be_confirmed_even_with_trusted_state(self):
        module = reader_module(
            success=("claimSignature.validated", "signingCredential.trusted"),
            failure=("assertion.dataHash.mismatch",),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            Image.new("RGB", (4, 4)).save(path)
            with patch.dict("sys.modules", {"c2pa": module}):
                result = inspect_c2pa(path)
        self.assertEqual(result["signature_state"], "valid")
        self.assertEqual(result["binding_state"], "mismatch")
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["confirmation_state"], "hash_mismatch")
        self.assertIn("asset_hash_mismatch", result["reasons"])
        summary = summarize_c2pa(result)
        self.assertEqual(
            set(summary),
            {
                "status",
                "validation_state",
                "trust_state",
                "ai_source_types",
                "data_hash",
            },
        )
        self.assertEqual(summary["data_hash"], "mismatch")
        self.assertEqual(summary["validation_state"], "Invalid")
        self.assertEqual(
            provisional_verdict(result, {"status": "ok", "predicted_ai": False})[
                "state"
            ],
            "inconclusive",
        )

    def test_ai_disclosure_is_read_alongside_actions(self):
        module = reader_module(
            success=(
                "claimSignature.validated",
                "signingCredential.trusted",
                "assertion.dataHash.match",
            )
        )
        active = module.Reader.try_create().get_active_manifest()
        active["assertions"].append(
            {
                "label": "c2pa.ai-disclosure",
                "data": {
                    "modelType": "c2pa.types.model.huggingface.transformers",
                    "modelName": "example-model",
                    "modelIdentifier": "pkg:huggingface/example/model@main",
                    "contentProfile": {"humanOversightLevel": "fully_autonomous"},
                    "scientificDomain": ["cs.AI"],
                },
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            anchors = Path(directory) / "anchors.pem"
            anchors.write_text("synthetic-test-anchors")
            with patch.dict("sys.modules", {"c2pa": module}):
                result = inspect_c2pa(Path("synthetic.png"), trust_anchors=anchors)
        self.assertTrue(result["ai_disclosure_assertion"])
        self.assertEqual(
            result["ai_disclosure"],
            [
                {
                    "model_type": "c2pa.types.model.huggingface.transformers",
                    "model_name": "example-model",
                    "model_identifier": "pkg:huggingface/example/model@main",
                    "human_oversight_level": "fully_autonomous",
                    "scientific_domain": ["cs.AI"],
                }
            ],
        )
        # Actions info stays alongside the disclosure.
        self.assertTrue(result["ai_source_assertion"])
        self.assertEqual(result["signature_state"], "valid")
        self.assertEqual(result["binding_state"], "match")
        self.assertEqual(result["generation_scope"], "full")

    def test_disclosure_without_model_type_is_not_an_ai_claim(self):
        module = reader_module(
            success=(
                "claimSignature.validated",
                "signingCredential.trusted",
                "assertion.dataHash.match",
            ),
            source="digitalCreation",
            action="c2pa.created",
        )
        active = module.Reader.try_create().get_active_manifest()
        active["assertions"].append({"label": "c2pa.ai-disclosure", "data": {}})
        with patch.dict("sys.modules", {"c2pa": module}):
            result = inspect_c2pa(Path("synthetic.png"))
        self.assertFalse(result["ai_disclosure_assertion"])
        self.assertEqual(result["ai_disclosure"], [])
        verdict = provisional_verdict(result, {"status": "ok", "predicted_ai": False})
        self.assertEqual(verdict["state"], "no_ai_signal_detected")

    def test_invalid_disclosure_fields_cannot_become_trusted_ai_evidence(self):
        model_type = "c2pa.types.model.onnx"
        invalid_data = (
            {"modelType": "unknown.model.type"},
            {"modelType": model_type, "contentProfile": "fully_autonomous"},
            {
                "modelType": model_type,
                "contentProfile": {"humanOversightLevel": "human"},
            },
            {"modelType": model_type, "scientificDomain": "bad domain"},
            {"modelType": model_type, "scientificDomain": ["bad domain"]},
            {"modelType": model_type, "modelName": 123},
            {"modelType": model_type, "metadata": []},
            {"modelType": model_type, "metadata": {1: "bad"}},
            {"modelType": model_type, "unexpected": True},
        )
        for data in invalid_data:
            with self.subTest(data=data), tempfile.TemporaryDirectory() as directory:
                anchors = Path(directory) / "anchors.pem"
                anchors.write_text("synthetic-test-anchors")
                module = reader_module(
                    success=(
                        "claimSignature.validated",
                        "signingCredential.trusted",
                        "assertion.dataHash.match",
                    ),
                    source="digitalCreation",
                    action="c2pa.created",
                )
                active = module.Reader.try_create().get_active_manifest()
                active["assertions"].append(
                    {"label": "c2pa.ai-disclosure", "data": data}
                )
                with patch.dict("sys.modules", {"c2pa": module}):
                    result = inspect_c2pa(Path("synthetic.png"), trust_anchors=anchors)
                self.assertTrue(result["confirmed"])
                self.assertFalse(result["ai_disclosure_assertion"])
                verdict = provisional_verdict(
                    result, {"status": "ok", "predicted_ai": False}
                )
                self.assertEqual(verdict["state"], "no_ai_signal_detected")

    def test_scientific_domain_scalar_from_spec_example_is_normalized(self):
        from detecter.core import _ai_disclosure_records

        records = _ai_disclosure_records(
            [
                {
                    "label": "c2pa.ai-disclosure",
                    "data": {
                        "modelType": "c2pa.types.model.onnx",
                        "scientificDomain": "astro-ph.CO",
                    },
                }
            ]
        )
        self.assertEqual(records[0]["scientific_domain"], ["astro-ph.CO"])

    def test_ingredient_disclosure_is_not_the_current_asset_claim(self):
        module = reader_module(
            success=("claimSignature.validated", "assertion.dataHash.match")
        )
        active = module.Reader.try_create().get_active_manifest()
        actions = active.pop("assertions")
        active["ingredients"] = [
            {
                "assertions": [
                    *actions,
                    {
                        "label": "c2pa.ai-disclosure",
                        "data": {"modelType": "c2pa.types.model.onnx"},
                    },
                ]
            }
        ]
        with patch.dict("sys.modules", {"c2pa": module}):
            result = inspect_c2pa(Path("synthetic.png"))
        self.assertFalse(result["ai_disclosure_assertion"])
        self.assertEqual(result["ai_disclosure"], [])
        self.assertFalse(result["ai_source_assertion"])

    def test_untrusted_disclosure_is_not_confirmed_evidence(self):
        module = reader_module(
            success=("claimSignature.validated", "assertion.dataHash.match"),
            failure=("signingCredential.untrusted",),
            source="digitalCreation",
            action="c2pa.created",
        )
        active = module.Reader.try_create().get_active_manifest()
        active["assertions"].append(
            {
                "label": "c2pa.ai-disclosure",
                "data": {"modelType": "c2pa.types.model.onnx"},
            }
        )
        with patch.dict("sys.modules", {"c2pa": module}):
            result = inspect_c2pa(Path("synthetic.png"))
        self.assertTrue(result["ai_disclosure_assertion"])
        self.assertFalse(result["ai_source_assertion"])
        self.assertFalse(result["confirmed"])
        verdict = provisional_verdict(result, {"status": "ok", "predicted_ai": False})
        self.assertEqual(verdict["state"], "ai_likely")

    def test_trusted_disclosure_with_low_classifier_marks_conflict(self):
        module = reader_module(
            success=(
                "claimSignature.validated",
                "signingCredential.trusted",
                "assertion.dataHash.match",
            ),
            source="digitalCreation",
            action="c2pa.created",
        )
        active = module.Reader.try_create().get_active_manifest()
        active["assertions"].append(
            {
                "label": "c2pa.ai-disclosure",
                "data": {"modelType": "c2pa.types.model.onnx"},
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            anchors = Path(directory) / "anchors.pem"
            anchors.write_text("synthetic-test-anchors")
            with patch.dict("sys.modules", {"c2pa": module}):
                result = inspect_c2pa(Path("synthetic.png"), trust_anchors=anchors)
        self.assertTrue(result["confirmed"])
        verdict = provisional_verdict(result, {"status": "ok", "predicted_ai": False})
        self.assertEqual(verdict["state"], "ai_evidence_confirmed")
        self.assertTrue(verdict["evidence_conflict"])
        self.assertNotEqual(verdict["state"], "no_ai_signal_detected")
