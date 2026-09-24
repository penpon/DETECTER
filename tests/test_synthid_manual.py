from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from PIL import Image

from detecter.core import file_sha256


class SynthIdManualTests(unittest.TestCase):
    def test_another_image_hash_is_rejected_without_writing_record(self):
        from detecter.synthid_manual import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            other = root / "other.png"
            output = root / "manual.jsonl"
            Image.new("RGB", (4, 4), "red").save(image)
            Image.new("RGB", (4, 4), "blue").save(other)
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "add",
                        "--image",
                        str(image),
                        "--image-id",
                        "image-001",
                        "--sha256",
                        file_sha256(other),
                        "--state",
                        "not_checked",
                        "--registrant",
                        "operator-1",
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())

    def test_missing_fields_and_contradictory_states_are_rejected(self):
        from detecter.synthid_manual import create_manual_record

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            Image.new("RGB", (4, 4)).save(image)
            valid = {
                "image_id": "image-1",
                "sha256": file_sha256(image),
                "state": "detected",
                "registrant": "operator-1",
                "checked_at": "2026-09-22T12:00:00Z",
                "route": "公式検証画面",
                "evidence": "検出と表示されました。",
            }
            for field in (
                "image_id",
                "sha256",
                "registrant",
                "checked_at",
                "route",
                "evidence",
            ):
                with self.subTest(missing=field), self.assertRaises(ValueError):
                    create_manual_record(image, **{**valid, field: ""})
            for changes in (
                {"state": "not_checked"},
                {"state": "not_detected", "generation_scope": "full"},
                {"state": "unverifiable", "generation_scope": "partial"},
                {"state": "trusted"},
                {"checked_at": "2026-09-22T12:00:00"},
            ):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    create_manual_record(image, **{**valid, **changes})

    def test_all_states_remain_distinct_and_partial_edit_is_preserved(self):
        from detecter.synthid_manual import create_manual_record

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            Image.new("RGB", (4, 4)).save(image)
            common = {
                "image_id": "image-1",
                "sha256": file_sha256(image),
                "registrant": "operator-1",
            }
            for state in ("detected", "not_detected", "unverifiable", "not_checked"):
                with self.subTest(state=state):
                    record = create_manual_record(
                        image,
                        **common,
                        state=state,
                        **(
                            {}
                            if state == "not_checked"
                            else {
                                "checked_at": "2026-09-22T21:00:00+09:00",
                                "route": "公式検証画面",
                                "evidence": "画面の表示を記録しました。",
                            }
                        ),
                    )
                    self.assertEqual(record["state"], state)
                    self.assertFalse(record["automatically_verified"])
                    self.assertEqual(record["generation_scope"], "unknown")
                    self.assertEqual(
                        record["checked_at"],
                        None if state == "not_checked" else "2026-09-22T12:00:00+00:00",
                    )
            partial = create_manual_record(
                image,
                **common,
                state="detected",
                generation_scope="partial",
                checked_at="2026-09-22T12:00:00Z",
                route="公式検証画面",
                evidence="部分編集に透かしを検出しました。",
            )
            self.assertEqual(partial["generation_scope"], "partial")
            self.assertNotIn("label", partial)
            self.assertNotIn("verdict", partial)

    def test_cli_saves_manual_result_bound_to_image_without_confirming_full_generation(
        self,
    ):
        from detecter.synthid_manual import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            evidence = root / "evidence.txt"
            output = root / "manual.jsonl"
            Image.new("RGB", (4, 4), "red").save(image)
            evidence.write_text("画面に透かし検出と表示されました。", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "add",
                        "--image",
                        str(image),
                        "--image-id",
                        "image-001",
                        "--sha256",
                        file_sha256(image),
                        "--state",
                        "detected",
                        "--checked-at",
                        "2026-09-22T12:00:00Z",
                        "--route",
                        "公式検証画面",
                        "--evidence",
                        str(evidence),
                        "--registrant",
                        "operator-1",
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 0)
            record = json.loads(output.read_text())
            self.assertEqual(record["image_id"], "image-001")
            self.assertEqual(record["sha256"], file_sha256(image))
            self.assertEqual(record["state"], "detected")
            self.assertTrue(record["manual"])
            self.assertFalse(record["automatically_verified"])
            self.assertEqual(record["generation_scope"], "unknown")
            self.assertEqual(record["signature_state"], "not_checked")
            self.assertEqual(record["binding_state"], "match")
            self.assertEqual(record["evidence"], evidence.read_text())


