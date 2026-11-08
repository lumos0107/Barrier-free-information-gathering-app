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


# 순서 번호: 시계가 뒤로 가도 시작, 지점, 끝 순서를 지킨다 (JS 시험과 같은 사례)
_o = [
    {"id": "r1", "seq": 1, "dev": "d1", "kind": "run_start", "at": "2026-11-23T09:05:00+09:00", "ord": 1000, "data": {"seg": 7, "from": 3, "start": 0}},
    {"id": "p1", "seq": 2, "dev": "d1", "kind": "slope", "run": "r1", "at": "2026-11-23T09:00:00+09:00", "ord": 1001, "data": {"mark": 5, "values": [2.0], "method": "one", "cross": [1.0], "kind": "gap"}},
    {"id": "e1", "seq": 3, "dev": "d1", "kind": "run_end", "run": "r1", "at": "2026-11-23T09:01:00+09:00", "ord": 1002, "data": {"end": 10, "result": "ok", "missing": []}},
]
_S = E.fold(_o)
check("순서 번호 우선", len(_S["runs"]["r1"]["points"]) == 1 and _S["runs"]["r1"]["closed"], str(_S["runs"].get("r1")))


# 2단계 고침 -------------------------------------------------------------------
def _e(i, seq, kind, data, run=None):
    e = {"id": i, "seq": seq, "ord": seq, "dev": "d1", "kind": kind, "at": "2026-11-23T09:00:00+09:00", "data": data}
    if run:
        e["run"] = run
    return e


# 고침의 unset 칸은 빠진다
_S = E.fold([_e("r1", 1, "run_start", {"seg": 7, "from": 3, "start": 0}), _e("b1", 2, "barrier", {"type": "bump", "mark": 3, "value": 20, "value2": 19}, "r1"), _e("f1", 3, "fix", {"of": "b1", "data": {"value": 10}, "unset": ["value2"]}, "r1")])
_b = _S["runs"]["r1"]["barriers"][0]
check("고침 unset", _b["value"] == 10 and "value2" not in _b, str(_b))
# 경계 표시는 값으로 다시 정한다
check("경계 다시 정함", "boundary" not in E.point_flags({"method": "three", "values": [4.0, 4.1, 4.2], "flags": ["boundary"], "_at": "2026-11-23T09:00:00+09:00"}, None, rules))

_pk = {"site": "s", "net": "n", "test": False, "hash": "p", "rules": rules, "segs": [{"seg": 0, "a": 10, "b": 11, "len": 30.0, "xy": [0, 0, 120, 0]}]}
# 끊김 전에 적은 턱은 그때까지의 끊김만 쓴다: 지도 30 m, 표시값 8의 턱, 20에서 끊김(20 -> 0), 끝값 10
_ev = [
    _e("r1", 1, "run_start", {"seg": 0, "from": 10, "start": 0}),
    _e("b1", 2, "barrier", {"type": "bump", "mark": 8, "value": 30, "breakCount": 0}, "r1"),
    _e("k1", 3, "break", {"orig": 20, "now": 0}, "r1"),
    _e("s1", 4, "surface", {"mark": 5, "material": "block", "grade": "good", "breakCount": 1}, "r1"),
    _e("x1", 5, "run_end", {"end": 10, "result": "ok", "missing": []}, "r1"),
]
_ri = E.route_input(_ev, _pk)
check("끊김 전 턱 위치", abs(_ri["barriers"][0]["s"] - 8.0) < 1e-9, str(_ri["barriers"][0]["s"]))
check("끊김 뒤 노면 위치", abs(_ri["surfaces"][0]["s"] - 25.0) < 1e-9, str(_ri["surfaces"][0]["s"]))

