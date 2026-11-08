"""측정이 끝난 저녁의 PC 도구. 백업 파일이나 데이터베이스에서 기록을 읽어 검사하고 경로 입력 파일을 만든다.

실행:
  python -I tools/evening.py 백업.txt --pack 자료.json --out 결과폴더 [--photos 사진폴더] [--overrides 저녁확인.json] [--allow-test]
  python -I tools/evening.py --db --pack 자료.json --out 결과폴더

저녁 확인 값 파일 형식: {"사건번호": {"long": 5.0, "why": "바퀴 줄 전체"}}. 이유(why)가 없으면 멈춘다.
고른 측정 파일 형식(--runs): {"구간 번호": "구간 측정 번호"}. 같은 구간을 여러 번 쟀을 때 사람이 경로에 쓸 측정을 정한다.
저녁 고침 파일 형식(--fixes): [{"of": "사건번호", "data": {"end": 15.3}, "unset": [], "why": "이유"}, {"void": "사건번호", "why": "이유"}].
시작값, 구간, 출발 마디는 run_start 사건을, 끝값과 결과는 run_end 사건을 고친다. 원본 사건은 그대로 두고 고침 사건을 더한다.
규칙은 측정 매뉴얼 9장 다, 마와 tools/rules.json을 따른다. 앱의 docs/js/calc.js와 같은 시험값(tests/calc_cases.json)을 통과한다.
"""
import argparse
import csv
import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EPS = 1e-9
FORMAT = "bf-route-input-1"


def at_least(value, limit):
    return value >= limit - EPS


def in_ranges(x, ranges):
    return any(at_least(x, lo) and at_least(hi, x) for lo, hi in ranges)


def long_route(values, method):
    if not values:
        return None
    if method == "both" and len(values) >= 2:
        return (values[0] + values[1]) / 2
    if method == "three" and len(values) >= 3:
        return sorted(values, key=abs)[1]
    return values[0]


def cross_route(values, method):
    if not values:
        return None
    mags = [abs(v) for v in values]
    if method == "both" and len(mags) >= 2:
        return (mags[0] + mags[1]) / 2
    if method == "three" and len(mags) >= 3:
        return mags[1]
    return mags[0]


def is_boundary(values, limits):
    mags = [abs(v) for v in values]
    return any(any(at_least(m, lim) for m in mags) and any(not at_least(m, lim) for m in mags) for lim in limits)


def continued(mark, start, breaks):
    dist, frm = 0.0, start
    for b in breaks:
        dist += b["orig"] - frm
        frm = b["now"]
    return dist + (mark - frm)


def length_mismatch(measured, map_len, rules):
    diff = abs(measured - map_len)
    return diff > rules["check"]["len_m"] + EPS and diff / map_len * 100 > rules["check"]["len_pct"] + EPS


def map_position(map_len, mark, start, end, breaks, second, reached, long_value, mark_breaks=None):
    """매뉴얼 9장 다. 돌려주는 값은 (구간표 첫 마디에서 잰 거리, 구간표 방향의 앞뒤 경사)."""
    dist = continued(mark, start, breaks if mark_breaks is None else mark_breaks)
    if reached and end is not None:
        total = continued(end, start, breaks)
        s = map_len * dist / total if abs(total) > EPS else dist
    else:
        s = dist
    if second:
        s = map_len - s
        long_value = -long_value if long_value is not None else None
    return s, long_value


# 재는 지점과 못 잰 항목. 앱의 calc.js와 같은 규칙이고 같은 시험값(calc_cases.json)을 통과한다 --------
def round1(x):
    return math.floor(x * 10 + 0.5) / 10


def round2(x):
    return math.floor(x * 100 + 0.5) / 100


def in_fine(m, fine):
    return any(m > a + EPS and m <= b + EPS for a, b in fine)


def plan_marks(length, fine, stop, rules, inclines=None):
    S = rules["slope"]
    fine = fine or []

    def point(m, kind="gap", both=False, cross=True):
        return {"mark": m, "kind": kind, "both": both, "cross": cross}

    if length < S["short_skip"]:
        return [point(round1(length / 2))] if inclines and any(v > 0 for v in inclines) else []
    if length < S["short_mid"]:
        return [point(round1(length / 2))]
    limit = length if stop is None else stop
    out = {}
    m = S["first"]
    while m < limit - EPS:
        if not in_fine(m, fine):
            out[round1(m)] = point(round1(m))
        m += S["step"]
    for a, b in fine:
        top = min(b, limit)
        for step in (S["fine_step"], S["fine_both_step"]):
            m = math.ceil((a + EPS) / step) * step
            while m <= top + EPS and m < limit - EPS:
                if m > 0:
                    q = m / S["fine_both_step"]
                    multiple = abs(q - math.floor(q + 0.5)) < EPS
                    out[round1(m)] = point(round1(m), "fine", multiple, multiple)
                m += step
    items = sorted(out.values(), key=lambda p: p["mark"])
    if not items:
        return [point(round1(limit / 2))]
    if limit - items[-1]["mark"] > S["end_gap"] + EPS:
        items.append(point(round1(limit - S["end_back"]), "end"))
    return items


def pending_marks(plan, saved, length, fine, rules, stop=None):
    S = rules["slope"]
    fine = fine or []
    limit = length if stop is None else stop

    def near(a, b):
        return abs(a - b) <= S["match_tol"] + EPS

    pool = [dict(p) for p in plan]
    for p in saved:
        if p.get("kind") == "more" or p.get("long") is None or in_fine(p["mark"], fine) or not at_least(abs(p["long"]), S["more_from"]):
            continue
        for d in (-S["more_dist"], S["more_dist"]):
            m = round1(p["mark"] + d)
            if m > EPS and m < limit - EPS and not any(near(x["mark"], m) for x in pool):
                pool.append({"mark": m, "kind": "more", "both": False, "cross": True})
    used = set()
    top = max((p["mark"] for p in saved if p.get("kind") != "more" and not p.get("added")), default=-math.inf)

    def take(p):
        if p.get("kind") == "end" and p["mark"] >= top - EPS:
            for i, x in enumerate(pool):
                if i not in used and x["kind"] == "end":
                    return i
        if p.get("target") is not None:
            for i, x in enumerate(pool):
                if i not in used and abs(x["mark"] - p["target"]) < 1e-6:
                    if near(x["mark"], p["mark"]):
                        return i
                    break
        best = -1
        for i, x in enumerate(pool):
            if i in used or not near(x["mark"], p["mark"]):
                continue
            if x.get("both") and p.get("n") is not None and p["n"] < 2:
                continue
            if best < 0 or abs(x["mark"] - p["mark"]) < abs(pool[best]["mark"] - p["mark"]):
                best = i
        return best

    for p in saved:
        if p.get("added"):
            continue
        i = take(p)
        if i >= 0:
            used.add(i)
    return sorted((x for i, x in enumerate(pool) if i not in used), key=lambda x: x["mark"])


