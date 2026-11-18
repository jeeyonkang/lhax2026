#!/usr/bin/env python3
"""하자 접수대장 week1 집계 (rules/aggregation_rules.md 기준). 표준 라이브러리만 사용.

사용: python3 scripts/aggregate.py
입력: inputs/m2/A-M2-01_하자접수대장_week1.csv (읽기만 함)
출력: outputs/m2/summary.csv, excluded_rows.csv, run_log.md
"""
import csv
import hashlib
import re
import sys
from collections import Counter, OrderedDict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "inputs" / "m2" / "A-M2-01_하자접수대장_week1.csv"
OUT = ROOT / "outputs" / "m2"

PYEONG = Decimal("3.3058")
LOC_RE = re.compile(r"^\d{3}-\d{3,4}-\S+$")
ID_RE = re.compile(r"^HA-\d+$")
SPACES = ["작은방", "안방", "침실", "거실", "주방", "욕실", "현관", "발코니"]
TRADES = ["마감", "창호", "설비", "전기", "방수결로"]
STATES = ["접수", "처리중", "완료"]
URGENT = ["긴급", "일반"]
DATE_MIN, DATE_MAX = "2026-10-26", "2026-10-30"
HEAD = ["접수번호", "접수일", "위치코드", "공종", "하자내용", "긴급구분", "처리상태", "보수면적", "면적단위"]
EXPECTED = {"정상 건수": 41, "마감 공종 건수": 13}  # A-M2-02 공개 기대값


def sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def round1(d):
    return d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def fix_location(loc, content):
    """R4: (고친 값, 근거) 또는 (None, 사유). 고칠 수 없으면 None."""
    m = re.match(r"^(\d{3})동\s*(\d{3,4})호\s*(\S+)$", loc)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "구분자 정리(동·호 표기)"
    m = re.match(r"^(\d{3})-(\d{3,4})\s+(\S+)$", loc)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "공백 구분을 '-'로 정리"
    m = re.match(r"^(\d{3})(\d{3,4})$", loc)
    if m:
        first = content.split()[0] if content.split() else ""
        if first in SPACES:
            return (f"{m.group(1)}-{m.group(2)}-{first}",
                    f"숫자를 3자리+나머지로 분리, 공간은 하자내용 첫 단어 '{first}'에서 가져옴")
        return f"{m.group(1)}-{m.group(2)}-{{확인 필요: 공간}}", "숫자 분리, 공간은 자료에 없음"
    return None, "고칠 수 있는 형식이 아님"