# 완주 뒤 일시 막힘 재방문: 값은 완주한 측정에서, 막힘은 상태로 얹는다
_ev = [
    _e("r1", 1, "run_start", {"seg": 0, "from": 10, "start": 0}),
    _e("p1", 2, "slope", {"mark": 5, "values": [6.5], "method": "one", "cross": [1.0], "kind": "gap"}, "r1"),
    _e("x1", 3, "run_end", {"end": 30, "result": "ok", "missing": []}, "r1"),
    _e("r2", 4, "run_start", {"seg": 0, "from": 10, "start": 0, "retry": "again"}),
    _e("x2", 5, "run_end", {"end": 2, "result": "temp_block", "missing": []}, "r2"),
]
_ri = E.route_input(_ev, _pk)
check("완주 값 유지", len(_ri["values"]) == 1 and _ri["segments"][0]["run"] == "r1", str(_ri["segments"]))
check("막힘 상태 얹음", _ri["segments"][0].get("blocked") == "temp_block", str(_ri["segments"]))
# 사람이 고른 측정이 이긴다
_ri = E.route_input(_ev, _pk, runs={"0": "r2"})
check("사람이 고른 측정", _ri["segments"][0]["run"] == "r2", str(_ri["segments"]))


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

# 4단계: 저녁 검사와 경로 입력 ---------------------------------------------------
pk4 = {
    "site": "s", "net": "n", "test": False, "hash": "p", "rules": rules, "map": {"zoom": 19, "origin": [0, 0], "mpp": 0.25},
    "segs": [
        {"seg": 0, "a": 10, "b": 11, "len": 40.0, "xy": [0, 0, 160, 0], "prio": 2},
        {"seg": 1, "a": 11, "b": 12, "len": 30.0, "xy": [160, 0, 280, 0], "prio": 2},
    ],
    "walks": {"11": [{"seg": 0, "from": 10, "move": 0, "group": "p2"}, {"seg": 1, "from": 11, "move": 0, "group": "p2"}]},
}
base4 = [
    ev("d", 1, "day", {"measurer": "가", "recorder": "나", "date": "2026-11-23"}),
    ev("t", 2, "tool_check", {"when": "before", "tool": "level", "values": [1.0, 1.1], "passed": True}),
    ev("ps", 3, "tool_check", {"when": "before", "tool": "phone_setup", "passed": True}),
]


def codes_of(evs, pk=pk4):
    return sorted(x["code"] for x in E.inspect(evs, pk)["issues"])


# 공백: 시작에서 첫 지점 15 m, 마지막 지점에서 끝 15 m
g = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("g1", 5, "r0", 15, [1.0]),
    slope("g2", 6, "r0", 25, [1.0]),
    ev("e0", 7, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
]
_iss = [x for x in E.inspect(g, pk4)["issues"] if x["code"] == "gap"]
check("시작과 끝의 공백", len(_iss) == 2, _iss)

# 구간 사이 공백: 구간 0 끝에서 8 m 남고 구간 1 시작에서 8 m 떨어짐 (합 16 m)
g2 = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("a1", 5, "r0", 5, [1.0]), slope("a2", 6, "r0", 15, [1.0]), slope("a3", 7, "r0", 25, [1.0]), slope("a4", 8, "r0", 32, [1.0]),
    ev("e0", 9, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
    ev("r1", 10, "run_start", {"seg": 1, "from": 11, "start": 0}),
    slope("b1", 11, "r1", 8, [1.0]), slope("b2", 12, "r1", 18, [1.0]), slope("b3", 13, "r1", 26, [1.0]),
    ev("e1", 14, "run_end", {"end": 30, "result": "ok", "missing": []}, run="r1"),
]
check("구간 사이 공백", "gap_between" in codes_of(g2), codes_of(g2))

# 양 끝 부호 오류는 검사에 오르고 불확실로 둔다
bs = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("s1", 5, "r0", 5, [4.6, -4.7], method="both"),
    ev("e0", 6, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
]
check("양 끝 부호 검사", "both_sign" in codes_of(bs), codes_of(bs))
_v = E.route_input(bs, pk4)["values"][0]
check("양 끝 부호는 불확실", "manual" in _v["uncertain_for"] and "power" in _v["uncertain_for"], _v)

# 원값 범위: 대표값은 범위 안이어도 원값 하나가 밖이면 잡는다
rr = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("w1", 5, "r0", 5, [20.0, 3.0, 4.0], method="three"),
    ev("bb", 6, "barrier", {"type": "bump", "mark": 6, "value": 20, "value2": 400, "breakCount": 0}, run="r0"),
    ev("e0", 7, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
]
_c = codes_of(rr)
check("원값 범위", "range_long" in _c and "range_bump" in _c, _c)

