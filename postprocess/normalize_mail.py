from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

import pandas as pd
from lxml import etree

from aconex.excel_formatting import format_table_workbook
from aconex.mail_final_scan import extract_review_comment_text, extract_workflow_review_history_comments


MAIL_COLUMNS = [
    "mail_id",
    "workflow_no",
    "approval_status",
    "subject",
    "sent_date",
    "corr_type_id",
    "reason_for_issue_id",
    "from_user_name",
    "from_organization",
    "to_recipients",
    "cc_recipients",
    "has_attachments",
    "all_attachment_count",
    "document_no_list",
    "attachment_id_list",
    "source_file",
]

# Only retain Final-workflow correspondence such as "Final (WF-001038) title".
FINAL_WORKFLOW_ONLY = True
FINAL_WORKFLOW_SUBJECT_RE = re.compile(
    r"^Final\s*\(\s*WF-(\d{6})\s*\)\s+\S.*$",
    re.IGNORECASE,
)

MAIL_ATTACHMENT_COLUMNS = [
    "mail_id",
    "attachment_id",
    "attachment_type",
    "document_no",
    "file_name",
    "file_size",
    "revision",
    "title",
    "source_file",
]

WORKFLOW_COMMENT_COLUMNS = [
    "workflow_no",
    "comments",
]


def normalize_mail(
    parsed_dir: Path,
    output_dir: Path,
    *,
    final_workflow_only: bool = FINAL_WORKFLOW_ONLY,
) -> Path:
    raw_dir = parsed_dir.parent / "raw"
    comments_df = build_workflow_comments_dataframe(raw_dir, final_workflow_only=final_workflow_only)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "mail_normalized.xlsx"
    with pd.ExcelWriter(output) as writer:
        comments_df.to_excel(writer, sheet_name="Workflow Comments", index=False)
    format_table_workbook(
        output,
        sheet_name="Workflow Comments",
        column_widths={"workflow_no": 16, "comments": 100},
        wrap_columns={"comments"},
    )
    print(f"Wrote mail normalized workbook: {output}")
    return output


def build_workflow_comments_dataframe(
    raw_dir: Path,
    *,
    final_workflow_only: bool = FINAL_WORKFLOW_ONLY,
) -> pd.DataFrame:
    """Extract unique review-history comments from saved Final workflow mail details.

    List responses do not contain the message body, so only saved ``Mail`` detail
    XML files can contribute comments.  A comment is unique within a workflow when
    its whitespace-normalized, case-insensitive text is unique.
    """
    comments_by_workflow: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()

    for path in sorted((raw_dir / "mail").glob("*.xml")):
        root = _parse_xml(path)
        if root is None or _local(root) != "Mail":
            continue
        subject = _text(root, "Subject")
        match = FINAL_WORKFLOW_SUBJECT_RE.match(subject.strip())
        if final_workflow_only and not match:
            continue
        if not match:
            continue

        workflow_no = f"WF-{match.group(1)}"
        for review_row in extract_workflow_review_history_comments(
            etree.tostring(root, encoding="unicode")
        ):
            comment = extract_review_comment_text(review_row.get("review_comment", ""))
            if not comment:
                continue
            key = (workflow_no, _comment_key(comment))
            if key in seen:
                continue
            seen.add(key)
            comments_by_workflow.setdefault(workflow_no, []).append(comment)

    frame = pd.DataFrame(
        [
            {"workflow_no": workflow_no, "comments": "\n".join(comments)}
            for workflow_no, comments in comments_by_workflow.items()
        ],
        columns=WORKFLOW_COMMENT_COLUMNS,
    )
    if not frame.empty:
        frame = frame.sort_values(["workflow_no", "comments"], kind="stable").reset_index(drop=True)
    return frame