def geo_for(seg, frm):
    fine = [[a, b] if frm == seg["a"] else [round2(seg["len"] - b), round2(seg["len"] - a)] for a, b in (seg.get("fine") or [])]
    st = seg.get("stop")
    return {"len": seg["len"], "fine": sorted(fine, key=lambda x: x[0]), "stop": st["m"] if st and st.get("from") == frm else None, "inclines": seg.get("inclines")}


def left_marks(r, geo, rules):
    if r["result"] not in ("ok", "stopped"):
        return []
    plan = plan_marks(geo["len"], geo["fine"], geo["stop"], rules, geo.get("inclines"))
    breaks = r["breaks"]
    saved = []
    for p in r["points"]:
        if p.get("values"):
            saved.append({"mark": continued(p["mark"], r["start"], breaks[: p.get("breakCount", len(breaks))]), "long": long_route(p["values"], p.get("method") or "one"), "kind": p.get("kind"), "added": p.get("added"), "target": p.get("target"), "n": len(p["values"])})
    left = pending_marks(plan, saved, geo["len"], geo["fine"], rules, geo["stop"])
    if r["end"] is None:
        return [] if r["result"] == "stopped" else left
    measured = continued(r["end"], r["start"], breaks)
    S = rules["slope"]
    kept = left if r["result"] == "ok" and length_mismatch(measured, geo["len"], rules) else [p for p in left if p["mark"] < measured - S["match_tol"] - EPS]
    if r["result"] != "ok":
        return kept
    reach = min(measured, geo["stop"]) if geo["stop"] is not None else measured
    last = max([p["mark"] for p in saved + kept] + [0])
    if reach - last <= S["end_gap"] + EPS:
        return kept
    return kept + [{"mark": round1(reach - S["end_back"]), "kind": "end", "both": False, "cross": True}]


def cross_unread(p, rules):
    """좌우 '못 잼': 값이 없거나, 재확인 범위의 첫 값만 있고 둘째를 못 읽었다."""
    if not p.get("no_cross"):
        return False
    c = p.get("cross") or []
    return not c or (len(c) == 1 and in_ranges(abs(c[0]), rules["slope"]["cross_recheck"]))


def run_missing(r, geo, rules):
    """구간 측정의 못 잰 항목. 저장한 값이 아니라 지금의 원값으로 계산한다(매뉴얼 1장 나 5, 9장 다)."""
    if r["result"] not in ("ok", "stopped"):
        return []
    out = []
    if not any(p.get("values") for p in r["points"]):
        out.append("slope")
    elif left_marks(r, geo, rules):
        out.append("slope_points")
    if geo["len"] >= rules["width"]["skip_len"] and not any(b.get("type") == "width_rep" and b.get("value") is not None for b in r["barriers"]):
        out.append("width")
    if not r["surfaces"]:
        out.append("surface")
    if any(b.get("unread") for b in r["barriers"]):
        out.append("barrier_value")
    if any(cross_unread(p, rules) for p in r["points"]):
        out.append("cross")
    if r.get("no_barrier") == "not_looked":
        out.append("barrier_look")
    return out


# 사건 쌓기 ----------------------------------------------------------------------
def time_of(e):
    return datetime.fromisoformat(e["at"].replace("Z", "+00:00")).timestamp()


def order_of(e):
    """순서 번호. 앱의 calc.js orderOf와 같다. 번호가 없는 옛 기록은 시각(ms)."""
    o = e.get("ord")
    if isinstance(o, (int, float)) and not isinstance(o, bool):
        return o
    return round(time_of(e) * 1000)


def sort_events(events):
    seen = {}
    for e in events:
        seen.setdefault(e["id"], e)
    return sorted(seen.values(), key=lambda e: (order_of(e), str(e.get("dev")), e.get("seq") or 0))


def fold(events):
    ev = sort_events(events)
    fixes, voided = {}, set()
    for e in ev:
        if e["kind"] == "fix":
            fixes.setdefault(e["data"]["of"], []).append(e)
        elif e["kind"] == "void":
            voided.add(e["data"]["of"])
    S = {"runs": {}, "order": [], "photos": {}, "facilities": [], "map_checks": [], "new_paths": {}, "route_choice": None, "tool_checks": [], "redo": [], "day": None, "days": [], "seq": {}, "events": ev, "orphans": []}
    level_fail = None
    for e in ev:
        S["seq"].setdefault(e.get("dev"), []).append(e.get("seq") or 0)
        k = e["kind"]
        if k in ("fix", "void", "track"):
            continue
        if e["id"] in voided:
            continue
        if k == "photo":
            of = e["data"].get("of")
            if of:
                S["photos"][of] = S["photos"].get(of, 0) + 1
            continue
        d = dict(e["data"])
        for f in fixes.get(e["id"], []):
            d.update(f["data"]["data"])
            for key in f["data"].get("unset") or []:
                d.pop(key, None)
        d["_id"], d["_at"], d["_gps"], d["_ord"] = e["id"], e["at"], e.get("gps"), e.get("ord")
        d["_rev"] = 1 + len(fixes.get(e["id"], []))
        d["_level_fail"] = level_fail
        if k == "day":
            S["day"] = d
            S["days"].append(d)
        elif k == "tool_check":
            S["tool_checks"].append(d)
            if d.get("tool") == "level":
                level_fail = None if d.get("passed") else (d.get("mode") or "no_judge")
        elif k == "run_start":
            S["runs"][e["id"]] = {"id": e["id"], "seg": d["seg"], "from": d["from"], "start": d.get("start") or 0, "line": d.get("line") or "main", "route_line": bool(d.get("routeLine")), "retry": d.get("retry") or "", "planned_stop": d.get("planned_stop"), "wet": bool(d.get("wet")), "points": [], "barriers": [], "surfaces": [], "breaks": [], "closed": False, "end": None, "result": None, "missing": [], "planned": False, "at": e["at"], "gps": []}
            S["order"].append(e["id"])
        elif k == "run_edit":
            r = S["runs"].get(e.get("run"))
            if r:
                r.update(d.get("changes") or {})
        elif k in ("slope", "barrier", "surface", "break"):
            r = S["runs"].get(e.get("run"))
            if not r:
                # 시작 사건보다 앞에 오거나 붙을 구간 측정이 없는 기록. 버리지 않고 검사에 올린다.
                S["orphans"].append({"kind": k, "id": e["id"], "run": e.get("run")})
                continue
            # 끊김 수는 쌓는 순서로 센다. 앞의 끊김을 지워도 뒤 기록이 다음 끊김을 받지 않는다(앱의 withBreaks와 같다).
            if k != "break":
                d["breakCount"] = len(r["breaks"])
            if k == "slope":
                d["_level_fail"] = level_fail
                r["points"].append(d)
            elif k == "barrier":
                r["barriers"].append(d)
            elif k == "surface":
                r["surfaces"].append(d)
            else:
                r["breaks"].append(d)
            if e.get("gps"):
                r["gps"].append(e["gps"])
        elif k in ("facility", "map_check"):
            d["_run"] = e.get("run")
            r = S["runs"].get(e.get("run"))
            if r:
                d["breakCount"] = len(r["breaks"])
            S["facilities" if k == "facility" else "map_checks"].append(d)
        elif k == "new_path":
            S["new_paths"][d["no"]] = d
        elif k == "route_choice":
            S["route_choice"] = d
        elif k == "redo":
            S["redo"].append(d)
        elif k == "run_end":
            r = S["runs"].get(e.get("run"))
            if r:
                r.update(closed=True, end=d.get("end"), result=d.get("result"), missing=d.get("missing") or [], planned=bool(d.get("planned")), reason=d.get("reason"), ended=e["at"], end_id=e["id"], no_barrier=d.get("no_barrier"), twin=d.get("twin"))
    return S


