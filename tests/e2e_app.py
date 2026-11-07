"""앱 전체 자동 시험. 실제 Edge(Chromium)로 돌린다.
실행: python -I tests/e2e_app.py [시험이름...]
"""
import functools
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fake_pack  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

DOCS = HERE.parent / "docs"
TMP = Path(tempfile.mkdtemp(prefix="bfapp-"))
PACK = TMP / "fake_pack.json"
FAKE_DB = {"url": "https://fake-project.supabase.co", "key": "sb_publishable_fake"}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve():
    h = functools.partial(Quiet, directory=str(DOCS))
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://localhost:{s.server_address[1]}/"


def kill_profile(dir_name):
    script = TMP / "kill.ps1"
    script.write_text(
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + dir_name + "*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
        encoding="utf-8",
    )
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True)


class App:
    """프로필 하나의 브라우저. 눌러서 쓰는 도우미를 묶었다."""

    def __init__(self, p, url, width=412, height=880, profile=None):
        self.p, self.url = p, url
        self.dir = profile or tempfile.mkdtemp(prefix="bfprofile-", dir=TMP)
        self.size = (width, height)
        self.errors = []
        self.open()

    def open(self):
        self.ctx = self.p.chromium.launch_persistent_context(
            self.dir, channel="msedge", headless=True, viewport={"width": self.size[0], "height": self.size[1]},
            has_touch=True, geolocation={"longitude": 126.84, "latitude": 33.32, "accuracy": 8}, permissions=["geolocation"],
            accept_downloads=True,
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.watch(self.page)
        self.page.goto(self.url)
        self.page.wait_for_selector("#app > *")

    def watch(self, page):
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: self.errors.append(f"console: {m.text}") if m.type == "error" and "ERR_" not in m.text and "Failed to load" not in m.text else None)

    def close(self):
        try:
            self.ctx.close()
        except Exception:
            pass

    def kill(self):
        kill_profile(Path(self.dir).name)
        time.sleep(0.8)
        self.close()

    def t(self, name, timeout=8000):
        return self.page.locator(f'[data-t="{name}"]').first.click(timeout=timeout)

    def opt(self, value):
        self.page.locator(f'[data-opt="{value}"]').first.click(timeout=8000)

    def keys(self, s):
        for ch in s:
            self.page.locator(f'[data-k="{ch}"]').first.click(timeout=8000)

    def num(self, s):
        self.keys(s)
        self.page.locator('[data-k="ok"]').first.click(timeout=8000)

    def sign(self, plus=True):
        self.page.locator(f'[data-sign="{"plus" if plus else "minus"}"]').first.click(timeout=8000)

    def state(self):
        return self.page.evaluate("window.__bf.state()")

    def events(self):
        return self.page.evaluate("window.__bf.events()")

    def text(self):
        return self.page.locator("#app").inner_text()

    def wait_text(self, s, timeout=8000):
        self.page.locator("#app").filter(has_text=s).first.wait_for(timeout=timeout)

    def poll(self, js, timeout=10.0, page=None):
        page = page or self.page
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = page.evaluate(js)
                if last:
                    return last
            except Exception as e:
                last = e
            time.sleep(0.05)
        raise AssertionError(f"기다리다 끝남: {js} (마지막 {last})")

    def wait_state(self, pred, timeout=8.0):
        end = time.time() + timeout
        s = None
        while time.time() < end:
            s = self.state()
            try:
                if pred(s):
                    return s
            except (KeyError, TypeError, IndexError):
                pass
            time.sleep(0.05)
        raise AssertionError(f"상태가 기대와 다름: {json.dumps(s, ensure_ascii=False)[:600]}")

    def wait_saved(self, n):
        self.poll(f"window.__bf.events().length >= {n}")

    # 흐름 도우미 -----------------------------------------------------------
    def load_pack(self):
        self.page.locator('input[data-t="pack-file"]').set_input_files(str(PACK))

    def setup_day(self):
        self.load_pack()
        self.t("login-skip")
        self.opt("sunny")
        self.page.locator('[data-t="text"]').fill("가")
        self.t("next")
        self.page.locator('[data-t="text"]').fill("나")
        self.t("next")
        self.t("form-save")
        self.t("phone-ok")
        self.tool_check()

    def tool_check(self):
        self.sign(True); self.keys("15")
        self.sign(False); self.keys("16")
        self.num("0"); self.num("265"); self.num("0"); self.num("100")
        self.opt("yes")
        self.t("form-save")

    def start_run(self):
        self.t("arrive")
        self.t("start-zero")

    def point(self, long_value, cross=None, plus=True):
        self.sign(plus)
        self.keys(long_value)
        if cross is not None:
            self.keys(cross)

    def fill_point(self, value="11"):
        """지금 지점이 요구하는 칸을 모두 채운다."""
        for _ in range(6):
            d = self.page.evaluate("window.__bf.draft()")
            if d["phase"] == "done":
                return
            if d["phase"] == "long":
                self.sign(True)
            self.keys(value)

    def slope_count(self):
        return self.page.evaluate("window.__bf.events().filter(e => e.kind === 'slope').length")

    def save_point(self):
        n = self.slope_count()
        self.page.locator('[data-k="save"]').first.click(timeout=8000)
        self.poll(f"window.__bf.events().filter(e => e.kind === 'slope').length >= {n + 1}")

    def fill_form(self, memo="메모"):
        """지금 단계 입력을 저장 버튼이 나올 때까지 채운다. 고른 값을 돌려준다."""
        for _ in range(30):
            pg = self.page
            if pg.locator('[data-t="form-save"]').count():
                return
            if pg.locator('[data-t="text"]').count():
                pg.locator('[data-t="text"]').fill(memo)
                self.t("next")
            elif pg.locator('[data-opt]').count():
                pg.locator('[data-opt]:not([data-opt=""]):not([data-opt="__same"])').first.click()
            elif pg.locator('[data-sign]').count():
                self.sign(True)
                self.keys("12")
            elif pg.locator('[data-k="ok"]').count():
                self.num("12")
            else:
                return
            time.sleep(0.03)
        raise AssertionError("단계 입력이 끝나지 않음")

    def first_flow(self, width="180"):
        self.num(width)
        self.opt("block")
        self.opt("good")
        self.opt("")
        self.t("form-save")


