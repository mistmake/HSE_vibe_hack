from __future__ import annotations

from study_analysis.schemas import PreparedWorksheet, WorksheetSnapshot, WorksheetStructureHint


def prepare_worksheet(
    worksheet: WorksheetSnapshot,
    structure_hint: WorksheetStructureHint | None = None,
    warnings: list[str] | None = None,
) -> PreparedWorksheet:
    max_width = max((len(row) for row in worksheet.rows), default=0)
    header_row_index = _detect_header_row(worksheet.rows)
    header_row_indices = [header_row_index]
    headers = _normalize_row(worksheet.rows[header_row_index], max_width) if worksheet.rows else []
    data_start_row = header_row_index + 1
    if structure_hint is not None:
        header_row_indices = structure_hint.header_row_indices or header_row_indices
        data_start_row = structure_hint.data_start_row
        headers = _build_headers_from_structure_hint(worksheet.rows, structure_hint, max_width)
    data_rows = [_normalize_row(row, len(headers)) for row in worksheet.rows[data_start_row:]]
    context_text = _build_context_text(worksheet.title, headers, data_rows)
    return PreparedWorksheet(
        title=worksheet.title,
        gid=worksheet.gid,
        rows=worksheet.rows,
        header_row_index=header_row_index,
        header_row_indices=header_row_indices,
        headers=headers,
        data_rows=data_rows,
        context_text=context_text,
        structure_hint=structure_hint,
        warnings=list(warnings or []),
    )


def _detect_header_row(rows: list[list[str]]) -> int:
    best_index = 0
    best_score = -1
    for index, row in enumerate(rows[:10]):
        non_empty = sum(1 for cell in row if str(cell).strip())
        alpha_cells = sum(1 for cell in row if any(char.isalpha() for char in str(cell)))
        score = non_empty + alpha_cells
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _normalize_row(row: list[str], target_len: int | None = None) -> list[str]:
    normalized = [str(cell).strip() for cell in row]
    if target_len is None:
        return normalized
    if len(normalized) < target_len:
        normalized.extend([""] * (target_len - len(normalized)))
    return normalized[:target_len]


def _build_context_text(title: str, headers: list[str], data_rows: list[list[str]]) -> str:
    lines = [f"Worksheet: {title}", f"Headers: {headers}"]
    for row in data_rows[:5]:
        lines.append(f"Row: {row}")
    return "\n".join(lines)


def _build_headers_from_structure_hint(
    rows: list[list[str]],
    structure_hint: WorksheetStructureHint,
    max_width: int,
) -> list[str]:
    headers = _merge_header_rows(rows, structure_hint.header_row_indices, max_width)
    if structure_hint.name_column_index is not None and structure_hint.name_column_index < max_width:
        headers[structure_hint.name_column_index] = "Student"
    if structure_hint.group_column_index is not None and structure_hint.group_column_index < max_width:
        headers[structure_hint.group_column_index] = "Group"
    for column in structure_hint.component_columns:
        if 0 <= column.index < max_width:
            headers[column.index] = column.label.strip()
    return headers


def _merge_header_rows(rows: list[list[str]], header_row_indices: list[int], max_width: int) -> list[str]:
    headers = [""] * max_width
    if not header_row_indices:
        return headers
    for column_index in range(max_width):
        fragments: list[str] = []
        for row_index in header_row_indices:
            if row_index >= len(rows) or column_index >= len(rows[row_index]):
                continue
            cell = str(rows[row_index][column_index]).strip()
            if not cell:
                continue
            if fragments and cell == fragments[-1]:
                continue
            fragments.append(cell)
        headers[column_index] = " ".join(fragments).strip()
    return headers