def seg_info(S, pack, seg_id):
    if isinstance(seg_id, str):
        n = S["new_paths"].get(seg_id)
        if not n:
            return None
        return {"seg": seg_id, "a": f"{seg_id}a", "b": f"{seg_id}b", "len": n["len"], "xy": n["xy"], "new": True}
    segs = pack["segs"]
    return segs[seg_id] if 0 <= seg_id < len(segs) else None


def run_status(r):
    if not r["closed"]:
        return "open"
    if r["result"] == "ok":
        return "partial" if r["missing"] else "done"
    return {"stopped": "partial", "not_path": "not_path", "no_entry": "no_entry", "temp_block": "temp_block"}.get(r["result"], "partial")


def ord_of(rec):
    """쌓은 기록(d)의 순서 번호."""
    return order_of({"ord": rec.get("_ord"), "at": rec["_at"]})


def retro_fail_from(S):
    """마친 뒤 점검이 실패하면 그 앞 마지막 통과부터 실패까지의 값에 점검 실패를 붙인다(매뉴얼 10장 나 4).
    기간 목록을 돌려준다. 다음 통과가 와도 지난 기간은 남는다."""
    periods, last_ok = [], None
    for t in S["tool_checks"]:
        if t.get("tool") != "level":
            continue
        if t.get("passed"):
            last_ok = t
        elif t.get("when") == "after":
            periods.append((ord_of(last_ok) if last_ok else -math.inf, ord_of(t)))
    return periods


def point_flags(p, retro, rules):
    # 경계 표시는 저장값을 믿지 않고 값으로 다시 정한다(앱의 calc.js slopePoint와 같다)
    flags = [f for f in (p.get("flags") or []) if f != "boundary"]
    method = p.get("method") or "one"
    values = p.get("values") or []
    if method == "three" and len(values) == 3 and is_boundary(values, rules["slope"]["bound_long"]):
        flags.append("boundary")
    if p.get("_level_fail") and "tool_fail" not in flags:
        flags.append("tool_fail")
    if retro and "tool_fail" not in flags and any(a <= ord_of(p) <= b for a, b in retro):
        flags.append("tool_fail")
    if both_sign(p):
        flags.append("both_sign")
    return flags


def both_sign(p):
    """양 끝 두 값의 부호가 다르고 각 크기가 0.5° 이상(앱의 checkPoint both_sign과 같다)."""
    v = p.get("values") or []
    return (p.get("method") or "one") == "both" and len(v) == 2 and (v[0] > 0) != (v[1] > 0) and abs(v[0]) >= 0.5 and abs(v[1]) >= 0.5


def uncertain_modes(slg, flags, values, rules):
    """이동 수단별 불확실. 4.8° 걸침은 수동, 5.8° 걸침은 전동, 점검 실패와 양 끝 부호 오류는 수동과 전동."""
    U, B = rules["uncertain"], rules["slope"]["bound_long"]
    out = set()
    mag = abs(slg) if slg is not None else None
    if mag is not None and in_ranges(mag, [U["manual_long"]]):
        out.add("manual")
    if mag is not None and in_ranges(mag, [U["power_long"]]):
        out.add("power")
    if "boundary" in flags and values:
        if is_boundary(values, B[:1]):
            out.add("manual")
        if len(B) > 1 and is_boundary(values, B[1:2]):
            out.add("power")
    if "tool_fail" in flags or "both_sign" in flags:
        out |= {"manual", "power"}
    return [m for m in ("manual", "power", "stroller") if m in out]


UNREAD_TYPES = ("bump", "gap", "width_rep", "narrow")


def barrier_route(b, rules):
    """매뉴얼 9장 다: 턱은 큰 값, 폭은 작은 값 하나만 넘긴다. 턱 18~22 mm는 불확실(v2 결정 8)."""
    t = b.get("type")
    vals = [v for v in (b.get("value"), b.get("value2")) if v is not None]
    out = {"route_value": None, "uncertain_for": []}
    if t == "bump":
        out["route_value"] = max(vals) if vals else None
        lo, hi = rules["bump"]["recheck_mm"]
        if any(lo - EPS <= v <= hi + EPS for v in vals):
            out["uncertain_for"] = ["manual", "power", "stroller"]
    elif t in ("width_rep", "narrow"):
        vals = vals + ([b["min_cm"]] if b.get("min_cm") is not None else [])
        out["route_value"] = min(vals) if vals else None
    out["unmeasured"] = bool(b.get("unread")) or (t in UNREAD_TYPES and b.get("value") is None)
    return out


def run_place(r, seg, m, rec):
    """구간 측정 안의 표시값을 구간표 첫 마디에서 잰 거리로 바꾼다. 저장할 때의 끊김 수(breakCount)까지만 쓴다."""
    if m is None:
        return None
    nb = rec.get("breakCount", len(r["breaks"]))
    second = r["from"] == seg["b"]
    reached = r["result"] == "ok" and r["end"] is not None
    return map_position(seg["len"], m, r["start"], r["end"], r["breaks"], second, reached, 0.0, r["breaks"][:nb])[0]


