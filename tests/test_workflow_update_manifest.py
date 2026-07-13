import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from aconex.workflow_update_manifest import (
    load_workflow_update_manifest,
    mark_manifest_sync,
    pending_manifest_workflows,
    record_workflow_changes,
)


class WorkflowUpdateManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "workflow_update_manifest.json"
        self.week_one = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)
        self.week_two = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_same_week_merges_changes_and_resets_only_required_targets(self):
        record_workflow_changes(
            [{
                "workflow_id": "1",
                "workflow_number": "WF-000001",
                "kind": "new",
                "summary": "created",
            }],
            manifest_path=self.path,
            now=self.week_one,
        )
        mark_manifest_sync(
            "google_sheet", ["1"], success=True, manifest_path=self.path, now=self.week_one
        )
        record_workflow_changes(
            [{
                "workflow_id": "1",
                "workflow_number": "WF-000001",
                "kind": "comments",
                "mail_ids": ["mail-1"],
            }],
            manifest_path=self.path,
            now=self.week_one,
        )

        entry = load_workflow_update_manifest(
            manifest_path=self.path, now=self.week_one
        )["workflows"]["1"]
        self.assertEqual(entry["change_types"], ["new", "comments"])
        self.assertEqual(entry["sync"]["google_sheet"]["status"], "pending")
        self.assertEqual(entry["sync"]["docflow"]["status"], "not_required")
        self.assertEqual(len(entry["events"]), 2)

    def test_new_workflow_skips_docflow_until_a_status_change_occurs(self):
        record_workflow_changes(
            [{"workflow_id": "1", "workflow_number": "WF-000001", "kind": "new"}],
            manifest_path=self.path,
            now=self.week_one,
        )
        self.assertEqual(
            pending_manifest_workflows(
                "docflow", manifest_path=self.path, now=self.week_one
            ),
            [],
        )

        record_workflow_changes(
            [{"workflow_id": "1", "workflow_number": "WF-000001", "kind": "status"}],
            manifest_path=self.path,
            now=self.week_one,
        )
        self.assertEqual(
            [entry["workflow_id"] for entry in pending_manifest_workflows(
                "docflow", manifest_path=self.path, now=self.week_one
            )],
            ["1"],
        )

    def test_existing_new_only_manifest_entry_is_removed_from_docflow_queue(self):
        record_workflow_changes(
            [{"workflow_id": "1", "workflow_number": "WF-000001", "kind": "new"}],
            manifest_path=self.path,
            now=self.week_one,
        )
        legacy = json.loads(self.path.read_text())
        legacy["workflows"]["1"]["sync"]["docflow"]["status"] = "pending"
        self.path.write_text(json.dumps(legacy), encoding="utf-8")

        self.assertEqual(
            pending_manifest_workflows(
                "docflow", manifest_path=self.path, now=self.week_one
            ),
            [],
        )
        entry = load_workflow_update_manifest(
            manifest_path=self.path, now=self.week_one
        )["workflows"]["1"]
        self.assertEqual(entry["sync"]["docflow"]["status"], "not_required")

    def test_week_rollover_drops_fully_synced_and_retains_failed(self):
        record_workflow_changes(
            [
                {"workflow_id": "done", "workflow_number": "WF-000001", "kind": "new"},
                {"workflow_id": "retry", "workflow_number": "WF-000002", "kind": "status"},
            ],
            manifest_path=self.path,
            now=self.week_one,
        )
        mark_manifest_sync(
            "google_sheet",
            ["done", "retry"],
            success=True,
            manifest_path=self.path,
            now=self.week_one,
        )
        mark_manifest_sync(
            "docflow",
            ["retry"],
            success=True,
            manifest_path=self.path,
            now=self.week_one,
        )
        mark_manifest_sync(
            "docflow",
            ["retry"],
            success=False,
            error="temporary outage",
            manifest_path=self.path,
            now=self.week_one,
        )

        rolled = load_workflow_update_manifest(
            manifest_path=self.path, now=self.week_two
        )
        self.assertEqual(rolled["week"], "2026-W30")
        self.assertNotIn("done", rolled["workflows"])
        self.assertIn("retry", rolled["workflows"])
        self.assertEqual(rolled["workflows"]["retry"]["carried_from_week"], "2026-W29")
        self.assertEqual(
            [entry["workflow_id"] for entry in pending_manifest_workflows(
                "docflow", manifest_path=self.path, now=self.week_two
            )],
            ["retry"],
        )

    def test_write_is_valid_json_and_leaves_no_temporary_file(self):
        record_workflow_changes(
            [{"workflow_id": "1", "workflow_number": "WF-000001", "kind": "comments"}],
            manifest_path=self.path,
            now=self.week_one,
        )
        self.assertEqual(json.loads(self.path.read_text())["schema_version"], 1)
        temporary_files = list(self.path.parent.glob(f".{self.path.name}.*.tmp"))
        self.assertEqual(temporary_files, [])


if __name__ == "__main__":
    unittest.main()