# 시험 ----------------------------------------------------------------------
def test_full_flow(p, url):
    a = App(p, url)
    a.setup_day()
    s = a.wait_state(lambda s: s["day"] and len(s["toolChecks"]) >= 5)
    assert s["day"]["measurer"] == "가" and s["day"]["recorder"] == "나", s["day"]
    assert s["levelMode"] is None
    # 걷는 순서의 첫 구간은 1순위 구간 1
    a.wait_text("구간 1")
    a.start_run()
    # 2 m 지점: 좌우를 묻지 않고, 3.2° 이상이어도 앞뒤 5 m를 더하지 않는다
    assert "2.0" in a.page.locator('[data-t="next-mark"]').inner_text()
    a.point("47")  # 4.7은 재측정 범위라 양 끝을 요구한다
    a.wait_text("양 끝")
    a.point("46")
    a.t("photo")
    a.save_point()
    # 구간 첫 지점 뒤에는 폭과 노면을 잇달아 묻는다
    a.first_flow()
    s = a.wait_state(lambda s: s["runs"][s["openRun"]]["surfaces"])
    run = s["runs"][s["openRun"]]
    assert run["points"][0]["method"] == "both"
    assert abs(run["points"][0]["long"] - 4.65) < 1e-9
    assert run["points"][0]["crossValues"] == []
    assert run["barriers"][0]["type"] == "width_rep" and run["barriers"][0]["value"] == 180
    assert run["surfaces"][0]["material"] == "block"
    assert "4.0" in a.page.locator('[data-t="next-mark"]').inner_text()
    # 4 m 지점, 범위 밖 값이면 그대로 저장. 5 m 배수는 양 끝과 좌우를 묻는다
    a.point("12")
    a.save_point()
    assert "5.0" in a.page.locator('[data-t="next-mark"]').inner_text()
    a.wait_text("양 끝")
    a.point("12")
    a.point("13")
    a.keys("11")
    a.t("photo")
    a.save_point()
    s = a.state()
    pt = s["runs"][s["openRun"]]["points"][-1]
    assert pt["method"] == "both" and pt["kind"] == "fine" and pt["cross"] == [1.1]
    # 구간 끝으로 간다. 지점이 남아 있어도 닫을 수 있고 못 잰 항목이 표시된다
    a.page.locator('[data-tool="end"]').click()
    a.num("160")
    a.opt("ok")
    a.t("close-run")
    a.wait_text("3순위")
    s = a.state()
    closed = [r for r in s["runs"].values() if r["closed"]]
    assert len(closed) == 1 and closed[0]["end"] == 16.0 and closed[0]["result"] == "ok"
    assert s["segStatus"]["1"] in ("done", "partial")
    # 1순위 구간이 모두 끝나 3순위 길을 고른다
    assert s["routeChoice"] is None
    a.close()
    return a


