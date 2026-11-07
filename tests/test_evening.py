"""저녁 도구 시험. calc_cases.json은 JavaScript 시험과 같은 파일이다.
실행: python -I tests/test_evening.py
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import evening as E  # noqa: E402

cases = json.loads((HERE / "calc_cases.json").read_text(encoding="utf-8"))
rules = json.loads((HERE.parent / "tools" / "rules.json").read_text(encoding="utf-8"))
fails = []
count = 0


def check(name, ok, detail=""):
    global count
    count += 1
    if not ok:
        fails.append(f"{name}: {detail}")


def near(a, b):
    return abs(a - b) < 1e-9


for c in cases["long_route"]:
    check("앞뒤 " + c["name"], near(E.long_route(c["values"], c["method"]), c["want"]))
for c in cases["cross_route"]:
    check("좌우 " + c["name"], near(E.cross_route(c["values"], c["method"]), c["want"]))
for c in cases["at_least"]:
    check("기준 " + c["name"], E.at_least(c["value"], c["limit"]) == c["want"])
for c in cases["boundary"]:
    check("경계 " + c["name"], E.is_boundary(c["values"], c["limits"]) == c["want"])
for c in cases["continued"]:
    check("이어 계산 " + c["name"], near(E.continued(c["mark"], c["start"], c["breaks"]), c["want"]))
for c in cases["check_len"]:
    check("길이 " + c["name"], E.length_mismatch(c["measured"], c["map"], rules) == c["want"])
for c in cases["position"]:
    s, lg = E.map_position(c["map_len"], c["mark"], c["start"], c["end"], c["breaks"], c["second"], c["reached"], c["long"])
    check("위치 " + c["name"], near(s, c["want_s"]) and near(lg, c["want_long"]), f"{s}, {lg}")


# 가짜 자료로 저녁 검사 ---------------------------------------------------------
def ev(i, seq, kind, data, run=None, gps=None):
    e = {"id": i, "seq": seq, "kind": kind, "at": f"2026-11-23T01:{seq // 60:02d}:{seq % 60:02d}.000Z", "dev": "d1", "site": "s", "net": "n", "pack": "p", "rules": rules["version"], "test": False, "app": "1", "data": data}
    if run:
        e["run"] = run
    if gps:
        e["gps"] = gps
    return e


pack = {
    "site": "s", "net": "n", "test": False, "hash": "p", "rules": rules, "map": {"zoom": 19, "origin": [0, 0], "mpp": 0.25},
    "segs": [
        {"seg": 0, "a": 10, "b": 11, "len": 100.0, "xy": [0, 0, 400, 0], "prio": 2},
        {"seg": 1, "a": 11, "b": 12, "len": 30.0, "xy": [400, 0, 520, 0], "prio": 2},
        {"seg": 2, "a": 12, "b": 13, "len": 2.0, "xy": [520, 0, 528, 0], "prio": 2},
        {"seg": 3, "a": 13, "b": 14, "len": 50.0, "xy": [528, 0, 728, 0], "prio": 3},
    ],
}


def slope(i, seq, run, mark, values, method="one", cross=(1.0,), kind="gap", flags=(), breaks=0, photos=0):
    return ev(i, seq, "slope", {"mark": mark, "values": list(values), "method": method, "cross": list(cross), "kind": kind, "flags": list(flags), "breakCount": breaks, "photos_required": photos, "dist": mark}, run=run)


events = [
    ev("d", 1, "day", {"measurer": "가", "recorder": "나"}),
    ev("t", 2, "tool_check", {"when": "before", "tool": "level", "values": [1.0, 1.1], "passed": True}),
    # 구간 0: 둘째 마디에서 출발, 끝값 50으로 지도 100 m와 크게 다름
    ev("r0", 3, "run_start", {"seg": 0, "from": 11, "start": 0}),
    slope("p01", 4, "r0", 25, [3.0], photos=1),
    ev("h1", 5, "photo", {"of": "p01"}, run="r0"),
    ev("e0", 6, "run_end", {"end": 50, "result": "ok", "missing": []}, run="r0"),
    # 구간 1: 범위 밖, 이웃 3°, 값 감소, 공백 11 m, 불확실 값, 양 끝
    ev("r1", 7, "run_start", {"seg": 1, "from": 11, "start": 0}),
    slope("p11", 8, "r1", 5, [16.0]),
    slope("p12", 9, "r1", 3, [1.0]),
    slope("p13", 10, "r1", 20, [4.6, 4.7], method="both", photos=1),
    slope("p14", 11, "r1", 28, [4.0, 5.0, 4.5], method="three", cross=(1.0,), flags=("boundary",), photos=1),
    ev("e1", 12, "run_end", {"end": 30, "result": "ok", "missing": []}, run="r1"),
    # 구간 3: 끝까지 못 감(계획된 중단)
    ev("r3", 13, "run_start", {"seg": 3, "from": 13, "start": 0, "planned_stop": 9.5}),
    slope("p31", 14, "r3", 5, [1.0]),
    ev("b31", 15, "barrier", {"type": "bump", "mark": 6.0, "value": 23, "remain_cm": 120, "dir": "up", "photos_required": 2}, run="r3"),
    ev("s31", 16, "surface", {"mark": 0, "material": "block", "grade": "good", "photos_required": 0}, run="r3"),
    ev("e3", 17, "run_end", {"end": 9.5, "result": "stopped", "planned": True, "missing": []}, run="r3"),
    # 고친 값
    ev("x", 18, "fix", {"of": "p31", "data": {"values": [-1.2]}}, run="r3"),
    # 열린 구간
    ev("r9", 19, "run_start", {"seg": 2, "from": 12, "start": 0}),
]

report = E.inspect(events, pack)
codes = sorted(x["code"] for x in report["issues"])
for want in ["length", "range_long", "mark_down", "gap", "neighbor", "boundary", "open_run", "photos"]:
    check(f"저녁 검사 {want}", want in codes, codes)

ri = E.route_input(events, pack)
vals = {v["event"]: v for v in ri["values"]}
check("둘째 마디 위치", near(vals["p01"]["s"], 50.0), vals["p01"])
check("둘째 마디 부호", near(vals["p01"]["long"], -3.0), vals["p01"])
check("불확실 범위", "uncertain" in vals["p13"]["flags"], vals["p13"])
check("경계 불확실", "uncertain" in vals["p14"]["flags"], vals["p14"])
check("세 자리 대표값", near(vals["p14"]["long"], 4.5), vals["p14"])
check("고친 값 사용", near(vals["p31"]["long"], -1.2), vals["p31"])
check("끝까지 못 감은 잰 거리", near(vals["p31"]["s"], 5.0), vals["p31"])
seg3 = next(x for x in ri["segments"] if x["seg"] == 3)
check("계획된 중단 표시", seg3["planned_stop"] is True and seg3["status"] == "partial" and seg3["reached_m"] == 9.5, seg3)
check("장벽 위치", near(next(b for b in ri["barriers"] if b["event"] == "b31")["s"], 6.0))
check("안 잰 구간은 미확인", next((x for x in ri["segments"] if x["seg"] == 2), {"status": "none"})["status"] != "done")
check("기울기 퍼센트", near(vals["p01"]["long_pct"], -5.240777928304121), vals["p01"]["long_pct"])

# 시험 자료는 거부한다
tp = dict(pack)
tp["test"] = True
try:
    E.route_input(events, tp)
    check("시험 자료 거부", False)
except ValueError:
    check("시험 자료 거부", True)

# 점검 실패 소급: 마친 뒤 실패면 마지막 통과 뒤 값에 표시
ev2 = events + [ev("t2", 30, "tool_check", {"when": "after", "tool": "level", "values": [1.0, 2.0], "passed": False})]
ri2 = E.route_input(ev2, pack)
check("마친 뒤 실패 소급", "tool_fail" in {v["event"]: v for v in ri2["values"]}["p13"]["flags"])
check("소급은 불확실", "uncertain" in {v["event"]: v for v in ri2["values"]}["p31"]["flags"])

# 같은 구간을 두 줄로 재면 경로 줄을 쓴다
ev3 = events + [
    ev("r1b", 40, "run_start", {"seg": 1, "from": 12, "start": 0, "line": "gentle", "routeLine": True}),
    slope("p1b", 41, "r1b", 10, [1.0]),
    ev("e1b", 42, "run_end", {"end": 30, "result": "ok", "missing": []}, run="r1b"),
]
ri3 = E.route_input(ev3, pack)
seg1 = next(x for x in ri3["segments"] if x["seg"] == 1)
check("경로 줄 선택", seg1["run"] == "r1b", seg1)
check("다른 줄 값은 경로에서 뺌", "p13" not in {v["event"] for v in ri3["values"]} and "p1b" in {v["event"] for v in ri3["values"]})

print(f"시험 {count}개, 실패 {len(fails)}개")
for f in fails:
    print("  실패:", str(f)[:300])
sys.exit(1 if fails else 0)