def build_mail_dataframes(
    raw_dir: Path,
    *,
    final_workflow_only: bool = FINAL_WORKFLOW_ONLY,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mail_by_id: dict[str, dict[str, str]] = {}
    detail_ids: set[str] = set()
    attachments: list[dict[str, str]] = []

    for path in sorted((raw_dir / "mail").glob("*.xml")):
        root = _parse_xml(path)
        if root is None:
            continue
        root_name = _local(root)
        if root_name == "MailSearch":
            for mail in _descendants(root, "Mail"):
                row = _mail_row(mail, path)
                if row["mail_id"]:
                    _merge_mail_row(mail_by_id, row, prefer_new=False)
        elif root_name == "Mail":
            row = _mail_row(root, path)
            if row["mail_id"]:
                detail_ids.add(row["mail_id"])
                _merge_mail_row(mail_by_id, row, prefer_new=True)
                attachments.extend(_attachment_rows(root, row["mail_id"], path))

    for mail_id, row in mail_by_id.items():
        related = [item for item in attachments if item["mail_id"] == mail_id]
        if related:
            row["attachment_id_list"] = _join(item["attachment_id"] for item in related)
            row["document_no_list"] = _join(item["document_no"] for item in related)
            row["all_attachment_count"] = row["all_attachment_count"] or str(len(related))
            row["has_attachments"] = "true"
        elif mail_id in detail_ids:
            row["has_attachments"] = row["has_attachments"] or "false"

    final_mail_ids = {
        mail_id
        for mail_id, row in mail_by_id.items()
        if _set_final_workflow_number(row)
    }
    selected_mail_by_id = (
        {mail_id: mail_by_id[mail_id] for mail_id in final_mail_ids}
        if final_workflow_only
        else mail_by_id
    )
    selected_mail_ids = set(selected_mail_by_id)

    mail_df = pd.DataFrame(selected_mail_by_id.values(), columns=MAIL_COLUMNS)
    if not mail_df.empty:
        mail_df = mail_df.sort_values(["sent_date", "mail_id"], ascending=[False, True], na_position="last")
    attachments_df = pd.DataFrame(
        [item for item in attachments if item["mail_id"] in selected_mail_ids],
        columns=MAIL_ATTACHMENT_COLUMNS,
    )
    if not attachments_df.empty:
        attachments_df = attachments_df.drop_duplicates(subset=["mail_id", "attachment_id", "file_name"], keep="last")
    return mail_df, attachments_df


def _set_final_workflow_number(row: dict[str, str]) -> bool:
    """Return whether a mail is a Final workflow mail and store its number."""
    match = FINAL_WORKFLOW_SUBJECT_RE.match((row.get("subject") or "").strip())
    if not match:
        return False
    row["workflow_no"] = f"WF-{match.group(1)}"
    return True


def _clean_comment(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _comment_key(value: str) -> str:
    return _clean_comment(value).casefold()


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


def _text(element: etree._Element, name: str) -> str:
    child = _first_child(element, name)
    return _node_text(child)


def _node_text(element: etree._Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


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


def _recipient_name(recipient: etree._Element) -> str:
    name = _text(recipient, "Name")
    org = _text(recipient, "OrganizationName")
    return f"{name} ({org})" if name and org else name or org


def _recipients(mail: etree._Element, distribution_type: str) -> str:
    users = _first_child(mail, "ToUsers")
    if users is None:
        return ""
    matches = []
    for recipient in _children(users, "Recipient"):
        if _text(recipient, "DistributionType").upper() == distribution_type:
            matches.append(_recipient_name(recipient))
    return _join(matches)


def _mail_row(mail: etree._Element, path: Path) -> dict[str, str]:
    from_user = _first_child(mail, "FromUserDetails")
    attachment_ids = []
    document_numbers = []
    for attachment in _attachment_elements(mail):
        attachment_ids.append(attachment.attrib.get("attachmentId", ""))
        document_numbers.append(_text(attachment, "DocumentNo"))
    return {
        "mail_id": mail.attrib.get("MailId", ""),
        "workflow_no": "",
        "approval_status": _text(mail, "ApprovalStatus"),
        "subject": _text(mail, "Subject"),
        "sent_date": _text(mail, "SentDate"),
        "corr_type_id": _text(mail, "CorrespondenceType"),
        "reason_for_issue_id": _text(mail, "ReasonForIssue"),
        "from_user_name": _text(from_user, "Name") if from_user is not None else "",
        "from_organization": _text(from_user, "OrganizationName") if from_user is not None else "",
        "to_recipients": _recipients(mail, "TO"),
        "cc_recipients": _recipients(mail, "CC"),
        "has_attachments": _text(mail, "HasAttachments") or ("true" if attachment_ids else ""),
        "all_attachment_count": _text(mail, "AllAttachmentCount"),
        "document_no_list": _join(document_numbers),
        "attachment_id_list": _join(attachment_ids),
        "source_file": path.name,
    }


def _merge_mail_row(rows: dict[str, dict[str, str]], new_row: dict[str, str], *, prefer_new: bool) -> None:
    mail_id = new_row["mail_id"]
    if mail_id not in rows:
        rows[mail_id] = {column: new_row.get(column, "") for column in MAIL_COLUMNS}
        return
    current = rows[mail_id]
    for column in MAIL_COLUMNS:
        if prefer_new:
            current[column] = new_row.get(column, "") or current.get(column, "")
        else:
            current[column] = current.get(column, "") or new_row.get(column, "")


def _attachment_elements(mail: etree._Element) -> list[etree._Element]:
    attachments = _first_child(mail, "Attachments")
    if attachments is None:
        return []
    return [
        child
        for child in attachments
        if _local(child) in {"RegisteredDocumentAttachment", "LocalFileAttachment", "MailAttachment"}
    ]


def _attachment_rows(mail: etree._Element, mail_id: str, path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for attachment in _attachment_elements(mail):
        attachment_type = _local(attachment)
        rows.append(
            {
                "mail_id": mail_id,
                "attachment_id": attachment.attrib.get("attachmentId", "") or _text(attachment, "MailId"),
                "attachment_type": attachment_type,
                "document_no": _text(attachment, "DocumentNo") or _text(attachment, "MailNo"),
                "file_name": _text(attachment, "FileName"),
                "file_size": _text(attachment, "FileSize"),
                "revision": _text(attachment, "Revision"),
                "title": _text(attachment, "Title") or _text(attachment, "Subject"),
                "source_file": path.name,
            }
        )
    return rows
