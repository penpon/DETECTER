from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from detecter.calibration import config_id_for
from detecter.selection import main, run_final, run_selection, selection_id_for

CONDITIONS = {
    "ufd": {
        "model": "ufd",
        "model_version": "m1",
        "weights_version": "w1",
        "preprocessing_version": "p1",
    },
    "community-forensics-384": {
        "model": "community-forensics-384",
        "model_version": "m2",
        "weights_version": "w2",
        "preprocessing_version": "p2",
    },
    "cure": {
        "model": "cure",
        "model_version": "m3",
        "weights_version": "w3",
        "preprocessing_version": "p3",
    },
}

TUNING_SPEC = [
    ("r1", "r1", "real"),
    ("r2", "r2", "real"),
    ("g1", "g1", "generated"),
    ("g2", "g2", "generated"),
]

SCORES = {
    "ufd": {"r1": 0.1, "r2": 0.2, "g1": 0.9, "g2": 0.8},
    "community-forensics-384": {"r1": 0.1, "r2": 0.2, "g1": 0.6, "g2": 0.5},
    "cure": {"r1": 0.5, "r2": 0.5, "g1": 0.5, "g2": 0.5},
}


def tuning_ledger():
    return [
        {
            "image_id": image_id,
            "sha256": hashlib.sha256(image_id.encode()).hexdigest(),
            "source_group": group,
            "label": label,
            "split": "tuning",
            "history": [],
        }
        for image_id, group, label in TUNING_SPEC
    ]


def tuning_measurements(name):
    ledger = {row["image_id"]: row for row in tuning_ledger()}
    return [
        {
            "image_id": image_id,
            "sha256": ledger[image_id]["sha256"],
            **CONDITIONS[name],
            "preprocessing": {"mode": name},
            "status": "ok",
            "raw_score": SCORES[name][image_id],
            "error": None,
        }
        for image_id in SCORES[name]
    ]


def candidates():
    return {name: tuning_measurements(name) for name in CONDITIONS}


def final_rows(real=2, generated=2):
    ledger = tuning_ledger()
    rows = []
    for row in ledger[:real]:
        rows.append(
            {
                "image_id": f"final-{row['image_id']}",
                "sha256": hashlib.sha256(
                    f"final-{row['image_id']}".encode()
                ).hexdigest(),
                "source_group": f"final-{row['source_group']}",
                "source": "verified-corpus",
                "license": "test",
                "label": "real",
                "split": "evaluation",
                "history": [],
                "camera": "camera-a",
            }
        )
    for row in ledger[2 : 2 + generated]:
        rows.append(
            {
                "image_id": f"final-{row['image_id']}",
                "sha256": hashlib.sha256(
                    f"final-{row['image_id']}".encode()
                ).hexdigest(),
                "source_group": f"final-{row['source_group']}",
                "source": "verified-corpus",
                "license": "test",
                "label": "generated",
                "split": "evaluation",
                "history": [],
                "generator": "gen-a",
            }
        )
    return rows


def final_measurements(rows, real_score=0.1, generated_score=0.9):
    return [
        {
            "image_id": row["image_id"],
            "sha256": row["sha256"],
            **CONDITIONS["ufd"],
            "preprocessing": {"mode": "ufd"},
            "status": "ok",
            "raw_score": real_score if row["label"] == "real" else generated_score,
            "error": None,
        }
        for row in rows
    ]


