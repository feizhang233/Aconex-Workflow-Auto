from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import json

import pandas as pd
from lxml import etree


def parse_response_file(path: Path, output_dir: Path, label: str | None = None) -> Path:
    label = label or path.stem
    data = path.read_bytes()
    stripped = data.lstrip()
    if not stripped:
        return _write_inventory(output_dir, label, [])
    if stripped.startswith(b"<"):
        return inventory_xml(data, output_dir, label)
    if stripped[:1] in {b"{", b"["}:
        return inventory_json(data, output_dir, label)
    return _write_inventory(output_dir, label, [{"path": "$", "attribute": "", "sample_value": data[:200].decode("utf-8", errors="replace"), "occurrence_count": 1}])


def inventory_xml(data: bytes, output_dir: Path, label: str) -> Path:
    parser = etree.XMLParser(recover=True, remove_blank_text=True, huge_tree=True)
    root = etree.fromstring(data, parser=parser)
    inventory: dict[tuple[str, str], dict[str, Any]] = {}

    def local_name(tag: Any) -> str:
        if not isinstance(tag, str):
            return str(tag)
        return etree.QName(tag).localname

    def visit(element: etree._Element, parts: list[str]) -> None:
        current = parts + [local_name(element.tag)]
        path = "/" + "/".join(current)
        text = (element.text or "").strip()
        key = (path, "")
        row = inventory.setdefault(key, {"path": path, "attribute": "", "sample_value": "", "occurrence_count": 0})
        row["occurrence_count"] += 1
        if text and not row["sample_value"]:
            row["sample_value"] = text[:500]
        for name, value in element.attrib.items():
            attr_key = (path, name)
            attr_row = inventory.setdefault(attr_key, {"path": path, "attribute": name, "sample_value": "", "occurrence_count": 0})
            attr_row["occurrence_count"] += 1
            if value and not attr_row["sample_value"]:
                attr_row["sample_value"] = value[:500]
        for child in element:
            visit(child, current)

    visit(root, [])
    return _write_inventory(output_dir, label, sorted(inventory.values(), key=lambda item: (item["path"], item["attribute"])))


def inventory_json(data: bytes, output_dir: Path, label: str) -> Path:
    payload = json.loads(data.decode("utf-8"))
    rows: dict[str, dict[str, Any]] = {}

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            rows.setdefault(path, {"path": path, "attribute": "", "sample_value": "<list>", "occurrence_count": 0})
            rows[path]["occurrence_count"] += len(value)
            for child in value[:10]:
                walk(child, f"{path}[]")
        else:
            row = rows.setdefault(path, {"path": path, "attribute": "", "sample_value": "", "occurrence_count": 0})
            row["occurrence_count"] += 1
            if value is not None and not row["sample_value"]:
                row["sample_value"] = str(value)[:500]

    try:
        frame = pd.json_normalize(payload)
        for column in frame.columns:
            row = rows.setdefault(column, {"path": column, "attribute": "", "sample_value": "", "occurrence_count": int(frame[column].count())})
            sample = frame[column].dropna()
            if not sample.empty and not row["sample_value"]:
                row["sample_value"] = str(sample.iloc[0])[:500]
    except Exception:
        pass
    walk(payload, "")
    return _write_inventory(output_dir, label, sorted(rows.values(), key=lambda item: item["path"]))


def _write_inventory(output_dir: Path, label: str, rows: list[dict[str, Any]]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{label}_field_inventory.csv"
    pd.DataFrame(rows, columns=["path", "attribute", "sample_value", "occurrence_count"]).to_csv(path, index=False)
    print(f"Wrote field inventory: {path}")
    return path


def extract_xml_attribute_values(path: Path, tag_name: str, attribute_name: str) -> list[str]:
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(path.read_bytes(), parser=parser)
    values: list[str] = []
    for element in root.iter():
        if etree.QName(element.tag).localname == tag_name:
            value = element.attrib.get(attribute_name)
            if value:
                values.append(value)
    return values


def extract_mail_attachment_ids(path: Path) -> list[str]:
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(path.read_bytes(), parser=parser)
    ids: list[str] = []
    for element in root.iter():
        if etree.QName(element.tag).localname in {"LocalFileAttachment", "RegisteredDocumentAttachment"}:
            attachment_id = element.attrib.get("attachmentId")
            if attachment_id:
                ids.append(attachment_id)
    return ids