def clip(s, seg_len):
    if s is None:
        return None, False
    if s < -EPS or s > seg_len + EPS:
        return min(max(s, 0.0), seg_len), True
    return s, False


def recheck_missing(S, pack):
    """닫은 구간의 못 잰 항목을 지금의 원값으로 다시 계산한다. 사람이 더한 항목(other)만 저장값을 쓴다."""
    for r in S["runs"].values():
        seg = seg_info(S, pack, r["seg"]) if r["closed"] else None
        if seg:
            r["missing"] = run_missing(r, geo_for(seg, r["from"]), pack["rules"]) + [m for m in r["missing"] if m == "other"]


def fail_flags(rec, retro):
    """시설 기울기와 차량 진출입부에도 점검 실패를 붙인다(매뉴얼 10장 나 4)."""
    return ["tool_fail"] if rec.get("_level_fail") or any(a <= ord_of(rec) <= b for a, b in retro) else []


def apply_fixes(events, fixes, pack):
    """저녁에 사람이 고친 값을 사건으로 더한다. 원본 사건은 건드리지 않는다. 이유가 없거나 없는 사건을 가리키면 멈춘다."""
    kinds = {e["id"]: e["kind"] for e in events}
    top = max((order_of(e) for e in events), default=0)
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = list(events)
    for i, x in enumerate(fixes, 1):
        target = x.get("of") or x.get("void")
        if not str(x.get("why") or "").strip():
            raise ValueError(f"저녁 고침에 이유(why)가 없습니다: {target}")
        if target not in kinds:
            raise ValueError(f"저녁 고침이 없는 사건을 가리킵니다: {target}")
        kind = "fix" if x.get("of") else "void"
        data = {"of": target, "why": x["why"]}
        ev = {"id": f"evening-{i}", "seq": i, "ord": top + i, "kind": kind, "at": at, "dev": "evening", "app": "evening", "site": pack["site"], "test": bool(pack.get("test")), "net": pack["net"], "pack": pack.get("hash"), "rules": pack["rules"].get("version"), "data": data}
        if kind == "fix" and kinds[target] == "run_start":
            # 낮에 run_edit로 고친 값 뒤에 적용되도록 구간 고침 사건으로 넣는다
            ev.update(kind="run_edit", run=target, data={"changes": x.get("data") or {}, "why": x["why"]})
        elif kind == "fix":
            data.update(data=x.get("data") or {}, unset=x.get("unset") or [])
        out.append(ev)
    return out


def check_events(S, pack, allow_test=False):
    """다른 연결망, 대상지, 시험 표시의 기록이 섞이면 멈춘다."""
    if pack.get("test") and not allow_test:
        raise ValueError("시험 자료는 경로 계산에 넣지 않습니다")
    bad = [e["id"] for e in S["events"] if (e.get("net") and e["net"] != pack["net"]) or (e.get("site") and e["site"] != pack["site"]) or bool(e.get("test")) != bool(pack.get("test"))]
    if bad:
        raise ValueError(f"다른 연결망, 대상지, 시험 표시의 기록 {len(bad)}건이 섞여 있습니다: {bad[:5]}")


# 경로 입력 --------------------------------------------------------------------
VALUE_RESULTS = ("ok", "stopped")
BLOCK_RESULTS = ("temp_block", "no_entry", "not_path")


def measured_len(r):
    if r["end"] is None:
        return 0.0
    return continued(r["end"], r["start"], r["breaks"])


def choose_runs(S, pack, runs=None):
    """구간마다 경로 값에 쓸 구간 측정을 고른다.
    닫힌 측정 가운데 값을 잰 것(ok, 끝까지 못 감)만 고르고, 경로 줄, 길 맞음, 길이 경고 없음, 못 잰 항목 없음, 나중 순이다.
    잰 길이는 끝까지 못 감끼리만 비교한다. 길이 경고로 다시 잰 구간에서 앞의 틀린 측정이 뽑히지 않게 한다.
    길 아님, 출입 금지, 일시 막힘은 값을 지우지 않고 구간 상태(blocked)로 얹는다. 그 뒤에 길이 경고 없는 완주가 있어야 풀린 것으로 본다.
    끝까지 못 감은 막힘이 그대로일 수 있고, 길이 경고가 있는 완주는 다른 길을 걸었을 수 있어서 근거로 쓰지 않는다.
    runs: {구간: 측정 번호}로 사람이 바꾼다. 막힘 측정을 고르면 그 결과를 유지한다. 값으로 쓸 측정을 고르는 것과 막힘을 푸는 것은 별개다."""
    runs = {str(k): v for k, v in (runs or {}).items()}
    for k, v in runs.items():
        r = S["runs"].get(v)
        if not r or str(r["seg"]) != k or not r["closed"]:
            raise ValueError(f"고른 측정을 쓸 수 없습니다(없거나 다른 구간이거나 닫히지 않음): 구간 {k}, 측정 {v}")

    def long_warn(x):
        seg = seg_info(S, pack, x["seg"])
        return bool(seg) and x["result"] == "ok" and x["end"] is not None and length_mismatch(measured_len(x), seg["len"], pack["rules"])

    by_seg = {}
    for rid in S["order"]:
        by_seg.setdefault(S["runs"][rid]["seg"], []).append(S["runs"][rid])
    best, blocked = {}, {}
    for seg, rs in by_seg.items():
        closed = [r for r in rs if r["closed"]]
        pick = runs.get(str(seg))
        cand = [r for r in closed if r["result"] in VALUE_RESULTS]
        if pick and pick in S["runs"] and S["runs"][pick]["seg"] == seg:
            best[seg] = S["runs"][pick]
        elif cand:
            rank = lambda x: (x["route_line"], x["result"] == "ok", not long_warn(x), not x["missing"], measured_len(x) if x["result"] == "stopped" else 0.0, S["order"].index(x["id"]))
            best[seg] = max(cand, key=rank)
        elif closed:
            best[seg] = closed[-1]
        else:
            best[seg] = rs[-1]
        if pick and best[seg]["result"] in BLOCK_RESULTS:
            blocked[seg] = best[seg]["result"]
            continue
        passed = [r for r in closed if r["result"] == "ok" and not long_warn(r)]
        since = max((S["order"].index(r["id"]) for r in passed), default=-1)
        blocks = [r for r in closed if r["result"] in BLOCK_RESULTS and S["order"].index(r["id"]) > since]
        if blocks:
            blocked[seg] = blocks[-1]["result"]
    return best, blocked


