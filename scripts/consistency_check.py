#!/usr/bin/env python3
"""ledger/ledger.csv 값과 문서 속 수치·날짜·요일을 대조한다. 표준 라이브러리만 사용, 아무 파일도 고치지 않는다.

사용: python3 scripts/consistency_check.py [--after --stage "고친 뒤"] > outputs/m3/consistency_report.md
대상: inputs/m3 초안 2개 + outputs/m1/minutes.md(5절만). 불일치가 있으면 종료 코드 1.
"""
import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "ledger" / "ledger.csv"
DOCS = [
    ("A-M3-01 협조전 초안", ROOT / "inputs/m3/A-M3-01_하자보수요청_협조전_초안.md", None),
    ("A-M3-02 업무보고서 초안", ROOT / "inputs/m3/A-M3-02_하자집계_업무보고서_초안.md", None),
    ("minutes.md 5절", ROOT / "outputs/m1/minutes.md", r"## 5\."),
]
AFTER_DOCS = [
    ("doc_A-M3-01 협조전", ROOT / "outputs/m3/doc_A-M3-01.md", None),
    ("doc_A-M3-02 업무보고서", ROOT / "outputs/m3/doc_A-M3-02.md", None),
    ("minutes.md 5절", ROOT / "outputs/m1/minutes.md", r"## 5\."),
]
WD = "월화수목금토일"
DATE = re.compile(r"(?:(\d{4})\. )?(\d{1,2})\. (\d{1,2})\.\s*\(([월화수목금토일])\)")

# (원장 항목명, 종류, 키워드 정규식)  종류: count(키워드 뒤 N건) / area / date(키워드 뒤 날짜)
RULES = [
    ("접수 건수(정상)", "count", r"(?:유효 접수|접수 건수:?)\s*(\d+)\s*건"),
    ("공종별 건수(마감)", "count", r"마감\s*(\d+)\s*건"),
    ("공종별 건수(창호)", "count", r"창호\s*(\d+)\s*건"),
    ("공종별 건수(설비)", "count", r"설비\s*(\d+)\s*건"),
    ("공종별 건수(전기)", "count", r"전기\s*(\d+)\s*건"),
    ("공종별 건수(방수결로)", "count", r"방수결로\s*(\d+)\s*건"),
    ("긴급 건수", "count", r"긴급\s*(\d+)\s*건"),
    ("미처리 건수", "count", r"미처리\s*(\d+)\s*건"),
    ("보수 면적 합계", "area", r"(?:보수 대상 면적|보수 면적)[:\s]*([\d.]+)\s*(㎡|평)"),
    ("1차 보수 착수 기한", "date", r"1차 보수 착수"),
    ("긴급 하자 착수일", "date", r"긴급 하자(?: 우선)? 착수"),
    ("협조전 회신 기한", "date", r"회신 기한"),
]


def load_ledger():
    with open(LEDGER, encoding="utf-8-sig", newline="") as f:
        return {r["항목"]: r for r in csv.DictReader(f)}


def section_lines(path, start):
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    out = []
    on = start is None
    for n, line in enumerate(lines, 1):
        if start is not None:
            if re.match(start, line):
                on = True
                continue
            if on and re.match(r"## ", line):
                break
        if on:
            out.append((n, line))
    return out


def parse_date(m):
    y = int(m.group(1) or 2026)
    return dt.date(y, int(m.group(2)), int(m.group(3))), m.group(4)


def pick_date(line, kw_end):
    """표 행이면 마지막 칸, 아니면 키워드 뒤 첫 날짜."""
    if line.lstrip().startswith("|"):
        cell = line.strip().strip("|").split("|")[-1]
        ms = list(DATE.finditer(cell))
        return ms[-1] if ms else None
    return next(DATE.finditer(line, kw_end), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="고치기 전")
    ap.add_argument("--after", action="store_true", help="고친 문서(outputs/m3/doc_*, minutes.md)를 대조")
    args = ap.parse_args()
    stage = args.stage
    docs = AFTER_DOCS if args.after else DOCS
    ledger = load_ledger()
    bad = 0
    res, wk = [], []
    for label, path, start in docs:
        for n, line in section_lines(path, start):
            for item, kind, pat in RULES:
                row = ledger.get(item)
                if row is None:
                    continue
                for m in re.finditer(pat, line):
                    loc = f"{label} {n}행"
                    if kind == "count":
                        got, exp = m.group(1), row["값"]
                        ok = got == exp
                        res.append((row["항목ID"], item, loc, f"{got}건", f"{exp}건", ok))
                    elif kind == "area":
                        got, exp = m.group(1) + m.group(2), row["값"] + row["단위"]
                        ok = got == exp
                        res.append((row["항목ID"], item, loc, got, exp, ok))
                    else:
                        d = pick_date(line, m.end())
                        if d is None:
                            res.append((row["항목ID"], item, loc, "날짜 없음({확인 필요} 표기)", row["값"], None))
                            continue
                        dd, w = parse_date(d)
                        ok = dd.isoformat() == row["값"]
                        res.append((row["항목ID"], item, loc, f"{dd.isoformat()}({w})", row["값"], ok))
                    if res[-1][5] is False:
                        bad += 1
            for m in DATE.finditer(line):
                dd, w = parse_date(m)
                real = WD[dd.weekday()]
                ok = real == w
                wk.append((f"{label} {n}행", m.group(0), dd.isoformat(), w, real, ok))
                if not ok:
                    bad += 1

    mark = {True: "일치", False: "**불일치**", None: "확인 필요"}
    print(f"# 정합성 점검 결과 — {stage}\n")
    print("> [가상 자료 기반] `scripts/consistency_check.py` 실행 결과. 기준은 `ledger/ledger.csv`이며 대상 문서는 읽기만 했다.")
    print(f"> 대상: {', '.join(d[0] for d in docs)}. 날짜 칸은 YYYY-MM-DD(요일) 형식으로 정리했다.\n")
    print("## 1. 원장 값 대조\n")
    print("| 원장 ID | 항목 | 문서 위치 | 문서 값 | 원장 값 | 판정 |\n|---|---|---|---|---|---|")
    for r in res:
        print(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {mark[r[5]]} |")
    print("\n## 2. 날짜·요일 대조\n")
    print("| 문서 위치 | 문서 표기 | 날짜 | 문서 요일 | 실제 요일 | 판정 |\n|---|---|---|---|---|---|")
    for r in wk:
        print(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {mark[r[5]]} |")
    seen = {r[1] for r in res}
    miss = [i for i in ledger if i not in seen]
    print("\n## 3. 요약\n")
    n_ok = sum(1 for r in res if r[5]) + sum(1 for r in wk if r[5])
    print(f"- 일치 {n_ok}건, 불일치 {bad}건.")
    print("- 문서에 나오지 않아 대조하지 못한 원장 항목: " + (", ".join(miss) if miss else "없음"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