class SelectionTests(unittest.TestCase):
    def test_selects_highest_detection_then_highest_threshold(self):
        selection = run_selection(tuning_ledger(), candidates())
        self.assertEqual(selection["status"], "selected")
        self.assertEqual(selection["selected"]["name"], "ufd")
        self.assertEqual(selection["selected"]["config"]["threshold"], 0.8)
        self.assertEqual(
            selection["selection_policy"].split("; ")[0], "meet_tuning_targets"
        )
        by_name = {row["name"]: row for row in selection["candidates"]}
        self.assertTrue(by_name["ufd"]["meets_tuning_targets"])
        self.assertTrue(by_name["community-forensics-384"]["meets_tuning_targets"])
        self.assertFalse(by_name["cure"]["meets_tuning_targets"])
        self.assertEqual(by_name["cure"]["status"], "unmet")
        for row in selection["candidates"]:
            self.assertEqual(
                row["condition"],
                CONDITIONS[row["name"]],
            )
            self.assertEqual(row["preprocessing"], {"mode": row["name"]})
            for key in ("generated_detection_rate", "hold_rate", "failure_rate"):
                self.assertIn("numerator", row["tuning_metrics"][key])
                self.assertIn("denominator", row["tuning_metrics"][key])
            self.assertEqual(row["config"]["usage"], "evaluation")
            self.assertIn(row["config"]["status"], {"candidate", "unmet"})
        self.assertEqual(
            selection,
            run_selection(
                list(reversed(tuning_ledger())),
                dict(reversed(list(candidates().items()))),
            ),
        )

    def test_same_tuning_groups_are_required_for_every_candidate(self):
        measurements = tuning_measurements("ufd")[:-1]
        with self.assertRaises(ValueError):
            run_selection(tuning_ledger(), {"ufd": measurements})
        with self.assertRaises(ValueError):
            run_selection(tuning_ledger(), {})

    def test_no_candidate_reports_without_validated_or_production_configs(self):
        tied = {
            name: [
                {**row, "raw_score": 0.5, **CONDITIONS[name]}
                for row in tuning_measurements(name)
            ]
            for name in CONDITIONS
        }
        selection = run_selection(tuning_ledger(), tied)
        self.assertEqual(selection["status"], "no_candidate")
        self.assertIsNone(selection["selected"])
        report = run_final(
            selection, final_rows(), measurements=final_measurements(final_rows())
        )
        self.assertEqual(report["status"], "no_candidate")
        self.assertEqual(report["adoption"]["status"], "no_candidate")
        self.assertFalse(report["adoption"]["decision_applied"])
        self.assertFalse(report["production_config_replaced"])
        for row in selection["candidates"]:
            self.assertNotEqual(row["config"]["status"], "validated")
            self.assertEqual(row["config"]["usage"], "evaluation")

    def test_final_evaluation_freezes_the_selected_config(self):
        selection = run_selection(tuning_ledger(), candidates())
        rows = final_rows()
        report = run_final(selection, rows, measurements=final_measurements(rows))
        self.assertEqual(report["selection"]["candidate"], "ufd")
        self.assertEqual(
            report["selection"]["config_id"], selection["selected"]["config_id"]
        )
        self.assertFalse(report["selection"]["reselected_after_final"])
        self.assertFalse(report["production_config_replaced"])
        evaluation = report["stages"]["evaluation"]["report"]
        self.assertEqual(evaluation["config_id"], selection["selected"]["config_id"])
        self.assertEqual(
            evaluation["breakdowns"]["generator"]["gen-a"]["generated_detection_rate"][
                "numerator"
            ],
            2,
        )

    def test_final_measurements_from_another_model_are_rejected(self):
        selection = run_selection(tuning_ledger(), candidates())
        rows = final_rows()
        measurements = final_measurements(rows)
        for row in measurements:
            row.update(CONDITIONS["cure"])
        report = run_final(selection, rows, measurements=measurements)
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("final_condition_mismatch", report["unverified"])

    def test_tampered_frozen_config_is_not_adopted(self):
        selection = run_selection(tuning_ledger(), candidates())
        tampered = json.loads(json.dumps(selection))
        tampered["selected"]["config"]["threshold"] = 0.99
        rows = final_rows()
        report = run_final(tampered, rows, measurements=final_measurements(rows))
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIn("selection_record_invalid", report["unverified"])
        unmet = json.loads(json.dumps(selection))
        cure = next(row for row in unmet["candidates"] if row["name"] == "cure")
        unmet["selected"] = {
            "name": "cure",
            "config_id": cure["config_id"],
            "tuning_metrics": cure["tuning_metrics"],
            "config": cure["config"],
        }
        unmet["selection_id"] = selection_id_for(
            {k: v for k, v in unmet.items() if k != "selection_id"}
        )
        report = run_final(unmet, rows, measurements=final_measurements(rows))
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertTrue(
            any(
                reason.startswith("frozen_config_invalid")
                for reason in report["unverified"]
            )
        )

    def test_reselected_final_evaluation_requires_fresh_unused_data(self):
        selection = run_selection(tuning_ledger(), candidates())
        frozen_id = selection["selected"]["config_id"]
        ledger = []
        for index in range(3000):
            ledger.append(
                {
                    "image_id": f"real-{index}",
                    "sha256": f"{index:064x}",
                    "source_group": f"real-{index}",
                    "source": "verified-corpus",
                    "license": "test",
                    "label": "real",
                    "split": "evaluation",
                    "history": [],
                    "camera": "camera-a",
                }
            )
        for index in range(30):
            ledger.append(
                {
                    "image_id": f"gen-{index}",
                    "sha256": f"{index + 10000:064x}",
                    "source_group": f"gen-{index}",
                    "source": "verified-corpus",
                    "license": "test",
                    "label": "generated",
                    "split": "evaluation",
                    "history": [],
                    "generator": "gen-a",
                }
            )
        ledger.append(
            {
                "image_id": "edited-0",
                "sha256": "c" * 64,
                "source_group": "edited-0",
                "source": "verified-corpus",
                "license": "test",
                "label": "edited",
                "split": "evaluation",
                "history": [],
                "generator": "gen-a",
                "camera": "camera-a",
            }
        )
        measurements = []
        for row in ledger:
            measurements.append(
                {
                    "image_id": row["image_id"],
                    "sha256": row["sha256"],
                    **CONDITIONS["ufd"],
                    "preprocessing": {"mode": "ufd"},
                    "status": "ok",
                    "raw_score": 0.1 if row["label"] == "real" else 0.9,
                    "error": None,
                }
            )
        comparisons = [
            {
                "image_id": row["image_id"],
                "sha256": row["sha256"],
                "model": model,
                "status": "ok",
            }
            for row in ledger
            for model in ("ufd", "community-forensics-384")
        ]
        derived = []
        for row in ledger:
            derived.extend(
                {
                    "source_image_id": row["image_id"],
                    "source_sha256": row["sha256"],
                    "status": "created",
                    "condition": {"operation": "jpeg", "jpeg_quality": quality},
                }
                for quality in (95, 85, 75)
            )
            derived.extend(
                {
                    "source_image_id": row["image_id"],
                    "source_sha256": row["sha256"],
                    "status": "created",
                    "condition": {"operation": "resize", "long_side": size},
                }
                for size in (1024, 512)
            )
        adopted = run_final(
            selection,
            ledger,
            measurements=measurements,
            comparisons=comparisons,
            derived_conditions=derived,
        )
        self.assertEqual(adopted["status"], "achieved")
        self.assertEqual(adopted["selection"]["config_id"], frozen_id)
        reselected = run_final(
            selection,
            ledger,
            measurements=measurements,
            comparisons=comparisons,
            derived_conditions=derived,
            reselected_after_final=True,
        )
        self.assertEqual(reselected["status"], "insufficient_evidence")
        self.assertEqual(reselected["adoption"]["status"], "evidence_insufficient")
        self.assertIn(
            "reselected_after_final:requires_fresh_unused_data",
            reselected["unverified"],
        )
        self.assertTrue(reselected["selection"]["reselected_after_final"])

    def test_cli_no_candidate_exit_codes(self):
        tied = {
            name: [
                {**row, "raw_score": 0.5, **CONDITIONS[name]}
                for row in tuning_measurements(name)
            ]
            for name in CONDITIONS
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "tuning.jsonl"
            ledger_path.write_text(
                "".join(
                    json.dumps(
                        {
                            **row,
                            "path": f"{row['image_id']}.png",
                            "source": "s",
                            "license": "l",
                        }
                    )
                    + "\n"
                    for row in tuning_ledger()
                )
            )
            candidate_args = []
            for name, rows in tied.items():
                path = root / f"{name}.jsonl"
                path.write_text("".join(json.dumps(row) + "\n" for row in rows))
                candidate_args.extend(["--candidate", f"{name}={path}"])
            selection_path = root / "selection.json"
            self.assertEqual(
                main(
                    [
                        "select",
                        "--tuning-ledger",
                        str(ledger_path),
                        *candidate_args,
                        "--output",
                        str(selection_path),
                    ]
                ),
                1,
            )
            report_path = root / "report.json"
            self.assertEqual(
                main(
                    [
                        "finalize",
                        "--ledger",
                        str(ledger_path),
                        "--selection",
                        str(selection_path),
                        "--output",
                        str(report_path),
                    ]
                ),
                1,
            )
            self.assertEqual(
                json.loads(report_path.read_text())["status"], "no_candidate"
            )

    def test_cli_select_then_finalize_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "tuning.jsonl"
            ledger_path.write_text(
                "".join(
                    json.dumps(
                        {
                            **row,
                            "path": f"{row['image_id']}.png",
                            "source": "s",
                            "license": "l",
                        }
                    )
                    + "\n"
                    for row in tuning_ledger()
                )
            )
            candidate_args = []
            for name in ("ufd", "cure"):
                path = root / f"{name}.jsonl"
                path.write_text(
                    "".join(json.dumps(row) + "\n" for row in tuning_measurements(name))
                )
                candidate_args.extend(["--candidate", f"{name}={path}"])
            selection_path = root / "selection.json"
            self.assertEqual(
                main(
                    [
                        "select",
                        "--tuning-ledger",
                        str(ledger_path),
                        *candidate_args,
                        "--output",
                        str(selection_path),
                    ]
                ),
                0,
            )
            selection = json.loads(selection_path.read_text())
            self.assertEqual(selection["selected"]["name"], "ufd")
            final_path = root / "final.jsonl"
            rows = final_rows()
            final_path.write_text(
                "".join(
                    json.dumps({**row, "path": f"{row['image_id']}.png"}) + "\n"
                    for row in rows
                )
            )
            measurements_path = root / "measurements.jsonl"
            measurements_path.write_text(
                "".join(json.dumps(row) + "\n" for row in final_measurements(rows))
            )
            report_path = root / "report.json"
            self.assertEqual(
                main(
                    [
                        "finalize",
                        "--ledger",
                        str(final_path),
                        "--selection",
                        str(selection_path),
                        "--measurements",
                        str(measurements_path),
                        "--output",
                        str(report_path),
                    ]
                ),
                0,
            )
            report = json.loads(report_path.read_text())
            self.assertEqual(report["selection"]["candidate"], "ufd")
            self.assertFalse(report["production_config_replaced"])
            self.assertEqual(
                report["selection"]["config_id"], selection["selected"]["config_id"]
            )
            before = selection_path.read_bytes()
            rerun_path = root / "report-rerun.json"
            self.assertEqual(
                main(
                    [
                        "finalize",
                        "--ledger",
                        str(final_path),
                        "--selection",
                        str(selection_path),
                        "--measurements",
                        str(measurements_path),
                        "--output",
                        str(rerun_path),
                    ]
                ),
                0,
            )
            # Finalize only writes the report; the frozen selection is unchanged.
            self.assertEqual(selection_path.read_bytes(), before)
            # Frozen evaluation configs are never validated production configs.
            frozen = selection["selected"]["config"]
            self.assertEqual(frozen["usage"], "evaluation")
            self.assertEqual(
                frozen["config_id"], config_id_for({k: v for k, v in frozen.items()})
            )


if __name__ == "__main__":
    unittest.main()