def test_route_choice_and_more_marks(p, url):
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.page.locator('[data-tool="end"]').click()
    a.num("160")
    a.opt("ok")
    a.t("close-run")
    # 1순위 뒤 3순위 고르기 화면
    a.wait_text("3순위")
    a.t("route-11")
    a.opt("value")
    a.wait_state(lambda s: s["routeChoice"]["route"] == "11")
    # 구간 0(2순위, 30 m): 15 m에서 3.5°면 더한 지점이 10, 20으로 생긴다
    a.wait_text("구간 0")
    a.start_run()
    assert "5.0" in a.page.locator('[data-t="next-mark"]').inner_text()
    a.point("10", "10")
    a.t("photo")
    a.save_point()
    a.first_flow()
    a.point("35", "10")
    a.save_point()
    txt = a.page.locator('[data-t="next-mark"]').inner_text()
    assert "10.0" in txt, txt
    a.wait_text("더함")
    a.point("11", "10")
    a.save_point()
    # 12 m 넘게 떨어진 곳 저장은 막지 않고 경고한다
    txt = a.page.locator('[data-t="next-mark"]').inner_text()
    assert "20.0" in txt, txt
    a.close()
    return a


def test_kill_keeps_saved(p, url):
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.point("47")
    a.point("46")
    a.save_point()
    a.first_flow()
    saved = []
    for i in range(6):
        a.fill_point()
        before = len(a.events())
        a.page.locator('[data-k="save"]').first.click()
        a.wait_saved(before + 1)
        saved.append(a.events()[-1]["id"])
    n = len(a.events())
    # 저장 표시 직후 프로세스를 죽인다
    a.kill()
    a.open()
    assert len(a.events()) == n, (len(a.events()), n)
    ids = {e["id"] for e in a.events()}
    assert all(i in ids for i in saved)
    a.wait_text("저장됨")
    s = a.state()
    assert s["openRun"], "열린 구간이 복구되어야 함"
    assert a.page.locator('[data-t="next-mark"]').count() == 1
    a.close()
    return a


def test_draft_survives_reload(p, url):
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.sign(True)
    a.keys("4")
    time.sleep(0.5)
    a.page.reload()
    a.page.wait_for_selector('[data-t="f-long"]')
    assert "4" in a.page.locator('[data-t="f-long"]').inner_text()
    a.keys("7")
    a.wait_text("양 끝")
    a.close()
    return a


def test_two_tabs(p, url):
    a = App(p, url)
    a.setup_day()
    a.start_run()
    other = a.ctx.new_page()
    a.watch(other)
    other.goto(url)
    other.wait_for_selector('[data-t="other-tab"]', timeout=8000)
    a.page.wait_for_selector('[data-t="other-tab"]', timeout=8000)
    other.close()
    a.close()
    return a