def route_input(events, pack, overrides=None, allow_test=False, runs=None):
    overrides = overrides or {}
    no_why = [k for k, o in overrides.items() if not str(o.get("why") or "").strip()]
    if no_why:
        raise ValueError(f"저녁 확인 값에 이유(why)가 없습니다: {no_why[:5]}")
    S = fold(events)
    check_events(S, pack, allow_test)
    recheck_missing(S, pack)
    known = {p["_id"] for r in S["runs"].values() for p in r["points"]}
    for k, o in overrides.items():
        if k not in known:
            raise ValueError(f"저녁 확인 값이 없는 지점을 가리킵니다: {k}")
        if "long" in o and (isinstance(o["long"], bool) or not isinstance(o["long"], (int, float)) or not math.isfinite(o["long"])):
            raise ValueError(f"저녁 확인 값이 숫자가 아닙니다: {k}")
    rules = pack["rules"]
    retro = retro_fail_from(S)
    best, blocked = choose_runs(S, pack, runs)
    segments, values, barriers, surfaces = [], [], [], []
    for seg_id, r in best.items():
        seg = seg_info(S, pack, seg_id)
        if not seg:
            continue
        second = r["from"] == seg["b"]
        reached = r["result"] == "ok" and r["end"] is not None
        missing = sorted(r["missing"])
        status = run_status(r)
        reached_m = None
        if r["end"] is not None:
            reached_m = continued(r["end"], r["start"], r["breaks"])
        segments.append({
            "seg": seg_id, "run": r["id"], "from": r["from"], "second": second, "line": r["line"], "route_line": r["route_line"], "status": status,
            "result": r["result"], "reached_m": reached_m, "planned_stop": r["planned"], "missing": missing, "wet": r["wet"], "retry": r["retry"],
            "other_runs": [x for x in S["order"] if S["runs"][x]["seg"] == seg_id and x != r["id"]],
            "blocked": blocked.get(seg_id), "no_barrier": r.get("no_barrier"), "twin": r.get("twin"),
        })
        # 닫지 않은 측정과 길 아님으로 닫은 측정의 값은 경로 값에 넣지 않는다
        if not r["closed"] or r["result"] == "not_path":
            continue
        for p in r["points"]:
            method = p.get("method") or "one"
            raw = p.get("values") or []
            lg = long_route(raw, method)
            cross_vals = p.get("cross") or []
            cr = cross_route(cross_vals, "both" if len(cross_vals) == 2 else method)
            flags = point_flags(p, retro, rules)
            # 확인 값이 있어야 경계와 부호 표시가 풀린다. 이유만 있으면 불확실로 둔다(매뉴얼 9장 마 3)
            o = overrides.get(p["_id"])
            confirmed = o is not None and "long" in o
            if confirmed:
                lg = o["long"]
                flags = [f for f in flags if f not in ("boundary", "both_sign")] + ["evening"]
            mb = r["breaks"][: p.get("breakCount", len(r["breaks"]))]
            s, slg = map_position(seg["len"], p["mark"], r["start"], r["end"], r["breaks"], second, reached, lg, mb)
            s, out = clip(s, seg["len"])
            if out:
                flags = flags + ["out_of_seg"]
            unc = uncertain_modes(slg, flags, [] if confirmed else raw, rules)
            if unc:
                flags = flags + ["uncertain"]
            values.append({
                "event": p["_id"], "seg": seg_id, "s": s, "long": slg, "long_pct": math.tan(math.radians(slg)) * 100 if slg is not None else None,
                "cross": cr, "cross_pct": math.tan(math.radians(cr)) * 100 if cr is not None else None, "kind": p.get("kind"), "method": method,
                "raw": p.get("values"), "raw_cross": cross_vals, "mark": p["mark"], "flags": flags, "uncertain_for": unc, "at": p["_at"], "rev": p["_rev"], "evening_why": o["why"] if o else None,
            })
        for b in r["barriers"]:
            ends = sorted(x for x in (clip(run_place(r, seg, b.get("mark"), b), seg["len"])[0], clip(run_place(r, seg, b.get("mark_end"), b), seg["len"])[0]) if x is not None)
            item = {**{k: v for k, v in b.items() if not k.startswith("_")}, "event": b["_id"], "seg": seg_id, "s": ends[0] if ends else None, "s_end": ends[1] if len(ends) > 1 else None, "walk_second": second, "at": b["_at"], "rev": b["_rev"]}
            item.update(barrier_route(b, rules))
            item["flags"] = fail_flags(b, retro) if b.get("type") == "driveway" and b.get("cross") is not None else []
            if item["flags"]:
                item["uncertain_for"] = ["manual", "power"]
            barriers.append(item)
        for b in r["surfaces"]:
            surfaces.append({**{k: v for k, v in b.items() if not k.startswith("_")}, "event": b["_id"], "seg": seg_id, "s": clip(run_place(r, seg, b.get("mark"), b), seg["len"])[0], "at": b["_at"]})

    def placed(rec):
        r = S["runs"].get(rec.get("_run"))
        seg = seg_info(S, pack, r["seg"]) if r else None
        if not seg:
            return {"run": rec.get("_run"), "seg": None, "s": None}
        return {"run": r["id"], "seg": r["seg"], "s": clip(run_place(r, seg, rec.get("mark"), rec), seg["len"])[0]}

    facilities = []
    for f in S["facilities"]:
        item = {k: v for k, v in f.items() if not k.startswith("_")}
        item.update(event=f["_id"], at=f["_at"], gps=f.get("_gps"), **placed(f))
        item["flags"] = fail_flags(f, retro) if any(f.get(k) is not None for k in ("slope", "slope_low", "slope_mid", "slope_top")) else []
        item["uncertain_for"] = ["manual", "power"] if item["flags"] else []
        facilities.append(item)
    map_checks = []
    for m in S["map_checks"]:
        item = {k: v for k, v in m.items() if not k.startswith("_")}
        item.update(event=m["_id"], at=m["_at"], **placed(m))
        map_checks.append(item)
    digest = hashlib.sha256(json.dumps(sorted(e["id"] for e in S["events"])).encode()).hexdigest()[:12]
    return {
        "format": FORMAT, "site": pack["site"], "net": pack["net"], "pack": pack.get("hash"), "rules": rules.get("version"), "test": bool(pack.get("test")),
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "events_hash": digest, "event_count": len(S["events"]),
        "event_versions": sorted({f"{e.get('app')}/{e.get('pack')}/{e.get('rules')}" for e in S["events"]}),
        "overrides_hash": hashlib.sha256(json.dumps(overrides, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12] if overrides else None,
        "segments": segments, "values": values, "barriers": barriers, "surfaces": surfaces, "facilities": facilities, "map_checks": map_checks,
        "new_paths": list(S["new_paths"].values()), "route_choice": {k: v for k, v in (S["route_choice"] or {}).items() if not k.startswith("_")} or None,
        "tool_checks": [{k: v for k, v in t.items() if not k.startswith("_")} | {"at": t["_at"]} for t in S["tool_checks"]],
    }


# 저녁 검사 --------------------------------------------------------------------
def merc_px(lon, lat, m):
    n = 256 * 2 ** m["zoom"]
    s = math.sin(math.radians(lat))
    return (lon + 180) / 360 * n - m["origin"][0], (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n - m["origin"][1]


def dist_polyline(px, py, xy):
    best = math.inf
    for i in range(0, len(xy) - 3, 2):
        ax, ay, bx, by = xy[i], xy[i + 1], xy[i + 2], xy[i + 3]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2)) if L2 else 0.0
        best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
    return best