# 이웃은 위치 순서로 비교한다: 5 m 0°, 15 m 2.9°, 뒤에 더한 10 m 3.5°
nb = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("n1", 5, "r0", 5, [0.0]), slope("n2", 6, "r0", 15, [2.9]), slope("n3", 7, "r0", 10, [3.5], kind="more"),
    ev("e0", 8, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
]
check("위치 순 이웃", "neighbor" in codes_of(nb), codes_of(nb))

# 일련번호 앞쪽 빠짐
sq = [dict(e, seq=e["seq"] + 3) for e in base4]
check("일련번호 앞쪽", "seq_gap" in codes_of(sq), codes_of(sq))

# 붙을 구간이 없는 기록
orp = base4 + [slope("o1", 4, "nope", 5, [1.0])]
check("붙을 곳 없는 기록", "orphan" in codes_of(orp), codes_of(orp))

# 아침 점검 없음
check("아침 점검 없음", "no_morning_check" in codes_of([base4[0]]), codes_of([base4[0]]))

# 불확실을 이동 수단별로
un = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("u1", 5, "r0", 5, [4.0, 4.3, 4.9], method="three"),
    slope("u2", 6, "r0", 15, [5.0, 5.2, 5.9], method="three"),
    ev("e0", 7, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
]
_vs = {v["event"]: v for v in E.route_input(un, pk4)["values"]}
check("4.8 걸침은 수동만", _vs["u1"]["uncertain_for"] == ["manual"], _vs["u1"]["uncertain_for"])
check("5.8 걸침은 전동만", _vs["u2"]["uncertain_for"] == ["power"], _vs["u2"]["uncertain_for"])
tf = base4[:1] + [ev("t", 2, "tool_check", {"when": "before", "tool": "level", "values": [1.0, 2.0], "passed": False, "mode": "no_judge"}), base4[2]] + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("f1", 5, "r0", 5, [1.0]),
    ev("e0", 6, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
]
_v = E.route_input(tf, pk4)["values"][0]
check("점검 실패는 수동과 전동", sorted(_v["uncertain_for"]) == ["manual", "power"], _v["uncertain_for"])

# 턱은 큰 값, 폭은 작은 값. 턱 18~22 mm는 불확실
bw = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    ev("k1", 5, "barrier", {"type": "bump", "mark": 6, "value": 19, "value2": 21, "breakCount": 0}, run="r0"),
    ev("k2", 6, "barrier", {"type": "width_rep", "mark": 0, "value": 104, "value2": 98, "breakCount": 0}, run="r0"),
    ev("k3", 7, "barrier", {"type": "bump", "mark": 9, "value": None, "unread": ["value"], "breakCount": 0}, run="r0"),
    ev("e0", 8, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
]
_bs = {b["event"]: b for b in E.route_input(bw, pk4)["barriers"]}
check("턱 대표값", _bs["k1"]["route_value"] == 21 and _bs["k1"]["uncertain_for"], _bs["k1"])
check("폭 대표값", _bs["k2"]["route_value"] == 98, _bs["k2"])
check("못 잰 턱 표시", _bs["k3"]["unmeasured"] is True, _bs["k3"])

# 시설과 지도 표시 확인에 구간과 위치를 넣는다
fc = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 11, "start": 0}),
    ev("fa", 5, "facility", {"type": "ramp", "mark": 10, "breakCount": 0}, run="r0"),
    ev("mc", 6, "map_check", {"mark": 12, "what": "x", "result": "wrong", "breakCount": 0}, run="r0"),
    ev("e0", 7, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
]
_ri = E.route_input(fc, pk4)
check("시설 위치", _ri["facilities"][0]["seg"] == 0 and near(_ri["facilities"][0]["s"], 30.0), _ri["facilities"][0])
check("지도 표시 구간", _ri["map_checks"][0]["seg"] == 0 and near(_ri["map_checks"][0]["s"], 28.0), _ri["map_checks"][0])

# 마친 뒤 실패 표시는 다음 통과로 사라지지 않는다
rt = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("q1", 5, "r0", 5, [1.0]),
    ev("e0", 6, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
    ev("t9", 7, "tool_check", {"when": "after", "tool": "level", "values": [1.0, 2.0], "passed": False}),
    ev("t10", 8, "tool_check", {"when": "before", "tool": "level", "values": [1.0, 1.1], "passed": True}),
]
check("실패 기간 유지", "tool_fail" in E.route_input(rt, pk4)["values"][0]["flags"])

