"""측정이 끝난 저녁의 PC 도구. 백업 파일이나 데이터베이스에서 기록을 읽어 검사하고 경로 입력 파일을 만든다.

실행:
  python -I tools/evening.py 백업.txt --pack 자료.json --out 결과폴더 [--photos 사진폴더] [--overrides 저녁확인.json] [--allow-test]
  python -I tools/evening.py --db --pack 자료.json --out 결과폴더

저녁 확인 값 파일 형식: {"사건번호": {"long": 5.0, "why": "바퀴 줄 전체"}}
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


# 사건 쌓기 ----------------------------------------------------------------------
def time_of(e):
    return datetime.fromisoformat(e["at"].replace("Z", "+00:00")).timestamp()


def sort_events(events):
    seen = {}
    for e in events:
        seen.setdefault(e["id"], e)
    return sorted(seen.values(), key=lambda e: (time_of(e), str(e.get("dev")), e.get("seq") or 0))


def fold(events):
    ev = sort_events(events)
    fixes, voided = {}, set()
    for e in ev:
        if e["kind"] == "fix":
            fixes.setdefault(e["data"]["of"], []).append(e)
        elif e["kind"] == "void":
            voided.add(e["data"]["of"])
    S = {"runs": {}, "order": [], "photos": {}, "facilities": [], "map_checks": [], "new_paths": {}, "route_choice": None, "tool_checks": [], "redo": [], "day": None, "seq": {}, "events": ev}
    level_fail = None
    for e in ev:
        S["seq"].setdefault(e.get("dev"), []).append(e.get("seq") or 0)
        k = e["kind"]
        if k in ("fix", "void", "track"):
            continue
        if k == "photo":
            of = e["data"].get("of")
            if of:
                S["photos"][of] = S["photos"].get(of, 0) + 1
            continue
        if e["id"] in voided:
            continue
        d = dict(e["data"])
        for f in fixes.get(e["id"], []):
            d.update(f["data"]["data"])
        d["_id"], d["_at"], d["_gps"] = e["id"], e["at"], e.get("gps")
        d["_rev"] = 1 + len(fixes.get(e["id"], []))
        if k == "day":
            S["day"] = d
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
                continue
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
        elif k == "facility":
            d["_run"] = e.get("run")
            S["facilities"].append(d)
        elif k == "map_check":
            d["_run"] = e.get("run")
            S["map_checks"].append(d)
        elif k == "new_path":
            S["new_paths"][d["no"]] = d
        elif k == "route_choice":
            S["route_choice"] = d
        elif k == "redo":
            S["redo"].append(d)
        elif k == "run_end":
            r = S["runs"].get(e.get("run"))
            if r:
                r.update(closed=True, end=d.get("end"), result=d.get("result"), missing=d.get("missing") or [], planned=bool(d.get("planned")), reason=d.get("reason"), ended=e["at"], end_id=e["id"])
    return S


def seg_info(S, pack, seg_id):
    if isinstance(seg_id, str):
        n = S["new_paths"].get(seg_id)
        if not n:
            return None
        return {"seg": seg_id, "a": f"{seg_id}a", "b": f"{seg_id}b", "len": n["len"], "xy": n["xy"], "new": True}
    return pack["segs"][seg_id]


def run_status(r):
    if not r["closed"]:
        return "open"
    if r["result"] == "ok":
        return "partial" if r["missing"] else "done"
    return {"stopped": "partial", "not_path": "not_path", "no_entry": "no_entry", "temp_block": "temp_block"}.get(r["result"], "partial")


def retro_fail_from(S):
    """마친 뒤 점검이 실패하면 마지막 통과 뒤의 값에 점검 실패를 붙인다(매뉴얼 10장 나 4)."""
    last_ok = None
    fail_after = False
    for t in S["tool_checks"]:
        if t.get("tool") != "level":
            continue
        if t.get("passed"):
            last_ok = t["_at"]
            fail_after = False
        elif t.get("when") == "after":
            fail_after = True
    return last_ok if fail_after else None


def point_flags(p, retro, rules):
    flags = list(p.get("flags") or [])
    method = p.get("method") or "one"
    values = p.get("values") or []
    if method == "three" and len(values) == 3 and is_boundary(values, rules["slope"]["bound_long"]) and "boundary" not in flags:
        flags.append("boundary")
    if p.get("_level_fail") and "tool_fail" not in flags:
        flags.append("tool_fail")
    if retro and time_of({"at": p["_at"]}) >= time_of({"at": retro}) and "tool_fail" not in flags:
        flags.append("tool_fail")
    return flags


# 경로 입력 --------------------------------------------------------------------
def choose_runs(S):
    """구간마다 경로에 쓸 구간 측정을 고른다. 경로 줄 표시가 우선이고, 같은 조건이면 닫힌 것 중 나중 것이다."""
    best = {}
    for rid in S["order"]:
        r = S["runs"][rid]
        cur = best.get(r["seg"])
        if cur is None:
            best[r["seg"]] = r
            continue
        rank = lambda x: (x["route_line"], x["closed"], x["line"] == "main")
        if rank(r) >= rank(cur):
            best[r["seg"]] = r
    return best


def route_input(events, pack, overrides=None, allow_test=False):
    if pack.get("test") and not allow_test:
        raise ValueError("시험 자료는 경로 계산에 넣지 않습니다")
    overrides = overrides or {}
    S = fold(events)
    rules = pack["rules"]
    retro = retro_fail_from(S)
    best = choose_runs(S)
    segments, values, barriers, surfaces = [], [], [], []
    for seg_id, r in best.items():
        seg = seg_info(S, pack, seg_id)
        if not seg:
            continue
        second = r["from"] == seg["b"]
        reached = r["result"] == "ok" and r["end"] is not None
        status = run_status(r)
        reached_m = None
        if r["end"] is not None:
            reached_m = continued(r["end"], r["start"], r["breaks"])
        segments.append({
            "seg": seg_id, "run": r["id"], "from": r["from"], "second": second, "line": r["line"], "route_line": r["route_line"], "status": status,
            "result": r["result"], "reached_m": reached_m, "planned_stop": r["planned"], "missing": r["missing"], "wet": r["wet"], "retry": r["retry"],
            "other_runs": [x for x in S["order"] if S["runs"][x]["seg"] == seg_id and x != r["id"]],
        })
        for p in r["points"]:
            method = p.get("method") or "one"
            lg = long_route(p.get("values") or [], method)
            cross_vals = p.get("cross") or []
            cr = cross_route(cross_vals, "both" if len(cross_vals) == 2 else method)
            flags = point_flags(p, retro, rules)
            if p["_id"] in overrides:
                o = overrides[p["_id"]]
                lg = o.get("long", lg)
                flags = [f for f in flags if f != "boundary"] + ["evening"]
            if lg is None:
                s, slg = map_position(seg["len"], p["mark"], r["start"], r["end"], r["breaks"], second, reached, None, r["breaks"][: p.get("breakCount", len(r["breaks"]))])
            else:
                s, slg = map_position(seg["len"], p["mark"], r["start"], r["end"], r["breaks"], second, reached, lg, r["breaks"][: p.get("breakCount", len(r["breaks"]))])
            mag = abs(slg) if slg is not None else None
            unc = []
            if mag is not None and in_ranges(mag, [rules["uncertain"]["manual_long"]]):
                unc.append("manual")
            if mag is not None and in_ranges(mag, [rules["uncertain"]["power_long"]]):
                unc.append("power")
            if "boundary" in flags or "tool_fail" in flags:
                unc = ["manual", "power", "stroller"]
            if unc:
                flags = flags + ["uncertain"]
            values.append({
                "event": p["_id"], "seg": seg_id, "s": s, "long": slg, "long_pct": math.tan(math.radians(slg)) * 100 if slg is not None else None,
                "cross": cr, "cross_pct": math.tan(math.radians(cr)) * 100 if cr is not None else None, "kind": p.get("kind"), "method": method,
                "raw": p.get("values"), "raw_cross": cross_vals, "mark": p["mark"], "flags": flags, "uncertain_for": unc, "at": p["_at"], "rev": p["_rev"],
            })
        pos = lambda m: None if m is None else map_position(seg["len"], m, r["start"], r["end"], r["breaks"], second, reached, 0.0)[0]
        for b in r["barriers"]:
            barriers.append({**{k: v for k, v in b.items() if not k.startswith("_")}, "event": b["_id"], "seg": seg_id, "s": pos(b.get("mark")), "s_end": pos(b.get("mark_end")), "at": b["_at"], "rev": b["_rev"]})
        for b in r["surfaces"]:
            surfaces.append({**{k: v for k, v in b.items() if not k.startswith("_")}, "event": b["_id"], "seg": seg_id, "s": pos(b.get("mark")), "at": b["_at"]})
    facilities = []
    for f in S["facilities"]:
        r = S["runs"].get(f.get("_run"))
        item = {k: v for k, v in f.items() if not k.startswith("_")}
        item.update(event=f["_id"], seg=r["seg"] if r else None, at=f["_at"], gps=f.get("_gps"))
        facilities.append(item)
    digest = hashlib.sha256(json.dumps(sorted(e["id"] for e in S["events"])).encode()).hexdigest()[:12]
    return {
        "format": FORMAT, "site": pack["site"], "net": pack["net"], "pack": pack.get("hash"), "rules": rules.get("version"), "test": bool(pack.get("test")),
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "events_hash": digest, "event_count": len(S["events"]),
        "segments": segments, "values": values, "barriers": barriers, "surfaces": surfaces, "facilities": facilities,
        "map_checks": [{k: v for k, v in m.items() if not k.startswith("_")} for m in S["map_checks"]],
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


def inspect(events, pack):
    S = fold(events)
    rules = pack["rules"]
    R, Ck = rules["range"], rules["check"]
    issues = []

    def add(code, msg, seg=None, run=None, event=None):
        issues.append({"code": code, "msg": msg, "seg": seg, "run": run, "event": event})

    for e in S["events"]:
        if e.get("net") and e["net"] != pack["net"]:
            add("net_mismatch", f"다른 연결망의 기록: {e['id']}", event=e["id"])
            break
    for dev, seqs in S["seq"].items():
        want = set(range(min(seqs), max(seqs) + 1)) if seqs else set()
        missing = sorted(want - set(seqs))
        if missing:
            add("seq_gap", f"폰 {dev}의 빠진 일련번호 {len(missing)}개: {missing[:10]}")

    photo_need = {}
    for rid in S["order"]:
        r = S["runs"][rid]
        seg = seg_info(S, pack, r["seg"])
        if not seg:
            add("unknown_seg", f"구간표에 없는 구간 {r['seg']}", seg=r["seg"], run=rid)
            continue
        if not r["closed"]:
            add("open_run", f"구간 확인 없는 구간 {r['seg']}", seg=r["seg"], run=rid)
        elif r["end"] is not None and r["result"] == "ok":
            measured = continued(r["end"], r["start"], r["breaks"])
            if length_mismatch(measured, seg["len"], rules):
                add("length", f"구간 {r['seg']}: 잰 길이 {measured:.1f} m, 지도 {seg['len']:.1f} m", seg=r["seg"], run=rid)
        for m in r["missing"]:
            add("missing", f"구간 {r['seg']} 못 잰 항목: {m}", seg=r["seg"], run=rid)
        prev_mark = None
        max_mark = None
        prev_long = None
        for p in r["points"]:
            d = continued(p["mark"], r["start"], r["breaks"][: p.get("breakCount", len(r["breaks"]))])
            method = p.get("method") or "one"
            lg = long_route(p.get("values") or [], method)
            cross_vals = p.get("cross") or []
            cr = cross_route(cross_vals, "both" if len(cross_vals) == 2 else method)
            tag = f"구간 {r['seg']} 표시값 {p['mark']}"
            if lg is not None and abs(lg) > R["long"] + EPS:
                add("range_long", f"{tag}: 앞뒤 {lg}°", seg=r["seg"], run=rid, event=p["_id"])
            if cr is not None and abs(cr) > R["cross"] + EPS:
                add("range_cross", f"{tag}: 좌우 {cr}°", seg=r["seg"], run=rid, event=p["_id"])
            kind = p.get("kind")
            if kind != "more":
                if prev_mark is not None and d < prev_mark - EPS:
                    add("mark_down", f"{tag}: 표시값이 줄어듦", seg=r["seg"], run=rid, event=p["_id"])
                if max_mark is not None and d - max_mark > Ck["gap_m"] + EPS:
                    add("gap", f"{tag}: 앞 지점과 {d - max_mark:.1f} m", seg=r["seg"], run=rid, event=p["_id"])
                prev_mark = d
            if prev_long is not None and lg is not None and abs(prev_long - lg) > Ck["neighbor_deg"] + EPS:
                add("neighbor", f"{tag}: 이웃과 {abs(prev_long - lg):.1f}° 차이", seg=r["seg"], run=rid, event=p["_id"])
            if lg is not None:
                prev_long = lg
            max_mark = d if max_mark is None else max(max_mark, d)
            if "boundary" in point_flags(p, None, rules):
                add("boundary", f"{tag}: 경계 값. 사진과 메모로 정하세요", seg=r["seg"], run=rid, event=p["_id"])
            need = p.get("photos_required") or 0
            photo_need[p["_id"]] = (need, tag, r["seg"], rid)
        for b in r["barriers"] + r["surfaces"]:
            need = b.get("photos_required") or 0
            photo_need[b["_id"]] = (need, f"구간 {r['seg']} {b.get('type') or '노면'} 표시값 {b.get('mark')}", r["seg"], rid)
            if b.get("type") == "bump" and b.get("value") is not None and b["value"] > R["bump_mm"]:
                add("range_bump", f"구간 {r['seg']}: 턱 {b['value']} mm", seg=r["seg"], run=rid, event=b["_id"])
            if b.get("type") in ("width_rep", "narrow") and b.get("value") is not None and not (R["width_cm"][0] <= b["value"] <= R["width_cm"][1]):
                add("range_width", f"구간 {r['seg']}: 폭 {b['value']} cm", seg=r["seg"], run=rid, event=b["_id"])
        if r["gps"] and pack.get("map"):
            ds = []
            for g in r["gps"]:
                if g.get("lon") is None:
                    continue
                x, y = merc_px(g["lon"], g["lat"], pack["map"])
                ds.append(dist_polyline(x, y, seg["xy"]) * pack["map"]["mpp"])
            if ds and sum(ds) / len(ds) > Ck["mean_dist_m"]:
                add("gps_far", f"구간 {r['seg']}: 기록 위치가 고른 선에서 평균 {sum(ds) / len(ds):.0f} m", seg=r["seg"], run=rid)
    for f in S["facilities"]:
        photo_need[f["_id"]] = (f.get("photos_required") or 0, f"시설 {f.get('type')}", None, f.get("_run"))
    for i, (need, tag, seg, rid) in photo_need.items():
        got = S["photos"].get(i, 0)
        if got < need:
            add("photos", f"{tag}: 사진 요구 {need}장, 찍음 {got}장", seg=seg, run=rid, event=i)

    measured_segs = {S["runs"][x]["seg"] for x in S["order"]}
    walks = pack.get("walks") or {}
    choice = (S["route_choice"] or {}).get("route") or "11"
    for w in walks.get(choice, []):
        if w["seg"] not in measured_segs:
            add("unvisited", f"순서에 있는데 안 잰 구간 {w['seg']}", seg=w["seg"])
    for t in S["tool_checks"]:
        if t.get("passed") is False and t.get("tool") != "phone_setup":
            add("tool_fail", f"도구 점검 실패: {t.get('tool')} ({t.get('when')}), 값 {t.get('values')}")
    return {"issues": issues, "state": S}


REDO_CODES = {"length", "range_long", "range_cross", "mark_down", "gap", "neighbor", "gps_far", "open_run", "unvisited", "missing"}
LABEL = {
    "length": "길이 차이", "range_long": "앞뒤 범위 밖", "range_cross": "좌우 범위 밖", "range_bump": "턱 범위 밖", "range_width": "폭 범위 밖", "mark_down": "표시값 감소",
    "gap": "11 m 넘는 공백", "neighbor": "이웃과 3° 넘는 차이", "boundary": "경계 값", "open_run": "구간 확인 없음", "photos": "사진 부족", "missing": "못 잰 항목",
    "unvisited": "안 잰 순위 구간", "gps_far": "위치가 선에서 멂", "tool_fail": "도구 점검 실패", "seq_gap": "일련번호 빠짐", "net_mismatch": "연결망 불일치", "unknown_seg": "없는 구간", "photo_files": "사진 파일 수",
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
    report = inspect(events, pack)
    S = report["state"]
    overrides = json.loads(Path(a.overrides).read_text(encoding="utf-8")) if a.overrides else None
    ri = route_input(events, pack, overrides, allow_test=a.allow_test)
    (out / "경로입력.json").write_text(json.dumps(ri, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "기록_원본.json").write_text(json.dumps(sort_events(events), ensure_ascii=False), encoding="utf-8")

    lines = [f"# 저녁 검사 결과 ({pack['site']})", "", f"- 기록 {len(S['events'])}건, 구간 측정 {len(S['order'])}개, 닫힌 것 {sum(1 for r in S['runs'].values() if r['closed'])}개", f"- 연결망 {pack['net']}, 규칙표 {pack['rules']['version']}", ""]
    if a.photos:
        pf, total = photo_files(a.photos, S)
        lines += [f"사진 파일 {total}장", "", "| 구간 | 시간 안의 사진 |", "|---|---:|"] + [f"| {x['seg']} | {x['files']} |" for x in pf] + [""]
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
