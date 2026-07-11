from __future__ import annotations

from pathlib import Path
from typing import Any

from .client import AconexClient
from .config import Settings
from .parsers import extract_mail_attachment_ids, extract_xml_attribute_values, parse_response_file


MAIL_ACCEPT_V2 = "application/vnd.aconex.mail.v2+xml;charset=UTF-8"
DEFAULT_RETURN_FIELDS = [
    "allAttachmentCount",
    "closedoutdetails",
    "confidential",
    "corrtypeid",
    "docno",
    "fromUserDetails",
    "hasAttachments",
    "inreftomailno",
    "mailRecipients",
    "reasonforissueid",
    "secondaryattribute",
    "sentdate",
    "subject",
    "tostatusid",
]


class MailFetcher:
    def __init__(self, settings: Settings, client: AconexClient):
        self.settings = settings
        self.client = client

    def fetch_list(
        self,
        *,
        mail_box: str | None = None,
        search_query: str | None = None,
        page_size: int | None = None,
        page_number: int = 1,
        max_pages: int | None = None,
        return_fields: list[str] | None = None,
    ) -> list[Path]:
        page_size = page_size or self.settings.page_size
        mail_box = mail_box or self.settings.default_mail_box
        fields = return_fields or DEFAULT_RETURN_FIELDS
        saved_paths: list[Path] = []
        current_page = page_number
        while True:
            params: dict[str, Any] = {
                "mail_box": mail_box,
                "return_fields": ",".join(fields),
                "search_type": "PAGED",
                "page_size": str(page_size),
                "page_number": str(current_page),
            }
            if search_query:
                params["search_query"] = search_query
            response = self.client.get(
                f"/api/projects/{self.settings.project_id}/mail",
                params=params,
                accept=MAIL_ACCEPT_V2,
                raw_group="mail",
                label=f"mail_list_page_{current_page}",
            )
            saved = self._latest_saved_body("mail_list_page", response.status_code)
            saved_paths.append(saved)
            parse_response_file(saved, self.settings.parsed_dir / "mail", f"mail_list_page_{current_page}")
            total_pages = self._total_pages(saved)
            if total_pages is None or current_page >= total_pages:
                break
            if max_pages is not None and len(saved_paths) >= max_pages:
                break
            current_page += 1
        return saved_paths

    def fetch_detail(self, mail_id: str) -> Path:
        response = self.client.get(
            f"/api/projects/{self.settings.project_id}/mail/{mail_id}",
            accept=MAIL_ACCEPT_V2,
            raw_group="mail",
            label=f"mail_detail_{mail_id}",
        )
        saved = self._latest_saved_body(f"mail_detail_{mail_id}", response.status_code)
        parse_response_file(saved, self.settings.parsed_dir / "mail", f"mail_detail_{mail_id}")
        return saved

    def fetch_details(self, *, limit: int = 20, list_file: Path | None = None) -> list[Path]:
        if list_file is None:
            paths = self.fetch_list(max_pages=1)
            list_file = paths[-1]
        mail_ids = extract_xml_attribute_values(list_file, "Mail", "MailId")[:limit]
        print(f"Found {len(mail_ids)} mail ids in {list_file}")
        return [self.fetch_detail(mail_id) for mail_id in mail_ids]

    def fetch_attachments(self, mail_id: str, *, markedup: bool = False) -> list[Path]:
        detail_path = self.fetch_detail(mail_id)
        attachment_ids = extract_mail_attachment_ids(detail_path)
        print(f"Found {len(attachment_ids)} downloadable attachment ids in {detail_path}")
        saved_paths: list[Path] = []
        for attachment_id in attachment_ids:
            suffix = "/markedup" if markedup else ""
            response = self.client.get(
                f"/api/projects/{self.settings.project_id}/mail/{mail_id}/attachments/{attachment_id}{suffix}",
                raw_group="mail",
                label=f"mail_attachment_{mail_id}_{attachment_id}",
            )
            saved_paths.append(self._latest_saved_body(f"mail_attachment_{mail_id}_{attachment_id}", response.status_code))
        return saved_paths

    def _latest_saved_body(self, label_prefix: str, status_code: int) -> Path:
        candidates = sorted((self.settings.raw_dir / "mail").glob(f"*{label_prefix}*_{status_code}.*"))
        return [path for path in candidates if not path.name.endswith(".meta.json")][-1]

    @staticmethod
    def _total_pages(path: Path) -> int | None:
        from lxml import etree

        parser = etree.XMLParser(recover=True, huge_tree=True)
        root = etree.fromstring(path.read_bytes(), parser=parser)
        value = root.attrib.get("TotalPages")
        return int(value) if value and value.isdigit() else None
