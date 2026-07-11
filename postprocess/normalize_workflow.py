from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
from lxml import etree


WORKFLOW_COLUMNS = [
    "workflow_id",
    "workflow_no",
    "workflow_name",
    "document_no",
    "document_revision",
    "document_version",
    "document_title",
    "step_name",
    "assignee_organizations",
    "assignee_users",
    "date_in",
    "date_due",
    "original_due_date",
    "date_completed",
    "step_status",
    "step_outcome",
    "file_name",
    "source_file",
]

# Default post-processing rule: one output row represents one Aconex workflow.
GROUP_WORKFLOWS_BY_ID = True


def normalize_workflow(
    parsed_dir: Path,
    output_dir: Path,
    *,
    group_workflows_by_id: bool = GROUP_WORKFLOWS_BY_ID,
) -> Path:
    raw_dir = parsed_dir.parent / "raw"
    workflow_df = build_workflow_dataframe(raw_dir, group_workflows_by_id=group_workflows_by_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "workflow_normalized.xlsx"
    workflow_df.to_excel(output, index=False)
    print(f"Wrote workflow normalized workbook: {output}")
    return output


def build_workflow_dataframe(
    raw_dir: Path,
    *,
    group_workflows_by_id: bool = GROUP_WORKFLOWS_BY_ID,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for path in sorted((raw_dir / "workflow").glob("*.xml")):
        root = _parse_xml(path)
        if root is None:
            continue
        for workflow in _descendants(root, "Workflow"):
            row = _workflow_row(workflow, path)
            if row["workflow_id"]:
                rows.append(row)

    frame = pd.DataFrame(rows, columns=WORKFLOW_COLUMNS)
    if not frame.empty:
        if group_workflows_by_id:
            frame = _merge_workflow_rows(frame)
        frame = frame.sort_values(["date_in", "workflow_no", "workflow_id"], ascending=[False, True, True], na_position="last")
    return frame


def _merge_workflow_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse repeated API occurrences into one row per workflow.

    A workflow can appear in more than one saved page or as separate records for
    different review steps.  Keep one complete row per ``workflow_id`` and retain
    distinct non-empty values (including step history) as semicolon-separated text.
    """
    merged_rows: list[dict[str, str]] = []
    for workflow_id, group in frame.groupby("workflow_id", sort=False, dropna=False):
        merged: dict[str, str] = {"workflow_id": str(workflow_id or "")}
        for column in WORKFLOW_COLUMNS:
            if column == "workflow_id":
                continue
            merged[column] = _join(group[column].fillna("").astype(str).tolist())
        merged_rows.append(merged)
    return pd.DataFrame(merged_rows, columns=WORKFLOW_COLUMNS)


def _parse_xml(path: Path) -> etree._Element | None:
    try:
        parser = etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=True)
        return etree.fromstring(path.read_bytes(), parser=parser)
    except Exception:
        return None


def _local(element: etree._Element) -> str:
    return etree.QName(element.tag).localname if isinstance(element.tag, str) else str(element.tag)


def _children(element: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in element if _local(child) == name]


def _first_child(element: etree._Element, name: str) -> etree._Element | None:
    children = _children(element, name)
    return children[0] if children else None


def _text(element: etree._Element | None, name: str) -> str:
    if element is None:
        return ""
    child = _first_child(element, name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _descendants(element: etree._Element, name: str) -> list[etree._Element]:
    return [item for item in element.iter() if _local(item) == name]


def _join(values: Iterable[str]) -> str:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        clean = (value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            output.append(clean)
    return "; ".join(output)


def _assignee_values(workflow: etree._Element, field: str) -> str:
    assignees = _first_child(workflow, "Assignees")
    if assignees is None:
        return ""
    return _join(_text(assignee, field) for assignee in _children(assignees, "Assignee"))


def _workflow_row(workflow: etree._Element, path: Path) -> dict[str, str]:
    return {
        "workflow_id": workflow.attrib.get("WorkflowId", ""),
        "workflow_no": _text(workflow, "WorkflowNumber"),
        "workflow_name": _text(workflow, "WorkflowName"),
        "document_no": _text(workflow, "DocumentNumber"),
        "document_revision": _text(workflow, "DocumentRevision"),
        "document_version": _text(workflow, "DocumentVersion"),
        "document_title": _text(workflow, "DocumentTitle"),
        "step_name": _text(workflow, "StepName"),
        "assignee_organizations": _assignee_values(workflow, "OrganizationName"),
        "assignee_users": _assignee_values(workflow, "Name"),
        "date_in": _text(workflow, "DateIn"),
        "date_due": _text(workflow, "DateDue"),
        "original_due_date": _text(workflow, "OriginalDueDate"),
        "date_completed": _text(workflow, "DateCompleted"),
        "step_status": _text(workflow, "StepStatus"),
        "step_outcome": _text(workflow, "StepOutcome"),
        "file_name": _text(workflow, "FileName"),
        "source_file": path.name,
    }
