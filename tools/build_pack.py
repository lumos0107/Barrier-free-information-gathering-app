"""현장 자료 파일을 만든다. 결과에는 항공사진과 그린 길이 들어가므로 저장소 밖에 둔다.

실행 (베리어프리 폴더에서):
  python -I Barrier-free-information-gathering-app/tools/build_pack.py --site minsokchon
  python -I Barrier-free-information-gathering-app/tools/build_pack.py --site samseong --test

구간 번호는 연결망에서 갈림길(이웃 선 3개 이상)과 길 끝, 정문에서만 끊어 매긴다. 측정을 시작한 뒤에는 연결망을 바꾸지 않는다.
"""
import argparse
import base64
import hashlib
import heapq
import io
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "공통자료" / "10_관광지지도"
OUT = DATA / "측정앱자료"
sys.path.insert(0, str(ROOT / "클라우드작업_-2" / "work" / "03_routing"))
import routing as R  # noqa: E402

TILE = 256
ROADS = {"service", "residential", "tertiary", "secondary", "primary", "unclassified"}


def merc_px(lon, lat, zoom):
    n = TILE * 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def build_segments(G):
    breaks = {i for i, a in enumerate(G.adj) if len(a) != 2}
    if G.start is not None:
        breaks.add(G.start)
    seen, segs = set(), []
    for n in sorted(breaks):
        for m, ei in G.adj[n]:
            if ei in seen:
                continue
            chain = [ei]
            seen.add(ei)
            cur = m
            while cur not in breaks:
                nxt = [(mm, ee) for mm, ee in G.adj[cur] if ee != chain[-1]]
                if not nxt:
                    break
                mm, ee = nxt[0]
                if ee in seen:
                    break
                chain.append(ee)
                seen.add(ee)
                cur = mm
            segs.append({"a": n, "b": cur, "edges": chain, "len": sum(G.edges[e]["len"] for e in chain)})
    for ei, e in enumerate(G.edges):
        if ei not in seen:
            segs.append({"a": e["a"], "b": e["b"], "edges": [ei], "len": e["len"], "loop": True})
            seen.add(ei)
    return segs


def walk_nodes(G, s):
    """구간의 꼭짓점을 a에서 b 방향으로 차례대로 낸다."""
    out = [s["a"]]
    cur = s["a"]
    for e in s["edges"]:
        E = G.edges[e]
        cur = E["b"] if E["a"] == cur else E["a"]
        out.append(cur)
    return out


def edge_ranges(G, s, want):
    """s의 선 가운데 want에 든 것의 a 기준 거리 범위를 이어 붙여 낸다."""
    out, pos, cur = [], 0.0, s["a"]
    for e in s["edges"]:
        L = G.edges[e]["len"]
        if e in want:
            if out and abs(out[-1][1] - pos) < 1e-6:
                out[-1][1] = pos + L
            else:
                out.append([pos, pos + L])
        pos += L
    return [[round(a, 2), round(b, 2)] for a, b in out]


def shortest(G, src):
    d = [math.inf] * len(G.nodes)
    d[src] = 0.0
    h = [(0.0, src)]
    while h:
        du, u = heapq.heappop(h)
        if du > d[u]:
            continue
        for m, ei in G.adj[u]:
            nd = du + G.edges[ei]["len"]
            if nd < d[m]:
                d[m] = nd
                heapq.heappush(h, (nd, m))
    return d


def read_env():
    env = {}
    p = Path.home() / ".keys" / "barrierfree.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def aerial_b64(path, quality):
    raw = path.read_bytes()
    from PIL import Image

    im = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    if len(buf.getvalue()) < len(raw):
        raw = buf.getvalue()
    return base64.b64encode(raw).decode("ascii"), len(raw)


