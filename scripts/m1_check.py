#!/usr/bin/env python3
"""outputs/m1/evidence.md 각 행의 값에 든 숫자가 위치 칸의 원문에 글자 그대로 있는지만 찾는다.
뜻은 판단하지 않고, 아무 파일도 고치지 않는다(표준 출력만)."""
import glob
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "outputs/m1/evidence.md"
INPUT_DIR = ROOT / "inputs/m1"

# 날짜(연도 포함) > 월.일 > 시각 > 숫자+단위/% > 그 밖의 숫자 순으로 글자 단위 토큰을 뽑는다.
TOKEN = re.compile(
    r"\d{4}\. \d{1,2}\. \d{1,2}\."
    r"|\d{1,2}\. \d{1,2}\."
    r"|\d{1,2}:\d{2}"
    r"|\d+(?:\.\d+)?(?:건|%|주|명|개|동|호|일|㎡)"
    r"|\d+(?:\.\d+)?"
)


def read_source(file_id):
    hits = sorted(glob.glob(str(INPUT_DIR / f"{file_id}_*")))
    if not hits:
        return None
    return Path(hits[0]).read_text(encoding="utf-8-sig")


def utterances(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"\*\*\[(\d+)\]", line)
        if m:
            out[int(m.group(1))] = line
    return out


def parse_rows():
    rows = []
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            break  # 첫 번째 표만
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0].isdigit():
            rows.append(cells)
    return rows


def scope_texts(files, locs):
    """(출처, 위치) 짝마다 검색 대상 글을 정한다: 발언 순번이 있으면 그 발언, 없으면 파일 전체."""
    files = [f.strip() for f in files.split(" / ")]
    locs = [l.strip() for l in locs.split(" / ")]
    if len(locs) != len(files):
        locs = [" / ".join(locs)] * len(files)
    texts = []
    for fid, loc in zip(files, locs):
        src = read_source(fid)
        if src is None:
            texts.append(f"<<파일 없음:{fid}>>")
            continue
        nums = [int(n) for n in re.findall(r"\[(\d+)\]", loc)]
        if nums:
            u = utterances(src)
            texts.append("\n".join(u.get(n, "") for n in nums))
        else:
            texts.append(src)
    return texts


def main():
    print("| # | 위치 | 값 | 결과 | 못 찾은 글자 |")
    print("|---|---|---|---|---|")
    for num, _sent, value, files, locs, _proc in parse_rows():
        tokens = list(dict.fromkeys(TOKEN.findall(value)))
        if not tokens:
            result, missing = "직접 확인", ""
        else:
            texts = scope_texts(files, locs)
            missing_list = [t for t in tokens if not any(t in tx for tx in texts)]
            result = "없음" if missing_list else "있음"
            missing = ", ".join(missing_list)
        print(f"| {num} | {files} {locs} | {value} | {result} | {missing} |")


if __name__ == "__main__":
    sys.exit(main())
