from __future__ import annotations

import csv
import html
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from study_analysis.schemas import SourceDocument, WorksheetSnapshot


GOOGLE_SHEETS_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
HTTP_SCHEMES = {"http", "https"}


def load_source(source: str) -> SourceDocument:
    if _is_google_sheets_url(source):
        return GoogleSheetsFetcher().fetch(source)
    if _is_http_url(source):
        return RemoteDelimitedFetcher().fetch(source)
    return LocalDelimitedFetcher().fetch(source)


class GoogleSheetsFetcher:
    def fetch(self, url: str) -> SourceDocument:
        spreadsheet_id = self._extract_spreadsheet_id(url)
        metadata_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        metadata_html, _ = _read_text_from_url(metadata_url)
        spreadsheet_title = self._extract_spreadsheet_title(metadata_html)
        sheet_entries = self._extract_sheet_entries(metadata_html)
        worksheets = self._load_worksheets(spreadsheet_id=spreadsheet_id, url=url, sheet_entries=sheet_entries)
        return SourceDocument(
            source_url=url,
            source_type="google_sheet",
            worksheets=worksheets,
            title=spreadsheet_title,
            spreadsheet_id=spreadsheet_id,
        )

    def _load_worksheets(
        self,
        *,
        spreadsheet_id: str,
        url: str,
        sheet_entries: list[tuple[str, str]],
    ) -> list[WorksheetSnapshot]:
        if sheet_entries:
            try:
                return self._read_csv_worksheets(spreadsheet_id, sheet_entries)
            except HTTPError as exc:
                if exc.code not in {400, 404}:
                    raise
                return self._read_xlsx_worksheets(spreadsheet_id)
        if self._url_explicitly_selects_gid(url):
            gid = self._extract_gid(url)
            try:
                return self._read_csv_worksheets(spreadsheet_id, [(str(gid), f"gid_{gid}")])
            except HTTPError as exc:
                if exc.code not in {400, 404}:
                    raise
        return self._read_xlsx_worksheets(spreadsheet_id)

    @staticmethod
    def _extract_spreadsheet_id(url: str) -> str:
        match = GOOGLE_SHEETS_ID_RE.search(url)
        if not match:
            raise ValueError("Could not parse Google Sheets spreadsheet id from URL.")
        return match.group(1)

    @staticmethod
    def _extract_gid(url: str) -> str:
        parsed = urlparse(url)
        query_gid = parse_qs(parsed.query).get("gid")
        if query_gid:
            return query_gid[0]
        if parsed.fragment.startswith("gid="):
            return parsed.fragment.split("=", 1)[1]
        return "0"

    @staticmethod
    def _url_explicitly_selects_gid(url: str) -> bool:
        parsed = urlparse(url)
        return bool(parse_qs(parsed.query).get("gid")) or parsed.fragment.startswith("gid=")

    def _read_csv_worksheets(
        self,
        spreadsheet_id: str,
        sheet_entries: list[tuple[str, str]],
    ) -> list[WorksheetSnapshot]:
        worksheets: list[WorksheetSnapshot] = []
        for gid, title in sheet_entries:
            export_url = (
                f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
            )
            rows = self._read_csv_from_url(export_url)
            worksheets.append(WorksheetSnapshot(title=title, gid=str(gid), rows=rows))
        return worksheets

    @staticmethod
    def _read_xlsx_worksheets(spreadsheet_id: str) -> list[WorksheetSnapshot]:
        export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
        content, _ = _read_bytes_from_url(export_url)
        return _parse_xlsx_workbook(content)

    @staticmethod
    def _read_csv_from_url(url: str) -> list[list[str]]:
        content, _ = _read_text_from_url(url)
        return _parse_delimited_text(content, delimiter=",")

    @staticmethod
    def _extract_spreadsheet_title(metadata_html: str) -> str | None:
        title_match = re.search(r"<title>(.*?)</title>", metadata_html, flags=re.IGNORECASE | re.DOTALL)
        if not title_match:
            return None
        title = html.unescape(title_match.group(1)).strip()
        title = re.sub(r"\s*-\s*Google Sheets\s*$", "", title, flags=re.IGNORECASE)
        return title or None

    @staticmethod
    def _extract_sheet_entries(metadata_html: str) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        seen: set[str] = set()
        patterns = (
            r'"sheetId":\s*(\d+).*?"title":"((?:[^"\\]|\\.)*)"',
            r'"title":"((?:[^"\\]|\\.)*)".{0,200}?"sheetId":\s*(\d+)',
        )
        for pattern in patterns:
            for match in re.finditer(pattern, metadata_html, flags=re.DOTALL):
                if pattern.startswith(r'"sheetId"'):
                    gid, raw_title = match.group(1), match.group(2)
                else:
                    raw_title, gid = match.group(1), match.group(2)
                if gid in seen:
                    continue
                title = _decode_google_json_string(raw_title)
                entries.append((gid, title))
                seen.add(gid)
        return entries


class RemoteDelimitedFetcher:
    def fetch(self, url: str) -> SourceDocument:
        content, content_type = _read_text_from_url(url)
        delimiter = _guess_delimiter(url=url, content=content, content_type=content_type)
        rows = _parse_delimited_text(content, delimiter=delimiter)
        parsed = urlparse(url)
        title = Path(parsed.path).stem or parsed.netloc or "remote_source"
        worksheet = WorksheetSnapshot(title=title, gid="remote", rows=rows)
        return SourceDocument(
            source_url=url,
            source_type="remote_file",
            worksheets=[worksheet],
            title=title,
        )