def make_walk(G, segs, plan, name_list):
    """걷는 순서 한 벌. 출발 마디는 지금 자리에서 가까운 쪽으로 고른다."""
    from_gate = set(plan.get("from_gate", []))
    from_start = shortest(G, G.start)
    out, cur = [], G.start
    for key in name_list:
        for sid in plan[key]:
            s = segs[sid]
            d = shortest(G, cur)
            if sid in from_gate:
                start = s["a"] if from_start[s["a"]] <= from_start[s["b"]] else s["b"]
            else:
                start = s["a"] if d[s["a"]] <= d[s["b"]] else s["b"]
            out.append({"seg": sid, "from": start, "move": round(d[start], 1), "group": key})
            cur = s["b"] if start == s["a"] else s["a"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--test", action="store_true", help="시험용 자료. 경로 계산이 거부한다")
    ap.add_argument("--quality", type=int, default=70)
    a = ap.parse_args()

    D = DATA / a.site
    G = R.load_site(a.site, DATA)
    segs = build_segments(G)
    e2s = {e: i for i, s in enumerate(segs) for e in s["edges"]}
    meta = json.loads((D / "aerial_z19.json").read_text(encoding="utf-8"))
    zoom = meta["zoom"]
    ox, oy = meta["tile_origin_px"]

    def px(lonlat):
        x, y = merc_px(lonlat[0], lonlat[1], zoom)
        return [round(x - ox, 1), round(y - oy, 1)]

    order_path = ROOT / "캡스톤2" / "08_실측규칙" / f"{a.site}_측정순서.json"
    if a.site == "minsokchon":
        order_path = ROOT / "캡스톤2" / "08_실측규칙" / "민속촌_측정순서.json"
    order = json.loads(order_path.read_text(encoding="utf-8")) if order_path.exists() else {"edges": []}
    prio, route, first = {}, {}, {}
    for x in order["edges"]:
        sid = e2s[x["edge"]]
        prio[sid] = min(prio.get(sid, 9), x["priority"])
        if x["priority"] == 3 and x.get("route"):
            route.setdefault(sid, set()).add(str(x["route"]))
        if x["priority"] == 1:
            first.setdefault(sid, set()).add(x["edge"])

    plan_path = OUT / f"{a.site}_walk.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else None

    out_segs = []
    for i, s in enumerate(segs):
        ns = walk_nodes(G, s)
        flat = []
        for n in ns:
            flat.extend(px(G.nodes[n]))
        feats = [G.feats[G.edges[e]["feat"]] for e in s["edges"]]
        inclines = sorted({round(abs(G.edges[e]["incline"]), 1) for e in s["edges"] if G.edges[e]["incline"] is not None})
        out = {
            "seg": i, "a": s["a"], "b": s["b"], "len": round(s["len"], 2), "xy": flat,
            "drawn": round(sum(G.edges[e]["len"] for e in s["edges"] if G.edges[e]["unknown"])),
            "road": any(f.get("highway") in ROADS for f in feats),
            "inclines": inclines,
        }
        if i in prio:
            out["prio"] = prio[i]
        if i in route:
            out["route"] = sorted(route[i])
        if i in first:
            out["fine"] = edge_ranges(G, s, first[i])
        out_segs.append(out)

    if plan:
        for sid, m in plan.get("stop", {}).items():
            s = segs[int(sid)]
            from_start = shortest(G, G.start)
            near = s["a"] if from_start[s["a"]] <= from_start[s["b"]] else s["b"]
            out_segs[int(sid)]["stop"] = {"from": near, "m": m}

    # 구간 끝의 길이 검사로 구별하지 못하는 옆 갈래
    rules = json.loads((HERE / "rules.json").read_text(encoding="utf-8"))
    at_node = {}
    for s in out_segs:
        at_node.setdefault(s["a"], []).append(s["seg"])
        at_node.setdefault(s["b"], []).append(s["seg"])
    for s in out_segs:
        if "prio" not in s:
            continue
        twins = []
        for n in (s["a"], s["b"]):
            for t in at_node[n]:
                if t == s["seg"]:
                    continue
                d = abs(out_segs[t]["len"] - s["len"])
                if d <= rules["check"]["len_m"] or d / s["len"] * 100 <= rules["check"]["len_pct"]:
                    twins.append(t)
        if twins:
            s["twin"] = sorted(set(twins))

    walks = {}
    if plan:
        want = sorted(i for i in prio if prio[i] <= 3)
        listed = sorted(set(sum((plan[k] for k in ("p1", "p2", "r11", "r10", "common")), [])))
        assert want == listed, f"순서 파일과 순위 구간이 다름: {sorted(set(want) ^ set(listed))}"
        walks["11"] = make_walk(G, segs, plan, ["p1", "p2", "r11", "common"])
        walks["10"] = make_walk(G, segs, plan, ["p1", "p2", "r10", "common"])
        walks["gate"] = make_walk(G, segs, plan, ["p1", "p2"])

    nodes = {}
    for s in out_segs:
        for n in (s["a"], s["b"]):
            nodes[str(n)] = px(G.nodes[n])

    b64, nbytes = aerial_b64(D / "aerial_z19.jpg", a.quality)
    net_hash = hashlib.sha256((D / "network.geojson").read_bytes()).hexdigest()[:12]
    env = read_env()
    body = {
        "format": 1, "site": a.site, "name": G.site, "test": bool(a.test),
        "built": datetime.now().astimezone().isoformat(timespec="seconds"),
        "net": net_hash, "rules": rules, "start_node": G.start, "start": px(G.nodes[G.start]),
        "nodes": nodes, "segs": out_segs, "walks": walks,
        "p1_groups": (plan or {}).get("p1_groups", {}),
        "map": {"W": meta["size_px"][0], "H": meta["size_px"][1], "zoom": zoom, "origin": [ox, oy], "mpp": meta.get("m_per_px", 0.25)},
    }
    pack_hash = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    body["hash"] = pack_hash
    if env.get("SUPABASE_URL") and env.get("SUPABASE_PUBLISHABLE_KEY"):
        body["db"] = {"url": env["SUPABASE_URL"], "key": env["SUPABASE_PUBLISHABLE_KEY"]}
    body["aerial"] = b64

    OUT.mkdir(parents=True, exist_ok=True)
    name = f"{a.site}{'_시험' if a.test else ''}_{pack_hash}.json"
    path = OUT / name
    path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    pr = [s for s in out_segs if "prio" in s]
    print(f"{a.site}: 구간 {len(out_segs)}개, 전체 {sum(s['len'] for s in out_segs):,.0f} m, 순위 구간 {len(pr)}개")
    for p in (1, 2, 3, 4):
        ss = [s for s in pr if s["prio"] == p]
        if ss:
            print(f"  {p}순위 {len(ss)}개 {sum(s['len'] for s in ss):.0f} m")
    for k, w in walks.items():
        L = sum(out_segs[x["seg"]]["len"] for x in w)
        M = sum(x["move"] for x in w)
        print(f"  걷는 순서 {k}: {len(w)}구간, 잴 길이 {L:.0f} m, 바퀴 들고 이동 {M:.0f} m")
    print(f"  항공사진 {nbytes // 1024} KB, 파일 {path.stat().st_size / 1e6:.2f} MB, 판 {pack_hash}, 연결망 {net_hash}, 데이터베이스 {'있음' if 'db' in body else '없음'}")
    print(f"  저장: {path}")


main()
