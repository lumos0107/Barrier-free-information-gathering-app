"""시험용 가짜 자료 파일. 좌표는 지도 픽셀이고 실제 장소와 상관없다."""
import base64
import hashlib
import io
import json
from pathlib import Path


def aerial_b64():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (800, 800), "#cfd4d8").save(buf, "JPEG", quality=60)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def seg(i, a, b, length, xy, **kw):
    return {"seg": i, "a": a, "b": b, "len": length, "xy": xy, "drawn": 0, "road": False, "inclines": [], **kw}


def build(rules_path, db=None):
    rules = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    segs = [
        seg(0, 10, 11, 30.0, [100, 100, 220, 100], prio=2, road=False),
        seg(1, 11, 12, 16.0, [220, 100, 284, 100], prio=1, fine=[[0, 16]]),
        seg(2, 11, 13, 16.5, [220, 100, 220, 166], prio=2, twin=[1]),
        seg(3, 13, 14, 2.5, [220, 166, 230, 166], prio=2),
        seg(4, 13, 15, 60.0, [220, 166, 220, 406], prio=3, route=["11"], stop={"from": 13, "m": 9.5}),
        seg(5, 13, 16, 40.0, [220, 166, 60, 166], prio=3, route=["10"]),
        seg(6, 14, 17, 20.0, [230, 166, 310, 166]),
    ]
    nodes = {str(s[k]): None for s in segs for k in ("a", "b")}
    for s in segs:
        nodes[str(s["a"])] = s["xy"][:2]
        nodes[str(s["b"])] = s["xy"][-2:]
    w = lambda *rows: [{"seg": s, "from": f, "move": m, "group": g} for s, f, m, g in rows]
    walks = {
        "11": w((1, 11, 30.0, "p1"), (0, 10, 46.0, "p2"), (2, 11, 0.0, "p2"), (3, 13, 0.0, "p2"), (4, 13, 2.5, "r11")),
        "10": w((1, 11, 30.0, "p1"), (0, 10, 46.0, "p2"), (2, 11, 0.0, "p2"), (3, 13, 0.0, "p2"), (5, 13, 2.5, "r10")),
        "gate": w((1, 11, 30.0, "p1"), (0, 10, 46.0, "p2"), (2, 11, 0.0, "p2"), (3, 13, 0.0, "p2")),
    }
    body = {
        "format": 1, "site": "fake", "name": "가짜 대상지", "test": True, "built": "2026-11-07T00:00:00+09:00",
        "net": "fakenet00000", "rules": rules, "start_node": 10, "start": [100, 100], "nodes": nodes, "segs": segs, "walks": walks,
        "p1_groups": {"11": [1], "10": [1]},
        "map": {"W": 800, "H": 800, "zoom": 19, "origin": [114397440, 53917952], "mpp": 0.25},
    }
    body["hash"] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    if db:
        body["db"] = db
    body["aerial"] = aerial_b64()
    return body