def test_backup_restore(p, url):
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.point("11")
    a.save_point()
    a.first_flow()
    a.t("more")
    with a.page.expect_download() as dl:
        a.t("backup-file")
    path = TMP / "backup_copy.txt"
    dl.value.save_as(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "bf-backup-1" and data["site"] == "fake"
    n = len(a.events())
    assert data["count"] == n and len(data["events"]) == n
    a.close()
    # 빈 폰: 자료 파일을 넣고 백업을 복원한다
    b = App(p, url)
    b.load_pack()
    b.page.locator('input[data-t="restore-file"]').set_input_files(str(path))
    b.poll(f"window.__bf.events().length === {n}")
    s = b.state()
    assert s["openRun"], "복원 뒤 열린 구간 이어 쓰기"
    b.wait_text("저장됨")
    # 같은 파일을 다시 넣어도 늘지 않는다
    b.t("more")
    b.page.locator('input[data-t="restore-file"]').set_input_files(str(path))
    time.sleep(0.6)
    assert len(b.events()) == n
    b.close()
    # 다른 연결망 백업은 거부한다
    c = App(p, url)
    c.load_pack()
    c.page.wait_for_selector('input[data-t="restore-file"]')
    bad = dict(data)
    bad["net"] = "other"
    wrong = TMP / "wrong.txt"
    wrong.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    c.page.locator('input[data-t="restore-file"]').set_input_files(str(wrong))
    c.wait_text("연결망")
    assert len(c.events()) == 0
    c.errors.clear()
    c.close()
    a.errors += b.errors
    return a


def test_sync(p, url):
    rows = []
    pack_with_db = TMP / "fake_db_pack.json"
    pack_with_db.write_text(json.dumps(fake_pack.build(HERE.parent / "tools" / "rules.json", db=FAKE_DB), ensure_ascii=False), encoding="utf-8")
    a = App(p, url)
    fail = {"on": False}

    def handler(route, request):
        u = request.url
        if "/auth/v1/token" in u:
            body = json.loads(request.post_data)
            if body.get("password") == "wrong":
                return route.fulfill(status=400, json={"msg": "bad"})
            return route.fulfill(status=200, json={"access_token": "tok", "refresh_token": "ref", "expires_in": 3600})
        if "/rest/v1/field_records" in u and request.method == "POST":
            if fail["on"]:
                return route.fulfill(status=503, body="down")
            assert request.headers.get("authorization") == "Bearer tok"
            for r in json.loads(request.post_data):
                if r["id"] not in {x["id"] for x in rows}:
                    rows.append(r)
            return route.fulfill(status=201, body="")
        if "/rest/v1/field_records" in u:
            return route.fulfill(status=200, json=[{"payload": r["payload"]} for r in rows if request.url.find("offset=0") >= 0])
        return route.abort()

    a.ctx.route("https://fake-project.supabase.co/**", handler)
    a.page.locator('input[data-t="pack-file"]').set_input_files(str(pack_with_db))
    a.page.locator('[data-t="email"]').fill("rec1@x.example")
    a.page.locator('[data-t="password"]').fill("wrong")
    a.t("login")
    a.wait_text("맞지 않습니다")
    a.page.locator('[data-t="password"]').fill("right")
    a.t("login")
    a.opt("sunny")
    a.page.locator('[data-t="text"]').fill("가")
    a.t("next")
    a.page.locator('[data-t="text"]').fill("나")
    a.t("next")
    a.t("form-save")
    a.t("phone-ok")
    a.tool_check()
    a.poll("window.__bf.pending() === 0")
    assert len(rows) == len(a.events())
    # 서버가 죽어도 저장은 된다
    fail["on"] = True
    a.start_run()
    a.point("11")
    a.save_point()
    n = len(a.events())
    time.sleep(0.5)
    assert a.page.evaluate("window.__bf.pending()") >= 1
    assert len(rows) < n
    # 서버가 돌아오면 빠짐없이 올라가고 중복이 없다
    fail["on"] = False
    a.page.evaluate("window.__bf.syncNow()")
    a.poll("window.__bf.pending() === 0")
    assert len(rows) == len(a.events())
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r["payload"]["site"] == "fake" for r in rows)
    a.errors = [e for e in a.errors if "503" not in e and "400" not in e]
    # 빈 폰에서 데이터베이스로 복원
    b = App(p, url)
    b.ctx.route("https://fake-project.supabase.co/**", handler)
    b.page.locator('input[data-t="pack-file"]').set_input_files(str(pack_with_db))
    b.page.locator('[data-t="email"]').fill("rec2@x.example")
    b.page.locator('[data-t="password"]').fill("right")
    b.t("login")
    b.t("pull-db")
    b.poll(f"window.__bf.events().length === {len(rows)}")
    assert b.page.evaluate("window.__bf.pending()") == 0
    b.close()
    a.close()
    return a