def main():
    before_hash = sha256(SRC)
    with open(SRC, encoding="utf-8-sig", newline="") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    assert header == HEAD, f"머리행이 예상과 다름: {header}"

    n_before = len(rows)
    excluded = []          # (원본행, 사유, 원본값)
    fixes = []             # R4 기록
    conv = []              # R5 기록
    holds = []             # 보류·확인 필요
    memos = []             # R6d 메모
    rule_count = Counter()
    live = OrderedDict()   # 원본행 -> dict

    def exclude(i, rule, reason, row):
        excluded.append((i, f"{rule} {reason}", "|".join(row)))
        rule_count[rule] += 1

    # R1
    for i, r in enumerate(rows, 1):
        if len(r) != 9:
            holds.append(f"{i}행: 열 수 {len(r)} (9 아님) {{확인 필요: 열 수}}")
            continue
        if not ID_RE.match(r[0]):
            exclude(i, "R1", "합계행", r)
            continue
        live[i] = dict(zip(HEAD, r))

    # R2 / R2'
    seen = {}
    for i in list(live):
        d = live[i]
        key = d["접수번호"]
        if key in seen:
            j = seen[key]
            if list(live[j].values()) == list(d.values()):
                exclude(i, "R2", f"완전중복(남긴 행 {j}행)", list(d.values()))
                del live[i]
            else:
                holds.append(f"{i}행: 접수번호 {key}가 {j}행과 같으나 내용이 다름 {{확인 필요: 접수번호 충돌}}")
        else:
            seen[key] = i

    # R3 (원문 위치코드 기준)
    def r3(tag):
        seen3 = {}
        for i in list(live):
            d = live[i]
            k = (d["접수일"], d["위치코드"], d["공종"], d["하자내용"])
            if k in seen3:
                j = seen3[k]
                exclude(i, "R3", f"내용중복({tag}, 남긴 행 {j}행, 접수번호 {live[j]['접수번호']}↔{d['접수번호']})",
                        list(d.values()))
                del live[i]
            else:
                seen3[k] = i
    r3("원문 위치코드")

    # R4
    for i, d in live.items():
        loc = d["위치코드"]
        if not LOC_RE.match(loc):
            new, why = fix_location(loc, d["하자내용"])
            if new:
                fixes.append((i, d["접수번호"], loc, new, why))
                d["위치코드"] = new
            else:
                holds.append(f"{i}행: 위치코드 `{loc}` {why} {{확인 필요: 위치코드}}")
    r3("표준화 후 위치코드")

    # R5 / R6
    for i, d in live.items():
        a, u = d["보수면적"].strip(), d["면적단위"].strip()
        d["_area"] = None
        if a:
            try:
                v = Decimal(a)
            except Exception:
                holds.append(f"{i}행: 보수면적 `{a}` 숫자 아님 {{확인 필요: 보수면적}}")
                continue
            if u == "㎡":
                d["_area"] = v
            elif u == "평":
                d["_area"] = v * PYEONG
                conv.append((i, d["접수번호"], a, u, v * PYEONG))
            else:
                holds.append(f"{i}행: 면적단위 `{u}` 미정의 {{확인 필요: 면적단위}}")
        elif d["공종"] in ("마감", "방수결로"):
            holds.append(f"{i}행: {d['공종']} 공종인데 보수면적 없음 {{확인 필요: 면적}} (건수 포함, 면적 합계 제외)")
        # R6c 허용값
        for col, ok in (("공종", TRADES), ("긴급구분", URGENT), ("처리상태", STATES)):
            if d[col] not in ok:
                holds.append(f"{i}행: {col} `{d[col]}` 허용값 아님 {{확인 필요: {col}}}")
        if not (DATE_MIN <= d["접수일"] <= DATE_MAX):
            holds.append(f"{i}행: 접수일 `{d['접수일']}` 범위({DATE_MIN}~{DATE_MAX}) 밖 {{확인 필요: 접수일}}")
        # R6d
        should = ("누수" in d["하자내용"]) or d["공종"] == "전기"
        if should and d["긴급구분"] != "긴급":
            memos.append(f"{i}행: 누수·전기 기준상 긴급이어야 하나 `{d['긴급구분']}` (원본 유지)")

    # 집계
    n_after = len(live)
    trade = Counter(d["공종"] for d in live.values())
    state = Counter(d["처리상태"] for d in live.values())
    urg = Counter(d["긴급구분"] for d in live.values())
    area_by_trade = {t: sum((d["_area"] for d in live.values() if d["공종"] == t and d["_area"] is not None), Decimal(0))
                     for t in TRADES}
    area_total = sum((d["_area"] for d in live.values() if d["_area"] is not None), Decimal(0))
    n_area_rows = sum(1 for d in live.values() if d["_area"] is not None)

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "summary.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["구분", "항목", "건수", "보수면적합계(㎡)"])
        w.writerow(["전체", "정상 건수", n_after, str(round1(area_total))])
        for t in TRADES:
            w.writerow(["공종", t, trade.get(t, 0), str(round1(area_by_trade[t])) if area_by_trade[t] else ""])
        for s in STATES:
            w.writerow(["처리상태", s, state.get(s, 0), ""])
        for u in URGENT:
            w.writerow(["긴급구분", u, urg.get(u, 0), ""])
    with open(OUT / "excluded_rows.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["원본행", "사유", "원본값"])
        w.writerows(sorted(excluded))

    after_hash = sha256(SRC)
    cmd = "python3 " + " ".join([str(Path(sys.argv[0]))] + sys.argv[1:])
    L = []
    L.append("# run_log — 하자 접수대장 week1 집계\n")
    L.append("> [가상 자료] 실습용 가상 정보. 기준: `rules/aggregation_rules.md`\n")
    L.append("## 실행\n")
    L.append(f"- 실행 명령: `{cmd}` (저장소 루트에서)")
    L.append(f"- 입력 파일: `inputs/m2/{SRC.name}`")
    L.append(f"- 입력 SHA-256 실행 전: `{before_hash}`")
    L.append(f"- 입력 SHA-256 실행 후: `{after_hash}` → {'변경 없음' if before_hash == after_hash else '**변경됨(오류)**'}\n")
    L.append("## 행 수\n")
    L.append("| 구분 | 행 수 |\n|---|---:|")
    L.append(f"| 처리 전(데이터 행, 머리행 제외) | {n_before} |")
    L.append(f"| 제외 | {len(excluded)} |")
    L.append(f"| 처리 후(집계 대상) | {n_after} |\n")
    L.append("## 규칙별 제외 수\n")
    L.append("| 규칙 | 제외 수 | 행 |\n|---|---:|---|")
    for rule, label in (("R1", "합계 행"), ("R2", "완전 중복"), ("R3", "내용 중복")):
        rr = [str(e[0]) for e in sorted(excluded) if e[1].startswith(rule)]
        L.append(f"| {rule} {label} | {rule_count.get(rule, 0)} | {', '.join(rr) or '-'} |")
    L.append("")
    L.append("## 고쳐서 포함한 행\n")
    L.append("### R4 위치코드 표준화\n")
    L.append("| 원본행 | 접수번호 | 원본값 | 수정값 | 근거 |\n|---|---|---|---|---|")
    for i, no, old, new, why in fixes:
        L.append(f"| {i} | {no} | `{old}` | `{new}` | {why} |")
    if not fixes:
        L.append("| - | - | - | - | 해당 없음 |")
    L.append("\n### R5 평 → ㎡ 환산 (1평 = 3.3058㎡, 행별 반올림 없음)\n")
    L.append("| 원본행 | 접수번호 | 원본값 | 환산값(㎡, 반올림 전) |\n|---|---|---|---|")
    for i, no, a, u, v in conv:
        L.append(f"| {i} | {no} | {a}{u} | {v} |")
    if not conv:
        L.append("| - | - | - | 해당 없음 |")
    L.append("\n## 집계 결과\n")
    L.append(f"- 정상 건수: {n_after}건")
    L.append("- 공종별: " + ", ".join(f"{t} {trade.get(t, 0)}" for t in TRADES))
    L.append("- 처리상태별: " + ", ".join(f"{s} {state.get(s, 0)}" for s in STATES))
    L.append("- 긴급구분: " + ", ".join(f"{u} {urg.get(u, 0)}" for u in URGENT))
    L.append(f"- 보수 면적 합계: {round1(area_total)}㎡ (면적이 있는 {n_area_rows}행, 최종 합계에서 한 번만 사사오입)\n")
    L.append("## 보류·확인 필요\n")
    L += [f"- {h}" for h in holds] or ["- 없음"]
    L.append("\n## 긴급구분 불일치 메모(R6d)\n")
    L += [f"- {m}" for m in memos] or ["- 없음"]
    L.append("\n## R7 대조\n")
    L.append("| 항목 | 기대·원본 값 | 이번 결과 | 일치 |\n|---|---:|---:|---|")
    got = {"정상 건수": n_after, "마감 공종 건수": trade.get("마감", 0)}
    for k, v in EXPECTED.items():
        L.append(f"| {k} (A-M2-02 공개값) | {v} | {got[k]} | {'일치' if v == got[k] else '**불일치**'} |")
    L.append(f"| 합계 행 건수(`44건`, 45행) | 44 | {n_before - rule_count.get('R1', 0)} (합계 행 제외 전체) | "
             f"{'일치' if n_before - rule_count.get('R1', 0) == 44 else '**불일치**'} |")
    raw_sum = sum((Decimal(r[7]) for r in rows if ID_RE.match(r[0]) and r[7]), Decimal(0))
    L.append(f"| 합계 행 면적(`118.1`, 45행) | 118.1 | 단위 무시 단순합 {raw_sum} / ㎡ 환산·중복 제외 {round1(area_total)} | "
             f"{'단순합과 일치(단위 미환산)' if round1(raw_sum) == Decimal('118.1') else '단순합과도 불일치'} |")
    if got["정상 건수"] != EXPECTED["정상 건수"]:
        L.append(f"\n- 정상 건수가 공개값과 {got['정상 건수'] - EXPECTED['정상 건수']:+d}건 다릅니다. "
                 "기준 누락·기준 모호·코드 오류 중 어느 쪽인지 {확인 필요: 추가 제외 행 또는 R3 판단}. "
                 "값을 맞추려고 행을 임의로 제외하지 않았습니다.")
    (OUT / "run_log.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    if before_hash != after_hash:
        sys.exit("입력 파일이 바뀌었습니다")


if __name__ == "__main__":
    main()
