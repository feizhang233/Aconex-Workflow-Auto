import unittest
from types import SimpleNamespace

from aconex.web_workflow_sync import (
    _api_root,
    _docflow_headers,
    _feedback_code,
    _payload_hash,
    _web_payload,
    _workflow_url,
)


class WebWorkflowSyncTests(unittest.TestCase):
    def test_feedback_code_maps_aconex_statuses(self):
        self.assertEqual(_feedback_code("A-Approved"), "A")
        self.assertEqual(_feedback_code("B-Approved with comments"), "B")
        self.assertEqual(_feedback_code("C-Reject"), "C")
        self.assertEqual(_feedback_code(""), "P")

    def test_web_payload_maps_steps_by_configured_reviewer_order(self):
        payload = _web_payload(
            {
                "step_1_review_status": "B-Approved with comments",
                "step_2_review_status": "",
                "review_status": "B-Approved with comments",
            },
            ("UTIBER", "GDS"),
        )
        self.assertEqual(payload["feedback_status"], {"UTIBER": "B", "GDS": "P"})
        self.assertEqual(payload["feedback"], {"UTIBER": True, "GDS": False, "Terminate": False})
        self.assertFalse(payload["terminate_workflow"])

    def test_web_payload_marks_terminated_workflow(self):
        payload = _web_payload({"review_status": "Terminate"}, ("R1", "R2"))
        self.assertTrue(payload["feedback"]["Terminate"])
        self.assertTrue(payload["terminate_workflow"])

    def test_url_helpers_accept_site_root_or_api_root(self):
        self.assertEqual(_api_root("https://feizhang233.com"), "https://feizhang233.com/api")
        self.assertEqual(_api_root("https://feizhang233.com/api/"), "https://feizhang233.com/api")
        self.assertTrue(_workflow_url("https://feizhang233.com", "WF 1/2").endswith("/WF%201%2F2"))

    def test_payload_hash_is_stable_for_the_same_payload(self):
        payload = _web_payload({"step_1_review_status": "A-Approved"}, ("R1", "R2"))
        self.assertEqual(_payload_hash(payload), _payload_hash(dict(payload)))

    def test_docflow_headers_include_both_authentication_layers(self):
        settings = SimpleNamespace(
            cf_access_client_id="service-client-id",
            cf_access_client_secret="service-client-secret",
        )
        self.assertEqual(
            _docflow_headers(settings, "docflow-api-key"),
            {
                "X-API-Key": "docflow-api-key",
                "Accept": "application/json",
                "CF-Access-Client-Id": "service-client-id",
                "CF-Access-Client-Secret": "service-client-secret",
            },
        )

    def test_docflow_headers_reject_partial_service_token(self):
        settings = SimpleNamespace(
            cf_access_client_id="service-client-id",
            cf_access_client_secret="",
        )
        with self.assertRaisesRegex(ValueError, "must be configured together"):
            _docflow_headers(settings, "docflow-api-key")


if __name__ == "__main__":
    unittest.main()