def test_offline_after_first_load(p, url):
    a = App(p, url)
    a.poll("navigator.serviceWorker.controller !== null")
    a.setup_day()
    a.ctx.set_offline(True)
    a.page.reload()
    a.page.wait_for_selector('[data-t="arrive"]', timeout=8000)
    a.start_run()
    a.point("11")
    a.save_point()
    a.ctx.set_offline(False)
    a.close()
    return a


def test_small_screen(p, url):
    a = App(p, url, width=360, height=640)
    a.setup_day()
    a.start_run()
    fits = a.page.evaluate("""() => {
      const s = document.querySelector('.screen');
      return {scroll: s.scrollHeight, client: s.clientHeight, doc: document.documentElement.scrollHeight, win: innerHeight};
    }""")
    assert fits["scroll"] <= fits["client"] + 1 and fits["doc"] <= fits["win"] + 1, fits
    small = a.page.evaluate("""() => [...document.querySelectorAll('.pad button, .sign button, .tools button')]
      .filter(b => b.getBoundingClientRect().height < 40).length""")
    assert small == 0, small
    a.page.screenshot(path=str(TMP / "measure_360.png"))
    a.close()
    return a


def test_move_map_pick(p, url):
    a = App(p, url)
    a.setup_day()
    a.t("pick")
    a.page.wait_for_selector('[data-t="map"]')
    a.t("list-all")
    a.page.locator('[data-seg="2"]').first.click()
    a.page.locator('[data-from="13"]').first.click()
    a.wait_text("옆 갈래")
    a.t("start-zero")
    s = a.wait_state(lambda s: s["openRun"])
    r = s["runs"][s["openRun"]]
    assert r["seg"] == 2 and r["from"] == 13
    # 구간과 출발 마디를 바꿀 수 있다
    a.t("more")
    a.t("flip-from")
    a.wait_state(lambda s: s["runs"][s["openRun"]]["from"] == 11)
    a.close()
    return a


def test_skip_and_redo(p, url):
    a = App(p, url)
    a.setup_day()
    a.t("skip")
    a.wait_text("구간 0")
    a.wait_state(lambda s: s["skipped"] == [1])
    a.start_run()
    a.point("11", "10")
    a.t("photo")
    a.save_point()
    a.first_flow()
    # 길이가 크게 다르면 경고하고 다시 잴 목록에 넣을 수 있다
    a.page.locator('[data-tool="end"]').click()
    a.num("100")
    a.opt("ok")
    a.wait_text("길이")
    a.t("close-redo")
    s = a.wait_state(lambda s: s["segStatus"]["0"] == "redo")
    assert s["redo"][0]["seg"] == 0
    a.close()
    return a


