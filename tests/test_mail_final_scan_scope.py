from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from aconex.mail_final_scan import MailSummary, _scan_mail


class MailFinalScanScopeTests(unittest.TestCase):
    @patch("aconex.mail_final_scan._write_comments_excel")
    @patch("aconex.mail_final_scan.load_workflow_comments", return_value=[])
    @patch("aconex.mail_final_scan.add_update_run")
    @patch("aconex.mail_final_scan._comment_rows_from_detail", return_value=[])
    @patch("aconex.mail_final_scan._fetch_mail_detail", return_value=object())
    @patch("aconex.mail_final_scan._iter_mail_summaries")
    def test_only_recent_matching_workflow_mail_fetches_detail(
        self,
        summaries,
        fetch_detail,
        _comment_rows,
        _add_run,
        _load_comments,
        _write_excel,
    ):
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        old = datetime.now(timezone.utc) - timedelta(hours=80)
        summaries.return_value = [
            MailSummary("match", "", "", "Final (WF-000001)", recent.isoformat(), ""),
            MailSummary("other", "", "", "Final (WF-000002)", recent.isoformat(), ""),
            MailSummary("old", "", "", "Final (WF-000001)", old.isoformat(), ""),
        ]
        with tempfile.TemporaryDirectory() as directory:
            _scan_mail(
                SimpleNamespace(output_dir=Path(directory)),
                object(),
                command="test",
                source="test",
                output=Path(directory) / "comments.xlsx",
                from_number=None,
                hours=72,
                max_pages=None,
                save_raw=False,
                debug_candidates=False,
                workflow_numbers={"WF-000001"},
                fail_on_error=True,
            )

        self.assertEqual(fetch_detail.call_count, 1)
        self.assertEqual(fetch_detail.call_args.args[2], "match")

    @patch("aconex.mail_final_scan._parse_xml_bytes")
    def test_iter_mail_summaries_does_not_stop_early_on_old_first_page(self, parse_xml):
        """Old page-1 rows must not prevent later pages from being scanned."""
        from aconex.mail_final_scan import _iter_mail_summaries
        from lxml import etree
        from unittest.mock import MagicMock

        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        def page_xml(page: int, total: int, mail_id: str, sent: str, subject: str):
            return etree.fromstring(
                f"""
                <MailSearch CurrentPage="{page}" PageSize="1" TotalPages="{total}" TotalResults="2">
                  <SearchResults>
                    <Mail MailId="{mail_id}">
                      <Subject>{subject}</Subject>
                      <SentDate>{sent}</SentDate>
                    </Mail>
                  </SearchResults>
                </MailSearch>
                """.strip()
            )

        parse_xml.side_effect = [
            page_xml(1, 2, "old-mail", old, "Unrelated"),
            page_xml(2, 2, "final-mail", recent, "Final (WF-000001)"),
        ]
        client = MagicMock()
        client.get.return_value = MagicMock(content=b"<unused/>")
        settings = SimpleNamespace(project_id="1", default_mail_box="inbox", page_size=1)

        got = list(_iter_mail_summaries(settings, client, max_pages=None, save_raw=False))
        self.assertEqual([item.mail_id for item in got], ["old-mail", "final-mail"])
        self.assertEqual(client.get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