# 저녁 확인 값은 이유가 있어야 한다
try:
    E.route_input(bs, pk4, overrides={"s1": {"long": 4.6}})
    check("저녁 확인 이유 필수", False)
except ValueError:
    check("저녁 확인 이유 필수", True)
_v = E.route_input(bs, pk4, overrides={"s1": {"long": 4.6, "why": "둘째 부호 잘못 누름"}})["values"][0]
check("저녁 확인 값", near(_v["long"], 4.6) and "evening" in _v["flags"], _v)

# 다른 연결망이나 시험 표시가 섞이면 경로 입력을 만들지 않는다
mx = base4 + [dict(ev("zz", 9, "day", {}), net="other")]
try:
    E.route_input(mx, pk4)
    check("섞인 기록 멈춤", False)
except ValueError:
    check("섞인 기록 멈춤", True)

# 길 아님 구간의 값은 경로 값에서 뺀다
npth = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("z1", 5, "r0", 5, [1.0]),
    ev("e0", 6, "run_end", {"end": None, "result": "not_path", "missing": []}, run="r0"),
]
check("길 아님 값 뺌", not E.route_input(npth, pk4)["values"])

# 위치는 구간 안으로 자르고 경고한다
oc = base4 + [
    ev("r0", 4, "run_start", {"seg": 1, "from": 11, "start": 0}),
    slope("c1", 5, "r0", 5, [1.0]),
    ev("e0", 6, "run_end", {"end": 4, "result": "stopped", "missing": []}, run="r0"),
    slope("c2", 7, "r0", 34, [1.0]),
]
_vs = E.route_input(oc, pk4)["values"]
check("구간 밖 위치 자름", all(0 <= v["s"] <= 30 for v in _vs), [v["s"] for v in _vs])
check("구간 밖 경고", "out_of_seg" in codes_of(oc), codes_of(oc))

# 지도 표시 확인도 사진을 센다
mp = base4 + [ev("m2", 4, "map_check", {"mark": None, "what": "x", "result": "right", "photos_required": 1})]
check("지도 표시 사진", "photos" in codes_of(mp), codes_of(mp))


# 13번: 저녁 고침 파일과 끊김 지우기 ---------------------------------------------
fx = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    slope("h1", 5, "r0", 10, [1.0]),
    ev("e0", 6, "run_end", {"end": 120, "result": "ok", "missing": []}, run="r0"),
]
check("고치기 전 배율", near(E.route_input(fx, pk4)["values"][0]["s"], 40 * 10 / 120))
_fx = E.apply_fixes(fx, [{"of": "e0", "data": {"end": 40}, "why": "자릿수를 잘못 눌렀음"}], pk4)
check("끝값 고침", near(E.route_input(_fx, pk4)["values"][0]["s"], 10.0))
check("고침으로 생긴 검사 오류 없음", not {"seq_gap", "orphan", "pack_mismatch", "net_mismatch", "test_mismatch"} & set(codes_of(_fx)), codes_of(_fx))
check("원본 사건은 그대로", len(fx) + 1 == len(_fx) and fx[-1]["data"]["end"] == 120)
_fx = E.apply_fixes(fx, [{"of": "r0", "data": {"seg": 1, "from": 11}, "why": "구간을 잘못 골랐음"}], pk4)
_seg = E.route_input(_fx, pk4)["segments"][0]
check("구간과 출발 마디 고침", _seg["seg"] == 1 and _seg["from"] == 11, _seg)
for bad_fix, name in (([{"of": "e0", "data": {"end": 40}}], "이유 없음"), ([{"of": "없는번호", "data": {}, "why": "x"}], "없는 사건")):
    try:
        E.apply_fixes(fx, bad_fix, pk4)
        check("저녁 고침 거부 " + name, False)
    except ValueError:
        check("저녁 고침 거부 " + name, True)

