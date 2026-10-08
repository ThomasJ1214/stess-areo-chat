"""Surface bounded pytest failure messages in normal GitHub CI annotations.

Reads only the specified JUnit report, never environment values or captured
test stdout. The pytest step retains responsibility for the job's exit status.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


def annotation(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if not args.report.is_file():
        print("No JUnit test report was produced; inspect the test step for a collection or startup failure.")
        return
    root = ET.parse(args.report).getroot()
    cases = list(root.iter("testcase"))
    failures = []
    skipped = 0
    for case in cases:
        skipped += case.find("skipped") is not None
        for problem in case:
            if problem.tag not in {"failure", "error"}:
                continue
            name = f"{case.get('classname', '')}.{case.get('name', '')}".strip(".")
            message = problem.get("message") or problem.text or "No failure message provided"
            failures.append((name, message[:2000]))
    print(f"JUnit report: {len(cases)} tests, {len(failures)} failures/errors, {skipped} skipped.")
    for name, message in failures[:20]:
        print(f"::error title=Pytest failure::{annotation(name + ': ' + message)}")


if __name__ == "__main__":
    main()