class LocalDelimitedFetcher:
    def fetch(self, path_str: str) -> SourceDocument:
        path = Path(path_str)
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")
        delimiter = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
        with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            reader = csv.reader(file_obj, delimiter=delimiter)
            rows = [list(row) for row in reader]
        worksheet = WorksheetSnapshot(title=path.stem, gid="local", rows=rows)
        return SourceDocument(
            source_url=str(path.resolve()),
            source_type="local_file",
            worksheets=[worksheet],
            title=path.stem,
        )


def _is_google_sheets_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in HTTP_SCHEMES and parsed.netloc == "docs.google.com" and "/spreadsheets/" in parsed.path


def _is_http_url(source: str) -> bool:
    return urlparse(source).scheme in HTTP_SCHEMES


def _read_text_from_url(url: str) -> tuple[str, str]:
    content, content_type = _read_bytes_from_url(url)
    return content.decode("utf-8-sig"), content_type


def _read_bytes_from_url(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": "study-analysis/0.1"})
    with urlopen(request, timeout=20) as response:
        content_type = response.headers.get_content_type()
        content = response.read()
    return content, content_type


def _guess_delimiter(url: str, content: str, content_type: str) -> str:
    lowered_url = url.lower()
    if lowered_url.endswith(".tsv") or "tab-separated-values" in content_type:
        return "\t"
    sample = "\n".join(content.splitlines()[:5])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return ","
    return dialect.delimiter


def _parse_delimited_text(content: str, delimiter: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    return [list(row) for row in reader]


def _decode_google_json_string(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw


def _parse_xlsx_workbook(content: bytes) -> list[WorksheetSnapshot]:
    with zipfile.ZipFile(io.BytesIO(content)) as workbook_zip:
        workbook = ET.fromstring(workbook_zip.read("xl/workbook.xml"))
        relationships = ET.fromstring(workbook_zip.read("xl/_rels/workbook.xml.rels"))
        shared_strings = _read_xlsx_shared_strings(workbook_zip)
        relationship_targets = {
            relationship.attrib["Id"]: f"xl/{relationship.attrib['Target'].lstrip('/')}"
            for relationship in relationships.findall(f"{{{_XLSX_REL_NS}}}Relationship")
        }
        worksheets: list[WorksheetSnapshot] = []
        for sheet in workbook.findall(f".//{{{_XLSX_MAIN_NS}}}sheet"):
            if sheet.attrib.get("state") == "hidden":
                continue
            relationship_id = sheet.attrib.get(f"{{{_XLSX_DOC_REL_NS}}}id")
            if not relationship_id:
                continue
            target = relationship_targets.get(relationship_id)
            if not target:
                continue
            rows = _read_xlsx_sheet_rows(workbook_zip, target, shared_strings)
            worksheets.append(
                WorksheetSnapshot(
                    title=sheet.attrib.get("name", "Sheet"),
                    gid=sheet.attrib.get("sheetId", relationship_id),
                    rows=rows,
                )
            )
        return worksheets


def _read_xlsx_shared_strings(workbook_zip: zipfile.ZipFile) -> list[str]:
    try:
        raw_shared_strings = workbook_zip.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    shared_strings_root = ET.fromstring(raw_shared_strings)
    strings: list[str] = []
    for item in shared_strings_root.findall(f"{{{_XLSX_MAIN_NS}}}si"):
        parts = [node.text or "" for node in item.iterfind(f".//{{{_XLSX_MAIN_NS}}}t")]
        strings.append("".join(parts))
    return strings


def _read_xlsx_sheet_rows(
    workbook_zip: zipfile.ZipFile,
    target: str,
    shared_strings: list[str],
) -> list[list[str]]:
    sheet_root = ET.fromstring(workbook_zip.read(target))
    rows: list[list[str]] = []
    for row in sheet_root.findall(f".//{{{_XLSX_MAIN_NS}}}sheetData/{{{_XLSX_MAIN_NS}}}row"):
        values_by_index: dict[int, str] = {}
        max_index = -1
        for cell in row.findall(f"{{{_XLSX_MAIN_NS}}}c"):
            cell_ref = cell.attrib.get("r", "")
            column_index = _xlsx_column_index(cell_ref)
            if column_index < 0:
                continue
            values_by_index[column_index] = _read_xlsx_cell_value(cell, shared_strings)
            max_index = max(max_index, column_index)
        rows.append([values_by_index.get(index, "") for index in range(max_index + 1)] if max_index >= 0 else [])
    return rows


def _read_xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        parts = [node.text or "" for node in cell.iterfind(f".//{{{_XLSX_MAIN_NS}}}t")]
        return "".join(parts)
    value_node = cell.find(f"{{{_XLSX_MAIN_NS}}}v")
    raw_value = value_node.text if value_node is not None and value_node.text is not None else ""
    if cell_type == "s":
        if raw_value.isdigit():
            index = int(raw_value)
            if 0 <= index < len(shared_strings):
                return shared_strings[index]
        return raw_value
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"
    return raw_value


def _xlsx_column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return -1
    column_name = match.group(1)
    index = 0
    for letter in column_name:
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1


_XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_XLSX_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