# 끊김을 지우면 뒤 기록은 남은 끊김만 쓴다: 끊김 1을 지운 뒤 손 계산 3번 지점 = 10 + 3 = 13 m
vb = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    ev("k1", 5, "break", {"orig": 20, "now": 0}, run="r0"),
    slope("v1", 6, "r0", 5, [1.0], breaks=1),
    ev("k2", 7, "break", {"orig": 10, "now": 0}, run="r0"),
    slope("v2", 8, "r0", 3, [1.0], breaks=2),
    ev("e0", 9, "run_end", {"end": 40, "result": "stopped", "missing": []}, run="r0"),
]
_fx = E.apply_fixes(vb, [{"void": "k1", "why": "끊김을 잘못 넣었음"}], pk4)
_vs = {v["event"]: v for v in E.route_input(_fx, pk4)["values"]}
check("지운 끊김 앞 지점", near(_vs["v1"]["s"], 5.0), _vs["v1"]["s"])
check("지운 끊김 뒤 지점", near(_vs["v2"]["s"], 13.0), _vs["v2"]["s"])


# 2라운드 필수 ---------------------------------------------------------------------
for c in cases["plan"]:
    got = [[p["mark"], p["kind"], p["both"], p["cross"]] for p in E.plan_marks(c["len"], c["fine"], c.get("stop"), rules, c.get("inclines"))]
    check("재는 지점 " + c["name"], got == c["want"], got)
for c in cases["pending"]:
    _plan = [{"mark": m[0], "kind": m[1], "both": bool(m[2]), "cross": True} if isinstance(m, list) else {"mark": m, "kind": "fine" if c["fine"] else "gap", "both": False, "cross": True} for m in c["plan"]]
    _saved = [dict(zip(("mark", "long", "kind", "added", "target", "n"), x)) for x in c["saved"]]
    got = [[p["mark"], p["kind"]] for p in E.pending_marks(_plan, _saved, c["len"], c["fine"], rules, c.get("stop"))]
    check("남은 지점 " + c["name"], got == c["want"], got)
for c in cases["run_missing"]:
    got = E.run_missing(c["run"], c["geo"], rules)
    check("못 잰 항목 " + c["name"], got == c["want"], got)


def _closed(end, result, missing=()):
    return base4 + [
        ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
        slope("m1", 5, "r0", 5, [1.0]),
        ev("w", 6, "barrier", {"type": "width_rep", "mark": 0, "value": 180}, run="r0"),
        ev("n", 7, "surface", {"mark": 0, "material": "block", "grade": "good"}, run="r0"),
        ev("e0", 8, "run_end", {"end": end, "result": result, "missing": list(missing)}, run="r0"),
    ]


# 닫은 구간을 고치면 저장값이 아니라 지금 원값으로 판정한다
_ev = _closed(12, "stopped") + [ev("f0", 9, "fix", {"of": "e0", "data": {"end": 40, "result": "ok"}}, run="r0")]
_seg = E.route_input(_ev, pk4)["segments"][0]
check("고친 구간 다시 판정", _seg["status"] == "partial" and "slope_points" in _seg["missing"], _seg)
_ev = _closed(12, "stopped") + [ev("v0", 9, "void", {"of": "m1"}, run="r0")]
check("전 지점 지운 구간", "slope" in E.route_input(_ev, pk4)["segments"][0]["missing"])
_ev = _closed(12, "stopped", ["other"])
check("사람이 더한 항목 유지", E.route_input(_ev, pk4)["segments"][0]["missing"] == ["other"])

# 길이 경고로 다시 재면 뒤의 맞는 측정을 고른다
_ev = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}), slope("a1", 5, "r0", 5, [1.0]), ev("e0", 6, "run_end", {"end": 50, "result": "ok", "missing": []}, run="r0"),
    ev("r1", 7, "run_start", {"seg": 0, "from": 10, "start": 0}), slope("a2", 8, "r1", 5, [1.0]), ev("e1", 9, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r1"),
]
check("다시 잰 측정 고름", E.route_input(_ev, pk4)["segments"][0]["run"] == "r1")

# 닫지 않은 측정의 값은 경로에 넣지 않는다
_ev = base4 + [ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}), slope("o1", 5, "r0", 5, [6.5])]
_ri = E.route_input(_ev, pk4)
check("열린 측정 값 뺌", _ri["segments"][0]["status"] == "open" and not _ri["values"], _ri["values"])