def local_day(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().date().isoformat()


def inspect(events, pack):
    S = fold(events)
    recheck_missing(S, pack)
    rules = pack["rules"]
    R, Ck = rules["range"], rules["check"]
    issues = []

    def add(code, msg, seg=None, run=None, event=None):
        issues.append({"code": code, "msg": msg, "seg": seg, "run": run, "event": event})

    for e in S["events"]:
        if e.get("net") and e["net"] != pack["net"]:
            add("net_mismatch", f"다른 연결망의 기록: {e['id']}", event=e["id"])
            break
    for e in S["events"]:
        if bool(e.get("test")) != bool(pack.get("test")):
            add("test_mismatch", f"시험 표시가 자료와 다른 기록: {e['id']}", event=e["id"])
            break
    vers = {(e.get("pack"), e.get("rules")) for e in S["events"] if e.get("pack") or e.get("rules")}
    if any(p_ and p_ != pack.get("hash") or r_ and r_ != rules.get("version") for p_, r_ in vers):
        add("pack_mismatch", f"자료 판이나 규칙표 판이 다른 기록이 있습니다: {sorted(map(str, vers))[:4]}")
    for dev, seqs in S["seq"].items():
        want = set(range(1, max(seqs) + 1)) if seqs else set()
        missing = sorted(want - set(seqs))
        if missing:
            add("seq_gap", f"폰 {dev}의 빠진 일련번호 {len(missing)}개: {missing[:10]}")
    for o in S["orphans"]:
        add("orphan", f"붙을 구간 측정이 없는 {o['kind']} 기록: {o['id']}", event=o["id"])

    # 아침 점검: 측정한 날마다 출발 전 수평계 점검이 있어야 한다
    days = {d.get("date") or local_day(d["_at"]) for d in S["days"]}
    checked = {local_day(t["_at"]) for t in S["tool_checks"] if t.get("tool") == "level" and t.get("when") == "before"}
    for d in sorted(days - checked):
        add("no_morning_check", f"{d}: 출발 전 도구 점검 기록이 없습니다")

    retro = retro_fail_from(S)
    photo_need = {}
    by_seg = {}
    for rid in S["order"]:
        r = S["runs"][rid]
        by_seg.setdefault(r["seg"], []).append(r)
        seg = seg_info(S, pack, r["seg"])
        if not seg:
            add("unknown_seg", f"구간표에 없는 구간 {r['seg']}", seg=r["seg"], run=rid)
            continue
        measured = measured_len(r) if r["end"] is not None else None
        if not r["closed"]:
            add("open_run", f"구간 확인 없는 구간 {r['seg']}", seg=r["seg"], run=rid)
        elif measured is not None and r["result"] == "ok":
            if length_mismatch(measured, seg["len"], rules):
                add("length", f"구간 {r['seg']}: 잰 길이 {measured:.1f} m, 지도 {seg['len']:.1f} m", seg=r["seg"], run=rid)
        elif measured is not None and r["result"] == "stopped" and measured > seg["len"] + Ck["len_m"] + EPS:
            add("length", f"구간 {r['seg']}: 끝까지 못 감인데 잰 길이 {measured:.1f} m가 지도 {seg['len']:.1f} m보다 깁니다", seg=r["seg"], run=rid)
        for m in sorted(r["missing"]):
            add("missing", f"구간 {r['seg']} 못 잰 항목: {m}", seg=r["seg"], run=rid)
        prev_mark = None
        pts = []
        for p in r["points"]:
            d = continued(p["mark"], r["start"], r["breaks"][: p.get("breakCount", len(r["breaks"]))])
            method = p.get("method") or "one"
            raw = p.get("values") or []
            lg = long_route(raw, method)
            cross_vals = p.get("cross") or []
            tag = f"구간 {r['seg']} 표시값 {p['mark']}"
            if any(abs(v) > R["long"] + EPS for v in raw):
                add("range_long", f"{tag}: 앞뒤 원값 {raw}", seg=r["seg"], run=rid, event=p["_id"])
            if any(abs(v) > R["cross"] + EPS for v in cross_vals):
                add("range_cross", f"{tag}: 좌우 원값 {cross_vals}", seg=r["seg"], run=rid, event=p["_id"])
            if both_sign(p):
                add("both_sign", f"{tag}: 양 끝 두 값 {raw}의 부호가 다릅니다", seg=r["seg"], run=rid, event=p["_id"])
            kind = p.get("kind")
            if kind != "more" and not p.get("added"):
                if prev_mark is not None and d < prev_mark - EPS:
                    add("mark_down", f"{tag}: 표시값이 줄어듦", seg=r["seg"], run=rid, event=p["_id"])
                prev_mark = d
            if lg is not None:
                pts.append((d, lg, p))
            if "boundary" in point_flags(p, None, rules):
                add("boundary", f"{tag}: 경계 값. 사진과 메모로 정하세요", seg=r["seg"], run=rid, event=p["_id"])
            s, _ = map_position(seg["len"], p["mark"], r["start"], r["end"], r["breaks"], r["from"] == seg["b"], r["result"] == "ok" and r["end"] is not None, 0.0, r["breaks"][: p.get("breakCount", len(r["breaks"]))])
            if clip(s, seg["len"])[1]:
                add("out_of_seg", f"{tag}: 위치 {s:.1f} m가 구간(0~{seg['len']:.1f} m) 밖입니다", seg=r["seg"], run=rid, event=p["_id"])
            photo_need[p["_id"]] = (p.get("photos_required") or 0, tag, r["seg"], rid)
        # 공백과 이웃은 위치 순서로 본다. 시작과 끝(못 갔으면 멈춘 곳)을 넣는다.
        pts.sort(key=lambda x: x[0])
        if pts and r["closed"] and r["result"] in VALUE_RESULTS and seg["len"] >= rules["slope"]["short_skip"]:
            stops = [0.0] + [x[0] for x in pts] + ([measured] if measured is not None else [])
            for a_, b_ in zip(stops, stops[1:]):
                if b_ - a_ > Ck["gap_m"] + EPS:
                    add("gap", f"구간 {r['seg']}: {a_:.1f}~{b_:.1f} m 사이 {b_ - a_:.1f} m에 잰 지점이 없습니다", seg=r["seg"], run=rid)
        for (d1, l1, _p1), (d2, l2, p2) in zip(pts, pts[1:]):
            if abs(l1 - l2) > Ck["neighbor_deg"] + EPS:
                add("neighbor", f"구간 {r['seg']} 표시값 {p2['mark']}: 이웃과 {abs(l1 - l2):.1f}° 차이", seg=r["seg"], run=rid, event=p2["_id"])
        for b in r["barriers"] + r["surfaces"]:
            need = b.get("photos_required") or 0
            photo_need[b["_id"]] = (need, f"구간 {r['seg']} {b.get('type') or '노면'} 표시값 {b.get('mark')}", r["seg"], rid)
            if b.get("type") == "bump" and any(v is not None and v > R["bump_mm"] for v in (b.get("value"), b.get("value2"))):
                add("range_bump", f"구간 {r['seg']}: 턱 {b.get('value')}, {b.get('value2')} mm", seg=r["seg"], run=rid, event=b["_id"])
            if b.get("type") in ("width_rep", "narrow") and any(v is not None and not (R["width_cm"][0] <= v <= R["width_cm"][1]) for v in (b.get("value"), b.get("value2"), b.get("min_cm"))):
                add("range_width", f"구간 {r['seg']}: 폭 {b.get('value')}, {b.get('value2')} cm", seg=r["seg"], run=rid, event=b["_id"])
            if b.get("type") == "driveway" and ((b.get("cross") or 0) > R["cross"] + EPS or (b.get("bump_mm") or 0) > R["bump_mm"]):
                add("range_driveway", f"구간 {r['seg']}: 차량 진출입부 좌우 {b.get('cross')}°, 턱 {b.get('bump_mm')} mm", seg=r["seg"], run=rid, event=b["_id"])
        if r["gps"] and pack.get("map"):
            ds = []
            for g in r["gps"]:
                if g.get("lon") is None:
                    continue
                x, y = merc_px(g["lon"], g["lat"], pack["map"])
                ds.append(dist_polyline(x, y, seg["xy"]) * pack["map"]["mpp"])
            if ds and sum(ds) / len(ds) > Ck["mean_dist_m"]:
                add("gps_far", f"구간 {r['seg']}: 기록 위치가 고른 선에서 평균 {sum(ds) / len(ds):.0f} m", seg=r["seg"], run=rid)
    for seg_id, rs in by_seg.items():
        if sum(1 for r in rs if r["closed"]) > 1:
            add("multi_run", f"구간 {seg_id}: 닫힌 측정 {sum(1 for r in rs if r['closed'])}개. 경로에 쓸 측정을 확인하세요(--runs)", seg=seg_id)
    for f in S["facilities"]:
        photo_need[f["_id"]] = (f.get("photos_required") or 0, f"시설 {f.get('type')}", None, f.get("_run"))
        for k in ("slope", "slope_low", "slope_mid", "slope_top"):
            if f.get(k) is not None and abs(f[k]) > R["long"] + EPS:
                add("range_facility", f"시설 {f.get('type')}: {k} {f[k]}°", run=f.get("_run"), event=f["_id"])
    for m in S["map_checks"]:
        photo_need[m["_id"]] = (m.get("photos_required") or 0, f"지도 표시 확인 {m.get('what')}", None, m.get("_run"))
    for i, (need, tag, seg, rid) in photo_need.items():
        got = S["photos"].get(i, 0)
        if got < need:
            add("photos", f"{tag}: 사진 요구 {need}장, 찍음 {got}장", seg=seg, run=rid, event=i)

    # 구간 사이 공백: 걷는 순서의 이웃 구간에서 앞 구간 끝 공백 + 안 잰 구간 + 다음 구간 시작 공백
    best, _ = choose_runs(S, pack)
    walks = pack.get("walks") or {}
    choice = (S["route_choice"] or {}).get("route") or "11"
    carry = None
    for w in walks.get(choice, []):
        if (w.get("move") or 0) > 3:
            carry = None
        seg = seg_info(S, pack, w["seg"])
        r = best.get(w["seg"])
        ds = []
        if seg and r and r["closed"] and r["result"] in VALUE_RESULTS:
            for p in r["points"]:
                if not p.get("values"):
                    continue
                s, _ = map_position(seg["len"], p["mark"], r["start"], r["end"], r["breaks"], r["from"] == seg["b"], r["result"] == "ok" and r["end"] is not None, 0.0, r["breaks"][: p.get("breakCount", len(r["breaks"]))])
                s = clip(s, seg["len"])[0]
                ds.append(s if w["from"] == seg["a"] else seg["len"] - s)
        if not seg:
            carry = None
            continue
        if not ds:
            carry = None if carry is None else carry + seg["len"]
            continue
        head = min(ds)
        if carry is not None and carry + head > Ck["gap_m"] + EPS:
            add("gap_between", f"구간 {w['seg']} 앞: 앞 구간의 마지막 지점에서 {carry + head:.1f} m 동안 잰 지점이 없습니다", seg=w["seg"])
        carry = seg["len"] - max(ds)

    measured_segs = {S["runs"][x]["seg"] for x in S["order"]}
    for w in walks.get(choice, []):
        if w["seg"] not in measured_segs:
            add("unvisited", f"순서에 있는데 안 잰 구간 {w['seg']}", seg=w["seg"])
    for t in S["tool_checks"]:
        if t.get("passed") is False and t.get("tool") != "phone_setup":
            add("tool_fail", f"도구 점검 실패: {t.get('tool')} ({t.get('when')}), 값 {t.get('values')}")
    return {"issues": issues, "state": S, "retro": retro}


REDO_CODES = {"length", "range_long", "range_cross", "mark_down", "gap", "gap_between", "neighbor", "both_sign", "gps_far", "open_run", "unvisited", "missing", "out_of_seg"}
LABEL = {
    "length": "길이 차이", "range_long": "앞뒤 범위 밖", "range_cross": "좌우 범위 밖", "range_bump": "턱 범위 밖", "range_width": "폭 범위 밖", "range_driveway": "차량 진출입부 범위 밖",
    "range_facility": "시설 기울기 범위 밖", "mark_down": "표시값 감소", "gap": "11 m 넘는 공백", "gap_between": "구간 사이 11 m 넘는 공백", "neighbor": "이웃과 3° 넘는 차이",
    "both_sign": "양 끝 부호 다름", "boundary": "경계 값", "open_run": "구간 확인 없음", "photos": "사진 부족", "missing": "못 잰 항목", "unvisited": "안 잰 순위 구간",
    "gps_far": "위치가 선에서 멂", "tool_fail": "도구 점검 실패", "seq_gap": "일련번호 빠짐", "net_mismatch": "연결망 불일치", "test_mismatch": "시험 표시 불일치",
    "pack_mismatch": "자료·규칙표 판 다름", "unknown_seg": "없는 구간", "photo_files": "사진 파일 수", "orphan": "붙을 곳 없는 기록", "no_morning_check": "아침 점검 없음",
    "out_of_seg": "구간 밖 위치", "multi_run": "같은 구간 측정 여러 개",
}


def photo_files(folder, S):
    from PIL import Image

    stamps = []
    for p in Path(folder).rglob("*"):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".heic", ".png"):
            continue
        ts = None
        try:
            ex = Image.open(p).getexif()
            v = ex.get(36867) or ex.get(306)
            if v:
                ts = datetime.strptime(v, "%Y:%m:%d %H:%M:%S").astimezone().timestamp()
        except Exception:
            ts = None
        stamps.append(ts if ts is not None else p.stat().st_mtime)
    out = []
    for rid in S["order"]:
        r = S["runs"][rid]
        t0 = time_of({"at": r["at"]})
        t1 = time_of({"at": r.get("ended") or r["at"]}) if r.get("ended") else t0 + 3600
        out.append({"seg": r["seg"], "run": rid, "files": sum(1 for x in stamps if t0 - 30 <= x <= t1 + 30)})
    return out, len(stamps)


