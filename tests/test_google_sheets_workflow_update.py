import unittest
from unittest.mock import patch

from aconex.google_sheets import (
    _pending_manifest_step_2_final_numbers,
    _step_2_pending_to_final_numbers,
    _workflow_snapshots,
)


class GoogleSheetsWorkflowUpdateTests(unittest.TestCase):
    def test_only_non_terminated_pending_to_abc_step_2_transitions_trigger_mail(self):
        before_rows = [
            {"workflow_id": "1", "workflow_number": "WF-000001", "step_2_review_status": ""},
            {"workflow_id": "2", "workflow_number": "WF-000002", "step_2_review_status": "pending"},
            {"workflow_id": "3", "workflow_number": "WF-000003", "step_2_review_status": "A-Approved"},
        ]
        after_rows = [
            {
                "workflow_id": "1",
                "workflow_number": "WF-000001",
                "step_2_review_status": "B-Approved with comments",
                "review_status": "B-Approved with comments",
            },
            {
                "workflow_id": "2",
                "workflow_number": "WF-000002",
                "step_2_review_status": "C-Reject",
                "review_status": "Terminate",
            },
            {
                "workflow_id": "3",
                "workflow_number": "WF-000003",
                "step_2_review_status": "B-Approved with comments",
                "review_status": "B-Approved with comments",
            },
        ]
        self.assertEqual(
            _step_2_pending_to_final_numbers(
                _workflow_snapshots(before_rows),
                after_rows,
                {"WF-000001", "WF-000002", "WF-000003"},
            ),
            {"WF-000001"},
        )

    @patch("aconex.google_sheets.pending_manifest_workflows")
    @patch("aconex.google_sheets.load_workflows")
    def test_pending_manifest_recovers_mail_trigger_after_failed_run(
        self, load_workflows, pending_manifest
    ):
        load_workflows.return_value = [
            {"workflow_number": "WF-000010", "review_status": "A-Approved"}
        ]
        pending_manifest.return_value = [
            {
                "workflow_number": "WF-000010",
                "events": [{
                    "kind": "status",
                    "old": {"step_2_review_status": "pending"},
                    "new": {
                        "step_2_review_status": "A-Approved",
                        "review_status": "A-Approved",
                    },
                }],
            }
        ]
        self.assertEqual(_pending_manifest_step_2_final_numbers(), {"WF-000010"})


if __name__ == "__main__":
    unittest.main()