def test_barrier_forms(p, url):
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.point("11")
    a.save_point()
    a.first_flow()
    # 턱 23 mm: 남은 폭과 사진 2장, 18~22 범위 밖이라 둘째 값 없음
    a.page.locator('[data-tool="bump"]').click()
    a.num("34")
    a.num("23")
    a.opt("up")
    a.opt("square")
    a.num("120")
    a.t("photo")
    a.t("photo")
    a.t("form-save")
    s = a.wait_state(lambda s: len(s["runs"][s["openRun"]]["barriers"]) == 2)
    b = s["runs"][s["openRun"]]["barriers"][-1]
    assert b["type"] == "bump" and b["mark"] == 3.4 and b["value"] == 23 and b["remain_cm"] == 120 and b["shape"] == "square"
    # 턱 20 mm: 둘째 값을 묻고, 턱 15 mm: 남은 폭을 묻지 않는다
    a.page.locator('[data-tool="bump"]').click()
    a.num("41")
    a.num("20")
    a.num("21")
    a.opt("down")
    a.opt("chamfer")
    a.num("100")
    a.num("50")
    a.t("form-save")
    s = a.wait_state(lambda s: len(s["runs"][s["openRun"]]["barriers"]) == 3)
    b = s["runs"][s["openRun"]]["barriers"][-1]
    assert b["value2"] == 21 and b["run_mm"] == 100
    a.page.locator('[data-tool="bump"]').click()
    a.num("42")
    a.num("15")
    a.opt("up")
    a.opt("square")
    a.t("form-save")
    s = a.wait_state(lambda s: len(s["runs"][s["openRun"]]["barriers"]) == 4)
    b = s["runs"][s["openRun"]]["barriers"][-1]
    assert "remain_cm" not in b or b["remain_cm"] is None
    # 못 잰 값은 null이고 0이 아니다
    a.page.locator('[data-tool="gap"]').click()
    a.num("43")
    a.t("blank")
    a.page.locator('[data-t="text"]').fill("캘리퍼 젖음")
    a.t("next")
    a.opt("parallel")
    a.t("blank")
    a.page.locator('[data-t="text"]').fill("가로막힘")
    a.t("next")
    a.t("form-save")
    s = a.wait_state(lambda s: len(s["runs"][s["openRun"]]["barriers"]) == 5)
    b = s["runs"][s["openRun"]]["barriers"][-1]
    assert b["value"] is None and b["remain_cm"] is None and b["reason"] == "캘리퍼 젖음"
    a.close()
    return a


def test_fix_keeps_original(p, url):
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.point("11")
    a.save_point()
    a.first_flow()
    a.t("last")
    a.wait_text("앞뒤")
    # 값 칸을 눌러 다시 넣는다
    a.t("edit-long-0")
    a.sign(False)
    a.keys("13")
    a.t("form-save")
    s = a.wait_state(lambda s: s["runs"][s["openRun"]]["points"][0]["rev"] == 2)
    pt = s["runs"][s["openRun"]]["points"][0]
    assert pt["values"] == [-1.3] and pt["original"]["values"] == [1.1] and pt["rev"] == 2
    kinds = [e["kind"] for e in a.events()]
    assert "fix" in kinds
    a.close()
    return a


def test_double_tap_save(p, url):
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.point("11")
    n = a.slope_count()
    a.page.evaluate("""() => { const b = document.querySelector('[data-k="save"]');
      const e = () => new PointerEvent('pointerdown', {bubbles: true});
      b.dispatchEvent(e()); b.dispatchEvent(e()); }""")
    time.sleep(0.5)
    assert a.slope_count() == n + 1, a.slope_count()
    ids = [e["id"] for e in a.events()]
    assert len(ids) == len(set(ids)), "같은 번호 사건이 두 번 들어감"
    a.close()
    return a