def fetch_db(pack):
    env = {}
    for line in (Path.home() / ".keys" / "barrierfree.env").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    url, key = env["SUPABASE_URL"], env["SUPABASE_PUBLISHABLE_KEY"]
    body = json.dumps({"email": env["SUPABASE_FIELD_EMAIL_1"], "password": env["SUPABASE_FIELD_PASSWORD_1"]}).encode()
    rq = urllib.request.Request(f"{url}/auth/v1/token?grant_type=password", data=body, headers={"apikey": key, "Content-Type": "application/json"})
    token = json.load(urllib.request.urlopen(rq))["access_token"]
    out, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"select": "payload", "payload->>site": f"eq.{pack['site']}", "order": "recorded_at.asc,id.asc", "limit": 1000, "offset": offset})
        rq = urllib.request.Request(f"{url}/rest/v1/field_records?{q}", headers={"apikey": key, "Authorization": f"Bearer {token}"})
        rows = json.load(urllib.request.urlopen(rq))
        out += [r["payload"] for r in rows]
        if len(rows) < 1000:
            return out
        offset += 1000


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("backup", nargs="?")
    ap.add_argument("--db", action="store_true")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--photos")
    ap.add_argument("--overrides")
    ap.add_argument("--runs")
    ap.add_argument("--fixes")
    ap.add_argument("--allow-test", action="store_true")
    a = ap.parse_args()
    pack = json.loads(Path(a.pack).read_text(encoding="utf-8"))
    pack.pop("aerial", None)
    if a.db:
        events = fetch_db(pack)
    else:
        b = json.loads(Path(a.backup).read_text(encoding="utf-8"))
        if b.get("net") != pack["net"]:
            raise SystemExit("백업과 자료 파일의 연결망이 다릅니다")
        events = b["events"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    raw_events = events
    if a.fixes:
        events = apply_fixes(events, json.loads(Path(a.fixes).read_text(encoding="utf-8")), pack)
    report = inspect(events, pack)
    S = report["state"]
    overrides = json.loads(Path(a.overrides).read_text(encoding="utf-8")) if a.overrides else None
    runs = json.loads(Path(a.runs).read_text(encoding="utf-8")) if a.runs else None
    ri = route_input(events, pack, overrides, allow_test=a.allow_test, runs=runs)
    (out / "경로입력.json").write_text(json.dumps(ri, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "기록_원본.json").write_text(json.dumps(sort_events(raw_events), ensure_ascii=False), encoding="utf-8")

    lines = [f"# 저녁 검사 결과 ({pack['site']})", "", f"- 기록 {len(S['events'])}건, 구간 측정 {len(S['order'])}개, 닫힌 것 {sum(1 for r in S['runs'].values() if r['closed'])}개", f"- 연결망 {pack['net']}, 규칙표 {pack['rules']['version']}", ""]
    if a.photos:
        pf, total = photo_files(a.photos, S)
        taken = {}
        for e in S["events"]:
            if e["kind"] == "photo" and e.get("run"):
                taken[e["run"]] = taken.get(e["run"], 0) + 1
        for x in pf:
            if x["files"] != taken.get(x["run"], 0):
                report["issues"].append({"code": "photo_files", "msg": f"구간 {x['seg']}: 시간 안의 사진 파일 {x['files']}장, 앱의 찍음 {taken.get(x['run'], 0)}장", "seg": x["seg"], "run": x["run"], "event": None})
        lines += [f"사진 파일 {total}장", "", "| 구간 | 시간 안의 사진 | 앱의 찍음 |", "|---|---:|---:|"] + [f"| {x['seg']} | {x['files']} | {taken.get(x['run'], 0)} |" for x in pf] + [""]
    order = sorted(report["issues"], key=lambda i: (i["code"], str(i["seg"])))
    lines += ["| 종류 | 내용 |", "|---|---|"] + [f"| {LABEL.get(i['code'], i['code'])} | {i['msg']} |" for i in order]
    (out / "검사결과.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (out / "다시잴목록.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["구간", "종류", "내용"])
        for i in order:
            if i["code"] in REDO_CODES:
                w.writerow([i["seg"], LABEL.get(i["code"], i["code"]), i["msg"]])
    print(f"검사 {len(report['issues'])}건, 경로 값 {len(ri['values'])}개, 구간 {len(ri['segments'])}개")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
