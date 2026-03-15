from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from study_analysis.llm import OpenAIStudentMatcher, OpenAIWorksheetStructureAnalyzer
from study_analysis.pipeline import AnalysisPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze a Google Sheet or local CSV/TSV file.")
    parser.add_argument(
        "--source",
        required=True,
        help="Google Sheets URL, direct CSV/TSV URL, or local CSV/TSV path.",
    )
    parser.add_argument("--student", required=True, help="Student full name to match in the sheet.")
    parser.add_argument("--group", help="Student group for additional matching confidence.")
    parser.add_argument(
        "--llm-student-match",
        choices=("off", "openai"),
        default="off",
        help="Enable LLM fallback for student row matching.",
    )
    parser.add_argument(
        "--llm-model",
        default=os.getenv("STUDY_ANALYSIS_LLM_MODEL", "gpt-5-mini"),
        help="Model used for LLM student matching.",
    )
    parser.add_argument(
        "--llm-worksheet-structure",
        choices=("off", "auto", "openai"),
        default="auto",
        help="Use LLM to understand complex worksheet headers and component columns.",
    )
    parser.add_argument(
        "--view",
        choices=("full", "normalized", "extraction"),
        default="full",
        help="Choose which JSON view to print.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    student_matcher = None
    structure_analyzer = None
    if args.llm_student_match == "openai":
        student_matcher = OpenAIStudentMatcher(model=args.llm_model)
    if args.llm_worksheet_structure in {"auto", "openai"}:
        structure_analyzer = OpenAIWorksheetStructureAnalyzer(model=args.llm_model)
    result = AnalysisPipeline(
        student_matcher=student_matcher,
        structure_analyzer=structure_analyzer,
    ).analyze(
        source=args.source,
        full_name=args.student,
        group=args.group,
    )
    if args.view == "normalized":
        payload = asdict(result.normalized)
    elif args.view == "extraction":
        payload = [asdict(worksheet.extraction) for worksheet in result.worksheets]
    else:
        payload = result.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
