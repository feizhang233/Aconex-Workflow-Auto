from __future__ import annotations

from pathlib import Path
from typing import Any

from lxml import etree

from .client import AconexClient
from .config import Settings
from .parsers import extract_xml_attribute_values, parse_response_file


WORKFLOW_ACCEPT_V1 = "application/vnd.aconex.workflow.v1+xml"


class WorkflowFetcher:
    SEARCH_PATHS = {
        "all": "/api/projects/{project_id}/workflows",
        "initiated-by-us": "/api/projects/{project_id}/workflows/initiated-by/us",
        "initiated-by-others": "/api/projects/{project_id}/workflows/initiated-by/others",
        "assigned-to-us": "/api/projects/{project_id}/workflows/assigned-to/us",
        "assigned-to-others": "/api/projects/{project_id}/workflows/assigned-to/others",
        "search-by-number": "/api/projects/{project_id}/workflows/search",
    }

    def __init__(self, settings: Settings, client: AconexClient):
        self.settings = settings
        self.client = client

    def fetch_list(
        self,
        *,
        search_mode: str = "all",
        status: str | None = None,
        workflow_number: str | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        page_size: int | None = None,
        page_number: int = 1,
        max_pages: int | None = None,
    ) -> list[Path]:
        page_size = self._workflow_page_size(page_size or self.settings.page_size)
        path_template = self._path_template(search_mode, status)
        saved_paths: list[Path] = []
        current_page = page_number
        while True:
            params: dict[str, Any] = {"page_size": str(page_size), "page_number": str(current_page)}
            if updated_after:
                params["updated_after"] = updated_after
            if updated_before:
                params["updated_before"] = updated_before
            if workflow_number:
                params["workflow_number"] = workflow_number
            response = self.client.get(
                path_template.format(project_id=self.settings.project_id),
                params=params,
                accept=WORKFLOW_ACCEPT_V1,
                raw_group="workflow",
                label=f"workflow_list_{search_mode}_page_{current_page}",
            )
            saved = self._latest_saved_body(f"workflow_list_{search_mode}_page_{current_page}", response.status_code)
            saved_paths.append(saved)
            parse_response_file(saved, self.settings.parsed_dir / "workflow", f"workflow_list_{search_mode}_page_{current_page}")
            total_pages = self._total_pages(saved)
            if total_pages is None or current_page >= total_pages:
                break
            if max_pages is not None and len(saved_paths) >= max_pages:
                break
            current_page += 1
        return saved_paths

    def fetch_detail(self, workflow_id: str) -> Path:
        raise NotImplementedError(
            "The uploaded Workflow API guide does not define a separate GET workflow detail endpoint by workflow_id. "
            "Use fetch-workflow-list or fetch-workflow-list --search-mode search-by-number --workflow-number WF-xxxx."
        )

    def fetch_details(self, *, limit: int = 20, list_file: Path | None = None) -> list[Path]:
        if list_file is None:
            paths = self.fetch_list(max_pages=1)
            list_file = paths[-1]
        workflow_ids = extract_xml_attribute_values(list_file, "Workflow", "WorkflowId")[:limit]
        print(
            f"Found {len(workflow_ids)} workflow ids in {list_file}, but no separate official by-id detail endpoint "
            "is provided in the uploaded Workflow API guide. The list/search response is saved as the available raw detail source."
        )
        return []

    def _path_template(self, search_mode: str, status: str | None) -> str:
        if status and search_mode == "all":
            return "/api/projects/{project_id}/workflows/{status}".replace("{status}", status)
        if status and search_mode in {"initiated-by-us", "initiated-by-others", "assigned-to-us", "assigned-to-others"}:
            rest = self.SEARCH_PATHS[search_mode].split("/workflows/", 1)[1]
            return f"/api/projects/{{project_id}}/workflows/{status}/{rest}"
        if search_mode not in self.SEARCH_PATHS:
            raise ValueError(f"Unsupported workflow search mode: {search_mode}")
        return self.SEARCH_PATHS[search_mode]

    def _latest_saved_body(self, label_prefix: str, status_code: int) -> Path:
        candidates = sorted((self.settings.raw_dir / "workflow").glob(f"*{label_prefix}*_{status_code}.*"))
        return [path for path in candidates if not path.name.endswith(".meta.json")][-1]

    @staticmethod
    def _workflow_page_size(value: int) -> int:
        if value < 25:
            return 25
        remainder = value % 25
        return value if remainder == 0 else value + (25 - remainder)

    @staticmethod
    def _total_pages(path: Path) -> int | None:
        parser = etree.XMLParser(recover=True, huge_tree=True)
        root = etree.fromstring(path.read_bytes(), parser=parser)
        value = root.attrib.get("TotalPages")
        return int(value) if value and value.isdigit() else None

    @staticmethod
    def _workflow_numbers(path: Path) -> list[str]:
        parser = etree.XMLParser(recover=True, huge_tree=True)
        root = etree.fromstring(path.read_bytes(), parser=parser)
        values: list[str] = []
        for element in root.iter():
            if etree.QName(element.tag).localname == "WorkflowNumber" and element.text:
                values.append(element.text.strip())
        return values