def test_all_forms_round_trip(p, url):
    """칸 정의의 모든 종류가 입력부터 내보내기까지 값이 그대로 남는다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.point("11")
    a.save_point()
    a.first_flow()
    a.t("more")
    names = a.page.evaluate("[...document.querySelectorAll('[data-barrier]')].map(b => b.dataset.barrier)")
    facs = a.page.evaluate("[...document.querySelectorAll('[data-fac]')].map(b => b.dataset.fac)")
    a.t("more-close")
    assert len(names) == 13 and len(facs) == 7, (names, facs)
    for attr, name, kind in [("data-barrier", x, "barrier") for x in names] + [("data-fac", x, "facility") for x in facs]:
        a.t("more")
        a.page.locator(f'[{attr}="{name}"]').click()
        a.fill_form()
        before = len(a.events())
        a.t("form-save")
        a.wait_saved(before + 1)
        a.page.wait_for_selector('[data-t="next-mark"]')
        e = [x for x in a.events() if x["kind"] == kind][-1]
        assert e["data"]["type"] == name, (name, e["data"])
        vals = {k: v for k, v in e["data"].items() if k not in ("type", "photos_required")}
        assert vals, f"{name}: 칸이 비어 있음"
    a.close()
    return a


def test_point_note_and_memo(p, url):
    a = App(p, url)
    a.setup_day()
    a.start_run()
    # 치우기 전 상태와 메모는 지점 저장에 함께 남는다
    a.t("note")
    a.opt("gravel")
    a.page.locator('[data-t="text"]').fill("자갈을 쓸어 냄")
    a.t("next")
    a.t("form-save")
    a.page.wait_for_selector('[data-t="next-mark"]')
    a.point("11")
    a.save_point()
    e = [x for x in a.events() if x["kind"] == "slope"][-1]
    assert e["data"]["clear"] == "gravel" and e["data"]["memo"] == "자갈을 쓸어 냄", e["data"]
    a.first_flow()
    # 구간 메모는 구간 끝에서 고칠 수 있다
    a.page.locator('[data-tool="end"]').click()
    a.num("160")
    a.opt("ok")
    a.t("edit-memo")
    a.page.locator('[data-t="text"]').fill("옆 갈래와 평행")
    a.t("next")
    a.t("close-run")
    s = a.wait_state(lambda s: any(r["closed"] for r in s["runs"].values()))
    assert [r for r in s["runs"].values() if r["closed"]][0]["memo"] == "옆 갈래와 평행"
    a.close()
    return a


def test_boundary_note(p, url):
    a = App(p, url)
    a.setup_day()
    a.t("pick")
    a.t("list-all")
    a.page.locator('[data-seg="0"]').first.click()
    a.page.locator('[data-from="10"]').first.click()
    a.t("start-zero")
    a.t("rough")
    a.point("40"); a.point("50"); a.point("45")
    a.keys("10")
    a.wait_text("경계")
    a.opt("whole")
    a.save_point()
    e = [x for x in a.events() if x["kind"] == "slope"][-1]
    assert e["data"]["note"] == "whole" and e["data"]["method"] == "three" and e["data"]["flags"] == ["boundary"], e["data"]
    a.close()
    return a


def test_two_lines(p, url):
    a = App(p, url)
    a.setup_day()
    a.t("arrive")
    a.page.locator('[data-line="gentle"]').click()
    a.t("start-zero")
    a.page.locator('[data-tool="end"]').click()
    a.num("160")
    a.opt("ok")
    a.t("close-run")
    # 1순위에서 줄을 골랐으면 다른 줄을 이어서 잰다
    a.wait_text("다른 줄")
    a.t("start-zero")
    s = a.wait_state(lambda s: s["openRun"])
    r = s["runs"][s["openRun"]]
    assert r["line"] == "walk" and r["retry"] == "line" and r["from"] == 12, r
    a.close()
    return a


def main():
    PACK.write_text(json.dumps(fake_pack.build(HERE.parent / "tools" / "rules.json"), ensure_ascii=False), encoding="utf-8")
    server, url = serve()
    names = sys.argv[1:] or [k[5:] for k in globals() if k.startswith("test_")]
    bad = 0
    with sync_playwright() as p:
        for name in names:
            t0 = time.time()
            try:
                a = globals()["test_" + name](p, url)
                errs = a.errors if a else []
                if errs:
                    raise AssertionError("콘솔 오류: " + " | ".join(errs[:5]))
                print(f"통과  {name} ({time.time() - t0:.1f}s)")
            except Exception as e:
                bad += 1
                print(f"실패  {name}: {type(e).__name__}: {str(e)[:500]}")
                tb = traceback.extract_tb(e.__traceback__)
                print("      ", [f"{f.name}:{f.lineno}" for f in tb if "e2e_app" in f.filename][-3:])
    server.shutdown()
    print("시험 파일:", TMP)
    print("실패", bad)
    if not bad:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if bad else 0)


main()