# 사람이 고른 측정은 검증한다
_ev = _closed(40, "ok") + [ev("r9", 9, "run_start", {"seg": 0, "from": 10, "start": 0})]
for _bad, _name in (({"0": "없는번호"}, "없는 번호"), ({"1": "r0"}, "다른 구간"), ({"0": "r9"}, "닫지 않은 측정")):
    try:
        E.route_input(_ev, pk4, runs=_bad)
        check("고른 측정 거부 " + _name, False)
    except ValueError:
        check("고른 측정 거부 " + _name, True)

# 시설 기울기와 차량 진출입부에도 점검 실패를 붙인다
_fail = [base4[0], ev("t", 2, "tool_check", {"when": "before", "tool": "level", "values": [1.0, 2.0], "passed": False, "mode": "no_judge"}), base4[2]]
_ev = _fail + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    ev("fa", 5, "facility", {"type": "ramp", "mark": 5, "slope_low": 4.0}, run="r0"),
    ev("dr", 6, "barrier", {"type": "driveway", "mark": 6, "cross": 3.0}, run="r0"),
    ev("e0", 7, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
]
_ri = E.route_input(_ev, pk4)
check("시설 점검 실패", "tool_fail" in _ri["facilities"][0]["flags"] and _ri["facilities"][0]["uncertain_for"] == ["manual", "power"], _ri["facilities"][0])
check("차량 진출입부 점검 실패", "tool_fail" in _ri["barriers"][0]["flags"], _ri["barriers"][0])
_ev = base4 + [
    ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}),
    ev("fa", 5, "facility", {"type": "ramp", "mark": 5, "slope_low": 4.0}, run="r0"),
    ev("e0", 6, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0"),
    ev("t9", 7, "tool_check", {"when": "after", "tool": "level", "values": [1.0, 2.0], "passed": False}),
]
check("시설 마친 뒤 실패", "tool_fail" in E.route_input(_ev, pk4)["facilities"][0]["flags"])

# 저녁 확인: 값이 있어야 표시가 풀린다. 없는 번호와 숫자 아닌 값은 멈춘다
_ev = base4 + [ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}), slope("b1", 5, "r0", 5, [4.0, 4.3, 4.9], method="three"), ev("e0", 6, "run_end", {"end": 40, "result": "ok", "missing": []}, run="r0")]
_v = E.route_input(_ev, pk4, overrides={"b1": {"why": "사진으로 판단 못 함"}})["values"][0]
check("이유만 있으면 경계 유지", "boundary" in _v["flags"] and _v["uncertain_for"] == ["manual"] and "evening" not in _v["flags"], _v)
_v = E.route_input(_ev, pk4, overrides={"b1": {"long": 4.3, "why": "돌 하나"}})["values"][0]
check("값이 있으면 경계 해제", "boundary" not in _v["flags"] and "evening" in _v["flags"] and _v["evening_why"] == "돌 하나", _v)
for _bad, _name in (({"없는사건": {"long": 1.0, "why": "x"}}, "없는 번호"), ({"b1": {"long": "많이", "why": "x"}}, "숫자 아님")):
    try:
        E.route_input(_ev, pk4, overrides=_bad)
        check("저녁 확인 거부 " + _name, False)
    except ValueError:
        check("저녁 확인 거부 " + _name, True)

# 저녁 고침은 낮의 고침 뒤에 적용하고, 지운 사진은 세지 않는다
_ev = base4 + [ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}), ev("m", 5, "run_edit", {"changes": {"start": 3}, "why": "fix_run"}, run="r0")]
check("낮 고침 뒤 저녁 고침", E.fold(E.apply_fixes(_ev, [{"of": "r0", "data": {"start": 2}, "why": "다시 봄"}], pk4))["runs"]["r0"]["start"] == 2)
_ev = base4 + [ev("r0", 4, "run_start", {"seg": 0, "from": 10, "start": 0}), ev("ph", 5, "photo", {"of": "m1"}, run="r0"), slope("m1", 6, "r0", 5, [1.0])]
check("지운 사진", E.fold(E.apply_fixes(_ev, [{"void": "ph", "why": "잘못 누름"}], pk4))["photos"].get("m1", 0) == 0)


print(f"시험 {count}개, 실패 {len(fails)}개")
for f in fails:
    print("  실패:", str(f)[:300])
sys.exit(1 if fails else 0)