def manual_record(image: Path, image_id: str, state: str) -> dict:
    from detecter.synthid_manual import create_manual_record

    arguments: dict = {
        "image_id": image_id,
        "sha256": file_sha256(image),
        "state": state,
        "registrant": "operator-1",
    }
    if state != "not_checked":
        arguments.update(
            {
                "checked_at": "2026-09-22T12:00:00Z",
                "route": "公式検証画面",
                "evidence": "画面の表示を記録しました。",
            }
        )
    return create_manual_record(image, **arguments)


class SynthIdReportLinkTests(unittest.TestCase):
    def test_detected_record_is_shown_without_changing_c2pa_or_verdict(self):
        from detecter.core import analyze_image

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            Image.new("RGB", (8, 8), "red").save(image)
            record = manual_record(image, "image-001", "detected")
            linked = analyze_image(
                image,
                detector=None,
                check_c2pa=False,
                synthid_records=[record],
                image_id="image-001",
            )
            plain = analyze_image(image, detector=None, check_c2pa=False)
            synthid = linked["synthid"]
            self.assertEqual(synthid["status"], "linked")
            self.assertEqual(synthid["state"], "detected")
            self.assertEqual(synthid["checked_at"], record["checked_at"])
            self.assertEqual(synthid["route"], "公式検証画面")
            self.assertEqual(synthid["evidence"], "画面の表示を記録しました。")
            self.assertTrue(synthid["manual"])
            self.assertFalse(synthid["automatically_verified"])
            self.assertEqual(synthid["signature_state"], "not_checked")
            self.assertEqual(linked["c2pa"], plain["c2pa"])
            self.assertEqual(linked["verdict"], plain["verdict"])
            self.assertNotEqual(linked["verdict"]["state"], "ai_evidence_confirmed")

    def test_hash_or_id_mismatch_is_not_linked(self):
        from detecter.core import analyze_image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            other = root / "other.png"
            Image.new("RGB", (8, 8), "red").save(image)
            Image.new("RGB", (8, 8), "blue").save(other)
            record = manual_record(image, "image-001", "detected")
            wrong_hash = {**record, "sha256": file_sha256(other)}
            for records, image_id in (
                ([wrong_hash], "image-001"),
                ([record], "image-002"),
            ):
                with self.subTest(image_id=image_id):
                    result = analyze_image(
                        image,
                        detector=None,
                        check_c2pa=False,
                        synthid_records=records,
                        image_id=image_id,
                    )
                    self.assertEqual(result["synthid"]["status"], "not_linked")
                    self.assertEqual(result["verdict"]["state"], "inconclusive")

    def test_not_detected_does_not_prove_real_and_missing_record_continues(self):
        from detecter.core import analyze_image

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            Image.new("RGB", (8, 8), "red").save(image)
            record = manual_record(image, "image-001", "not_detected")
            linked = analyze_image(
                image,
                detector=None,
                check_c2pa=False,
                synthid_records=[record],
                image_id="image-001",
            )
            self.assertEqual(linked["synthid"]["state"], "not_detected")
            self.assertIn("実写", linked["synthid"]["interpretation"])
            plain = analyze_image(image, detector=None, check_c2pa=False)
            self.assertEqual(linked["verdict"], plain["verdict"])
            self.assertEqual(plain["synthid"]["status"], "not_linked")

    def test_cli_links_manual_file_but_keeps_it_out_of_jev_input(self):
        from detecter.cli import main
        from detecter.core import build_jev_state, file_sha256

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            manual = root / "manual.jsonl"
            Image.new("RGB", (8, 8), "red").save(image)
            record = manual_record(image, str(image.resolve()), "unverifiable")
            manual.write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "analyze-legacy",
                        str(image),
                        "--skip-ufd",
                        "--skip-c2pa",
                        "--synthid-manual",
                        str(manual),
                        "--output",
                        "-",
                    ]
                )
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["synthid"]["status"], "linked")
            self.assertEqual(report["synthid"]["state"], "unverifiable")
            self.assertEqual(report["c2pa"]["status"], "skipped")
            state = build_jev_state(
                report["media"],
                report["c2pa"],
                {"status": "ok"},
                input_variant="original",
            )
            serialized = json.dumps(state)
            self.assertNotIn(file_sha256(image), serialized)
            self.assertNotIn(str(image.resolve()), serialized)
            self.assertNotIn("synthid", state)
            self.assertIn(
                "Manual SynthID results are kept outside this model input.",
                state["limitations"],
            )


if __name__ == "__main__":
    unittest.main()
