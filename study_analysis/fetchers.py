from __future__ import annotations

import csv
import html
import io
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

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
        if not sheet_entries:
            fallback_gid = self._extract_gid(url)
            sheet_entries = [(str(fallback_gid), f"gid_{fallback_gid}")]
        worksheets: list[WorksheetSnapshot] = []
        for gid, title in sheet_entries:
            export_url = (
                f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
            )
            rows = self._read_csv_from_url(export_url)
            worksheets.append(WorksheetSnapshot(title=title, gid=str(gid), rows=rows))
        return SourceDocument(
            source_url=url,
            source_type="google_sheet",
            worksheets=worksheets,
            title=spreadsheet_title,
            spreadsheet_id=spreadsheet_id,
        )

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
    request = Request(url, headers={"User-Agent": "study-analysis/0.1"})
    with urlopen(request, timeout=20) as response:
        content_type = response.headers.get_content_type()
        content = response.read().decode("utf-8-sig")
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
