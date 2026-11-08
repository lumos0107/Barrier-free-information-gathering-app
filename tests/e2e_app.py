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

    # 누르기는 실제 터치로 한다. 마우스 클릭으로는 손가락에서만 생기는 유령 누름을 못 잡는다.
    def tap(self, sel, timeout=8000):
        self.page.locator(sel).first.tap(timeout=timeout)

    def t(self, name, timeout=8000):
        return self.tap(f'[data-t="{name}"]', timeout)

    def opt(self, value):
        self.tap(f'[data-opt="{value}"]')

    def keys(self, s):
        for ch in s:
            self.tap(f'[data-k="{ch}"]')

    def num(self, s):
        self.keys(s)
        self.tap('[data-k="ok"]')

    def sign(self, plus=True):
        self.tap(f'[data-sign="{"plus" if plus else "minus"}"]')

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

    def see(self, sel, timeout=8000):
        try:
            self.page.locator(sel).first.wait_for(timeout=timeout)
        except Exception:
            raise AssertionError(f"{sel} 없음. 화면: {self.text()[:300]}")

    def wait_saved(self, n):
        self.poll(f"window.__bf.events().length >= {n}")

    # 흐름 도우미 -----------------------------------------------------------
    def load_pack(self, path=None):
        self.see('input[data-t="pack-file"]', timeout=15000)
        self.page.locator('input[data-t="pack-file"]').first.set_input_files(str(path or PACK))

    def setup_day(self, pack=None):
        self.load_pack(pack)
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
    a.opt("checked")
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
    a.opt("checked")
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
    a.see('[data-t="arrive"]')
    a.ctx.set_offline(True)
    a.page.reload()
    a.see('[data-t="arrive"]')
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
    a.t("records")
    a.tap(f'[data-run="{s["openRun"]}"]')
    a.t("edit-from")
    a.opt("11")
    a.t("form-save")
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
    a.opt("checked")
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
    a.page.evaluate("""() => { const b = document.querySelector('[data-k="save"]'); b.click(); b.click(); }""")
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
    a.opt("checked")
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
    a.opt("checked")
    a.t("close-run")
    # 1순위에서 줄을 골랐으면 다른 줄을 이어서 잰다
    a.wait_text("다른 줄")
    a.t("start-zero")
    s = a.wait_state(lambda s: s["openRun"])
    r = s["runs"][s["openRun"]]
    assert r["line"] == "walk" and r["retry"] == "line" and r["from"] == 12, r
    a.close()
    return a


# 1단계 고침 시험 -------------------------------------------------------------
def test_touch_end_asks_result(p, url):
    """끝값 뒤 '다음'을 손가락으로 눌러도 구간 확인을 묻는다(유령 누름 없음)."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.tap('[data-tool="end"]')
    a.num("300")
    time.sleep(0.3)
    assert a.page.locator('[data-opt="ok"]').count() == 1, "구간 확인을 묻지 않음: " + a.text()[:200]
    assert a.page.locator('[data-t="edit-result"]').count() == 0, "구간 확인이 저절로 들어감"
    a.close()
    return a


def test_touch_bump_asks_dir(p, url):
    """턱 높이 뒤 '다음'을 손가락으로 눌러도 방향을 묻는다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.tap('[data-tool="bump"]')
    a.num("50")
    a.num("25")
    time.sleep(0.3)
    assert a.page.locator('[data-opt="up"]').count() == 1 and a.page.locator('[data-opt="down"]').count() == 1, "방향을 묻지 않음: " + a.text()[:200]
    a.close()
    return a


def test_draft_not_overwritten_after_crash(p, url):
    """저장 직후 앱이 죽어 옛 초안이 복구돼도 저장한 값을 덮어쓰지 않는다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.point("11")
    time.sleep(0.4)
    # 저장 뒤 화면 상태 쓰기가 디스크에 닿지 못한 것을 흉내 낸다: 'ui' 쓰기를 버린다
    a.page.evaluate("""() => { const o = IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put = function (v, k) { if (k === 'ui') return o.call(this, v, 'ui_dropped'); return o.apply(this, arguments); }; }""")
    a.save_point()
    first = [e for e in a.events() if e["kind"] == "slope"][0]
    a.page.reload()
    a.page.wait_for_selector("#app > *")
    a.page.locator('[data-k="save"]').first.wait_for(timeout=8000)
    d = a.page.evaluate("window.__bf.draft()")
    assert d["id"] != first["id"], "저장한 번호의 초안이 그대로 복구됨"
    a.fill_point("22")
    a.save_point()
    a.page.reload()
    a.page.wait_for_selector("#app > *")
    slopes = [e for e in a.events() if e["kind"] == "slope"]
    assert len(slopes) == 2, len(slopes)
    kept = [e for e in slopes if e["id"] == first["id"]][0]
    assert kept["data"]["values"] == first["data"]["values"], kept["data"]
    a.close()
    return a


def test_same_id_write_refused(p, url):
    """같은 번호의 사건은 저장소가 받지 않는다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.point("11")
    a.save_point()
    ev = [e for e in a.events() if e["kind"] == "slope"][0]
    r = a.page.evaluate("""async (id) => { const m = await import('./js/store.js'); await m.openStore();
      try { await m.addEvent((seq) => ({ id, seq, kind: 'slope', at: new Date().toISOString(), data: { values: [9.9] } })); return 'ok'; }
      catch (e) { return e.name || String(e); } }""", ev["id"])
    assert r != "ok", r
    a.close()
    return a


def test_triple_start_one_run(p, url):
    """시작을 빠르게 3번 눌러도 구간 측정은 하나다."""
    a = App(p, url)
    a.setup_day()
    a.t("arrive")
    a.page.evaluate("""() => { const b = document.querySelector('[data-t="start-zero"]'); b.click(); b.click(); b.click(); }""")
    time.sleep(0.5)
    n = sum(1 for e in a.events() if e["kind"] == "run_start")
    assert n == 1, n
    a.close()
    return a


def test_clock_back_keeps_order(p, url):
    """재는 중에 폰 시계가 5분 뒤로 가도 지점이 구간에 붙고 구간이 닫힌다."""
    from datetime import datetime, timedelta
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.wait_state(lambda s: s["openRun"])
    time.sleep(0.2)
    a.page.clock.set_fixed_time(datetime.now() - timedelta(minutes=5))
    a.point("11")
    a.save_point()
    evs = a.events()
    start = [e for e in evs if e["kind"] == "run_start"][0]
    slope = [e for e in evs if e["kind"] == "slope"][0]
    assert slope["at"] < start["at"], "시계가 뒤로 가지 않음"
    a.first_flow()
    a.tap('[data-tool="end"]')
    a.num("160")
    a.opt("ok")
    a.fill_form()
    a.t("close-run")
    s = a.wait_state(lambda s: not s["openRun"] and len(s["runOrder"]) == 1)
    run = s["runs"][s["runOrder"][0]]
    assert run["closed"] and len(run["points"]) == 1 and not s["loose"], (run["closed"], len(run["points"]), s["loose"])
    a.close()
    return a


# 2단계 고침 시험 -------------------------------------------------------------
def to_seg0(a):
    """1순위 구간 1을 건너뛰고 30 m 구간 0을 시작한다. 예정 지점은 5, 15, 25."""
    a.t("skip")
    a.page.locator('[data-t="arrive"]').first.wait_for(timeout=8000)
    a.start_run()
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)


def no_long_point(a):
    """앞뒤를 '못 잼'으로 두고 좌우만 잰다."""
    a.t("skip-slot")
    a.keys("10")
    a.save_point()


def end_ok(a, end="300"):
    a.tap('[data-tool="end"]')
    a.num(end)
    a.opt("ok")
    a.fill_form()


def test_unread_counts_missing(p, url):
    """앞뒤를 모두 못 잼, 대표 폭도 못 잼으로 닫으면 못 잰 항목에 들어가고 구간이 '일부'다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    no_long_point(a)
    a.t("blank")  # 대표 폭 못 잼
    a.opt("block"); a.opt("good"); a.opt(""); a.t("form-save")
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    no_long_point(a)
    no_long_point(a)
    end_ok(a)
    a.t("close-run")
    s = a.wait_state(lambda s: not s["openRun"] and s["runOrder"])
    run = s["runs"][s["runOrder"][0]]
    assert "slope" in run["missing"] and "width" in run["missing"], run["missing"]
    assert s["segStatus"]["0"] == "partial", s["segStatus"]
    a.close()
    return a


def test_break_then_facility_position(p, url):
    """끊김 뒤 시설의 자동 표시값은 끊김 뒤 값이고, 기록에 그때의 끊김 수가 남는다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.t("more")
    a.t("break")
    a.num("200")
    a.num("0")
    a.t("form-save")
    a.tap('[data-fac="bench"]')
    a.opt("no")
    a.t("form-save")
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    f = [e for e in a.events() if e["kind"] == "facility"][0]
    assert f["data"]["mark"] == 0 and f["data"]["breakCount"] == 1, f["data"]
    a.close()
    return a


def test_first_surface_from_start(p, url):
    """구간의 첫 노면은 구간 시작부터다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.poll("window.__bf.events().some(e => e.kind === 'surface')")
    sf = [e for e in a.events() if e["kind"] == "surface"][0]
    assert sf["data"]["mark"] == 0, sf["data"]
    a.close()
    return a


def test_add_here_point(p, url):
    """'여기 더 재기'로 넣은 지점은 더한 지점으로 남고 예정 지점은 그대로다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.t("add-here")
    a.num("80")
    a.fill_point("12")
    a.save_point()
    e = [e for e in a.events() if e["kind"] == "slope"][-1]
    assert e["data"]["kind"] == "more" and e["data"]["added"] and e["data"]["mark"] == 8.0, e["data"]
    d = a.page.evaluate("window.__bf.draft()")
    assert d["mark"] == 15 and d["kind"] == "gap", (d["mark"], d["kind"])
    a.close()
    return a


def test_planned_mark_not_lost(p, url):
    """1순위 구간에서 4를 4.4로 재도 5 m 지점이 다음 차례로 남는다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    a.tap('[data-adj="0.2"]')
    a.tap('[data-adj="0.2"]')
    a.fill_point("11")
    a.save_point()
    d = a.page.evaluate("window.__bf.draft()")
    assert d["mark"] == 5 and d["both"], (d["mark"], d["both"])
    a.close()
    return a


def test_edit_clears_hidden(p, url):
    """턱 20 mm(둘째 값 19)를 10 mm로 고치면 숨은 칸이 남지 않는다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.tap('[data-tool="bump"]')
    a.num("30")
    a.num("20")
    a.num("19")
    a.opt("up")
    a.opt("square")
    a.num("12")
    a.t("form-save")
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    bid = [e for e in a.events() if e["kind"] == "barrier"][0]["id"]
    a.t("more")
    a.t("records")
    a.tap(f'[data-rec="{bid}"]')
    a.t("edit-value")
    a.num("10")
    a.t("form-save")
    s = a.wait_state(lambda s: s["runs"][s["runOrder"][0]]["barriers"][0]["value"] == 10)
    b = s["runs"][s["runOrder"][0]]["barriers"][0]
    assert "value2" not in b and "remain_cm" not in b, b
    a.close()
    return a


def test_void_needs_two_taps(p, url):
    """지점 지우기는 두 번 눌러야 지워진다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.t("last")
    a.t("void-record")
    time.sleep(0.2)
    assert not any(e["kind"] == "void" for e in a.events()), "한 번에 지워짐"
    a.t("void-record")
    a.wait_state(lambda s: len(s["runs"][s["runOrder"][0]]["points"]) == 0)
    a.close()
    return a


def test_run_header_fix(p, url):
    """닫은 구간의 끝값을 기록 목록에서 고칠 수 있다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    end_ok(a, "513")
    a.t("close-run")
    s = a.wait_state(lambda s: not s["openRun"] and s["runOrder"])
    rid = s["runOrder"][0]
    a.t("more")
    a.t("records")
    a.tap(f'[data-run="{rid}"]')
    a.t("edit-end")
    a.num("153")
    a.t("form-save")
    a.wait_state(lambda s: s["runs"][rid]["end"] == 15.3)
    a.close()
    return a


def test_photo_count_by_record(p, url):
    """구간 끝의 사진 셈에 시설 사진이 섞이지 않는다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.t("more")
    a.tap('[data-fac="ramp"]')
    a.fill_form()
    a.t("photo")
    a.t("photo")
    a.t("form-save")
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    end_ok(a)
    tx = a.text()
    assert "찍음 0장" in tx, tx[:400]
    a.close()
    return a


def test_keypad_stays_put(p, url):
    """띠가 떠도 숫자 키 자리가 그대로다."""
    a = App(p, url, width=384, height=780)
    a.setup_day()
    to_seg0(a)
    before = a.page.locator('[data-k="5"]').bounding_box()
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    after = a.page.locator('[data-k="5"]').bounding_box()
    assert abs(before["y"] - after["y"]) < 1, (before, after)
    save = a.page.locator('[data-k="save"]').bounding_box()
    assert save["y"] + save["height"] <= 780, save
    a.close()
    return a


# 3단계 고침 시험 -------------------------------------------------------------
def custom_pack(name, change):
    body = fake_pack.build(HERE.parent / "tools" / "rules.json")
    change(body)
    path = TMP / name
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


def day_form(a):
    a.opt("sunny")
    a.page.locator('[data-t="text"]').fill("가")
    a.t("next")
    a.page.locator('[data-t="text"]').fill("나")
    a.t("next")
    a.t("form-save")


def close_seg(a, end="160"):
    a.tap('[data-tool="end"]')
    a.num(end)
    a.opt("ok")
    a.fill_form()
    a.t("close-run")


def test_gps_waits_for_tap(p, url):
    """위치는 '위치 켜기'를 누를 때 처음 묻는다. 권한 창이 막히지 않게 한다."""
    d = tempfile.mkdtemp(prefix="bfprofile-", dir=TMP)
    ctx = p.chromium.launch_persistent_context(d, channel="msedge", headless=True, viewport={"width": 412, "height": 880}, has_touch=True)
    ctx.add_init_script("""window.__geoCalls = 0; const g = navigator.geolocation;
      const w = g.watchPosition.bind(g); g.watchPosition = (...a) => { window.__geoCalls += 1; return w(...a); };""")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(url)
    page.wait_for_selector("#app > *")
    page.locator('input[data-t="pack-file"]').set_input_files(str(PACK))
    page.locator('[data-t="login-skip"]').tap()
    page.locator('[data-opt="sunny"]').tap()
    page.locator('[data-t="text"]').fill("가")
    page.locator('[data-t="next"]').tap()
    page.locator('[data-t="text"]').fill("나")
    page.locator('[data-t="next"]').tap()
    page.locator('[data-t="form-save"]').tap()
    page.locator('[data-t="gps-on"]').wait_for(timeout=8000)
    assert page.evaluate("window.__geoCalls") == 0, "누르기 전에 위치를 물음"
    page.locator('[data-t="gps-on"]').tap()
    time.sleep(0.3)
    assert page.evaluate("window.__geoCalls") == 1
    ctx.close()
    return None


def test_switch_pack_keeps_records(p, url):
    """다른 대상지 자료를 넣으면 앞 대상지 기록은 그대로 남고, 다시 넣으면 이어진다."""
    other = custom_pack("other_site.json", lambda b: b.update(site="fake2", name="둘째 대상지", net="othernet0000"))
    a = App(p, url)
    a.setup_day()
    a.see('[data-t="arrive"]')
    n = len(a.events())
    assert n > 0
    a.t("more")
    a.page.locator('input[data-t="pack-file"]').set_input_files(str(other))
    a.page.locator('[data-t="login-skip"]').wait_for(timeout=8000)
    assert len(a.events()) == 0, "새 대상지에 앞 기록이 섞임"
    a.t("login-skip")
    day_form(a)
    a.t("phone-ok")
    a.tool_check()
    a.t("more")
    a.page.locator('input[data-t="pack-file"]').set_input_files(str(PACK))
    a.page.locator('[data-t="login-skip"]').wait_for(timeout=8000)
    assert len(a.events()) == n, (len(a.events()), n)
    a.close()
    return a


def test_token_refused_shows_login(p, url):
    """토큰 갱신이 거절되면 세션을 지우고 다시 로그인할 수 있다."""
    pk = TMP / "fake_db_pack2.json"
    pk.write_text(json.dumps(fake_pack.build(HERE.parent / "tools" / "rules.json", db=FAKE_DB), ensure_ascii=False), encoding="utf-8")
    a = App(p, url)

    def handler(route, request):
        u = request.url
        if "grant_type=password" in u:
            return route.fulfill(status=200, json={"access_token": "a", "refresh_token": "r", "expires_in": -10})
        if "grant_type=refresh_token" in u:
            return route.fulfill(status=400, json={"error": "invalid_grant"})
        return route.fulfill(status=401, body="{}")

    a.ctx.route("https://fake-project.supabase.co/**", handler)
    a.load_pack(pk)
    a.page.locator('[data-t="email"]').fill("x@test.invalid")
    a.page.locator('[data-t="password"]').fill("y")
    a.t("login")
    day_form(a)
    a.t("phone-ok")
    a.tool_check()
    a.t("more")
    if a.page.locator('[data-t="sync-now"]').count():
        a.t("sync-now")
    a.page.locator('[data-t="go-login"]').wait_for(timeout=8000)
    a.errors = [e for e in a.errors if "400" not in e and "401" not in e]
    a.close()
    return a


def test_spare_phone_restore_from_day(p, url):
    """자료를 넣어 둔 예비 폰은 오늘 준비 화면에서 백업을 복원한다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.t("more")
    with a.page.expect_download() as dl:
        a.t("backup-file")
    path = TMP / "spare.txt"
    dl.value.save_as(path)
    n = len(a.events())
    a.close()
    b = App(p, url)
    b.load_pack()
    b.t("login-skip")
    b.page.locator('input[data-t="restore-file"]').set_input_files(str(path))
    b.poll(f"window.__bf.events().length === {n}")
    b.see('[data-t="next-mark"]')
    b.close()
    a.errors += b.errors
    return a


def test_reload_on_phone_setup(p, url):
    """폰 설정 화면에서 앱이 다시 열려도 아침 점검으로 돌아온다."""
    a = App(p, url)
    a.load_pack()
    a.t("login-skip")
    day_form(a)
    a.see('[data-t="phone-ok"]')
    a.page.reload()
    a.page.wait_for_selector("#app > *")
    a.see('[data-t="phone-ok"]')
    a.t("phone-ok")
    a.see('[data-sign="plus"]')
    a.page.reload()
    a.page.wait_for_selector("#app > *")
    a.see('[data-sign="plus"]')
    a.tool_check()
    a.see('[data-t="arrive"]')
    a.close()
    return a


def test_redo_close_moves_on(p, url):
    """다시 잴 목록에 넣고 닫으면 다음 구간으로 간다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.tap('[data-tool="end"]')
    a.num("400")
    a.opt("ok")
    a.fill_form()
    a.t("close-redo")
    a.wait_state(lambda s: s["segStatus"]["1"] == "redo")
    a.wait_text("다음 일: 구간 0")
    a.close()
    return a


def test_skip_p1_asks_route(p, url):
    """1순위를 건너뛰고 2순위를 다 하면 3순위 길을 묻는다. 고르기 전에는 3순위로 가지 않는다."""
    a = App(p, url)
    a.setup_day()
    for seg in ("1", "0", "2", "3"):
        a.wait_text(f"다음 일: 구간 {seg}")
        a.t("skip")
    a.wait_text("3순위 길 고르기")
    a.t("route-10")
    a.opt("site")
    a.wait_text("다음 일: 구간 5")
    a.t("more")
    a.t("route-again")
    a.wait_text("3순위 길 고르기")
    a.close()
    return a


def test_new_path_moves_run(p, url):
    """재는 중에 '새 길'을 누르면 지금 구간을 어떻게 할지 묻고, 잰 지점을 새 길로 옮길 수 있다."""
    a = App(p, url)
    a.setup_day()
    a.t("skip")
    a.start_run()
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.t("more")
    a.t("new-path-more")
    a.t("np-move")
    box = a.page.locator('[data-t="map"]').bounding_box()
    a.page.touchscreen.tap(box["x"] + 60, box["y"] + 60)
    time.sleep(0.2)
    a.page.touchscreen.tap(box["x"] + 160, box["y"] + 90)
    time.sleep(0.2)
    a.t("draw-done")
    s = a.wait_state(lambda s: s["openRun"] and isinstance(s["runs"][s["openRun"]]["seg"], str))
    run = s["runs"][s["openRun"]]
    assert len(run["points"]) == 1, len(run["points"])
    assert "-" in run["seg"], run["seg"]
    old = [s["runs"][x] for x in s["runOrder"] if x != s["openRun"]]
    assert len(old) == 1 and old[0]["seg"] == 0 and old[0]["result"] == "not_path" and not old[0]["points"], old
    a.close()
    return a


def test_boot_failure_screen(p, url):
    """시작 중 오류가 나면 '불러오는 중'에 멈추지 않고 이유와 다시 열기가 보인다."""
    a = App(p, url)
    a.setup_day()
    a.ctx.add_init_script("IDBObjectStore.prototype.getAll = function () { throw new Error('시험용 읽기 실패'); };")
    a.page.reload()
    a.page.locator('[data-t="boot-fail"]').wait_for(timeout=8000)
    assert "시험용 읽기 실패" in a.text()
    a.errors.clear()
    a.close()
    return a


def test_twin_question(p, url):
    """순서에 없는 옆 선이 붙은 구간을 닫을 때 옆 선이 실제 길인지 묻는다."""
    pk = custom_pack("twin.json", lambda b: b["segs"][0].update(twin=[6]))
    a = App(p, url)
    a.setup_day(pk)
    a.t("skip")
    a.start_run()
    a.tap('[data-tool="end"]')
    a.num("300")
    a.opt("ok")
    a.opt("checked")
    a.wait_text("옆 선 구간 6")
    a.opt("no")
    a.fill_form()
    a.t("close-run")
    a.poll("window.__bf.events().some(e => e.kind === 'run_end')")
    end = [e for e in a.events() if e["kind"] == "run_end"][0]
    assert end["data"]["twin"] == {"seg": 6, "result": "no"}, end["data"]
    a.close()
    return a


def test_new_day_restarts_prep(p, url):
    """날짜가 바뀌면 오늘 준비부터 다시 한다."""
    from datetime import datetime, timedelta
    a = App(p, url)
    a.setup_day()
    a.page.locator('[data-t="arrive"]').wait_for(timeout=8000)
    a.page.clock.set_fixed_time(datetime.now() + timedelta(days=1))
    a.page.reload()
    a.page.wait_for_selector("#app > *")
    a.see('[data-opt="sunny"]')
    a.close()
    return a


def test_end_asks_no_barrier(p, url):
    """장벽을 하나도 안 적은 구간은 닫을 때 '장벽 없음 확인'을 남긴다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.tap('[data-tool="end"]')
    a.num("160")
    a.opt("ok")
    a.opt("checked")
    a.t("close-run")
    a.poll("window.__bf.events().some(e => e.kind === 'run_end')")
    end = [e for e in a.events() if e["kind"] == "run_end"][0]
    assert end["data"]["no_barrier"] == "checked", end["data"]
    a.close()
    return a


def test_restore_rejects_mixed(p, url):
    """백업 안에 다른 연결망이나 시험 표시가 다른 사건이 있으면 그 사건은 넣지 않는다."""
    a = App(p, url)
    a.setup_day()
    evs = a.events()
    bad = dict(evs[-1])
    bad["id"] = "bad-net-1"
    bad["net"] = "other"
    data = {"format": "bf-backup-1", "site": "fake", "net": "fakenet00000", "events": evs + [bad]}
    path = TMP / "mixed.txt"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    a.t("more")
    a.page.locator('input[data-t="restore-file"]').set_input_files(str(path))
    a.wait_text("넣지 않음")
    assert not any(e["id"] == "bad-net-1" for e in a.events())
    a.close()
    return a


def test_merge_keeps_my_open_run(p, url):
    """다른 폰 기록을 합쳐도 이 폰에서 재던 구간이 열린 구간으로 남는다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.page.locator('[data-t="next-mark"]').first.wait_for(timeout=8000)
    mine = a.state()["openRun"]
    evs = a.events()
    t = evs[-1]["at"]
    other = {**evs[-1], "id": "other-run", "dev": "otherdev", "seq": 1, "kind": "run_start", "ord": evs[-1].get("ord", 0) + 5, "at": t,
             "data": {"seg": 0, "from": 10, "start": 0}}
    data = {"format": "bf-backup-1", "site": "fake", "net": "fakenet00000", "events": [other]}
    path = TMP / "merge.txt"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    a.t("more")
    a.page.locator('input[data-t="restore-file"]').set_input_files(str(path))
    s = a.wait_state(lambda s: "other-run" in s["runs"])
    assert s["openRun"] == mine, (s["openRun"], mine)
    a.close()
    return a


# 13번 나머지 -----------------------------------------------------------------
def test_closed_run_change_seg_and_from(p, url):
    """닫은 구간의 출발 마디와 구간 번호를 기록 목록에서 고칠 수 있다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    end_ok(a)
    a.t("close-run")
    s = a.wait_state(lambda s: not s["openRun"] and s["runOrder"])
    rid = s["runOrder"][0]
    a.t("more")
    a.t("records")
    a.tap(f'[data-run="{rid}"]')
    a.t("edit-from")
    a.opt("11")
    a.t("form-save")
    a.wait_state(lambda s: s["runs"][rid]["from"] == 11)
    a.tap(f'[data-run="{rid}"]')
    a.t("run-change-seg")
    a.t("list-all")
    a.tap('[data-seg="2"]')
    a.tap('[data-from="13"]')
    s = a.wait_state(lambda s: s["runs"][rid]["seg"] == 2)
    assert s["runs"][rid]["from"] == 13 and s["runs"][rid]["closed"], s["runs"][rid]["from"]
    assert "0" not in s["segStatus"] and s["segStatus"]["2"] in ("done", "partial"), s["segStatus"]
    a.see(f'[data-run="{rid}"]')
    a.close()
    return a


def test_void_break(p, url):
    """잘못 넣은 끊김은 두 번 눌러 지운다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.t("more")
    a.t("break")
    a.num("200")
    a.num("0")
    a.t("form-save")
    a.poll("window.__bf.events().some(e => e.kind === 'break')")
    kid = [e for e in a.events() if e["kind"] == "break"][0]["id"]
    a.t("records")
    a.tap(f'[data-rec="{kid}"]')
    a.t("void-record")
    time.sleep(0.2)
    assert not any(e["kind"] == "void" for e in a.events()), "한 번에 지워짐"
    a.t("void-record")
    a.wait_state(lambda s: s["openRun"] and len(s["runs"][s["openRun"]]["breaks"]) == 0)
    a.close()
    return a


# 2라운드 필수 -----------------------------------------------------------------
DROP_UI = """() => { const o = IDBObjectStore.prototype.put;
  IDBObjectStore.prototype.put = function (v, k) { if (k === 'ui') return o.call(this, v, 'ui_dropped'); return o.apply(this, arguments); }; }"""


def reopen(a):
    a.page.reload()
    a.page.wait_for_selector("#app > *")
    time.sleep(0.5)


def test_short_seg_counts_slope_missing(p, url):
    """3 m 미만 구간을 안 재고 닫으면 경사가 못 잰 항목이다."""
    a = App(p, url)
    a.setup_day()
    for seg in ("1", "0", "2"):
        a.wait_text(f"다음 일: 구간 {seg}")
        a.t("skip")
    a.wait_text("다음 일: 구간 3")
    a.start_run()
    a.opt("block"); a.opt("good"); a.opt(""); a.t("form-save")
    a.see('[data-t="next-mark"]')
    a.tap('[data-tool="end"]')
    a.num("25")
    a.opt("ok")
    a.fill_form()
    a.t("close-run")
    s = a.wait_state(lambda s: not s["openRun"] and s["runOrder"])
    assert s["runs"][s["runOrder"][0]]["missing"] == ["slope"] and s["segStatus"]["3"] == "partial", s["segStatus"]
    a.close()
    return a


def test_status_after_closed_fix(p, url):
    """끝까지 못 감을 길 맞음으로 고치면 안 잰 지점이 못 잰 항목으로 잡힌다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.tap('[data-tool="end"]')
    a.num("120")
    a.opt("stopped")
    a.fill_form()
    a.t("close-run")
    s = a.wait_state(lambda s: not s["openRun"] and s["runOrder"])
    rid = s["runOrder"][0]
    a.t("more")
    a.t("records")
    a.tap(f'[data-run="{rid}"]')
    a.t("edit-result")
    a.opt("ok")
    a.t("edit-end")
    a.num("300")
    a.t("form-save")
    s = a.wait_state(lambda s: s["runs"][rid]["result"] == "ok")
    assert "slope_points" in s["runs"][rid]["missing"] and s["segStatus"]["0"] == "partial", (s["runs"][rid]["missing"], s["segStatus"])
    a.close()
    return a


def test_map_touch_no_ghost(p, url):
    """지도는 손을 떼는 순간 화면을 바꾸지 않고 click에서 고른다. 그래야 새로 올라온 버튼이 눌리지 않는다."""
    a = App(p, url)
    a.setup_day()
    a.t("pick")
    a.see('[data-t="map"]')
    time.sleep(0.2)
    a.tap(".mapctl .mini")
    box = a.page.locator('[data-t="map"]').bounding_box()
    w, h = box["width"], box["height"]
    k0 = min(w / 800, h / 800)
    tx0, ty0 = (w - 800 * k0) / 2, (h - 800 * k0) / 2
    r = 1.6 / k0
    sx, sy = w * 0.5, h * 0.5
    zx, zy = (sx - tx0 * r - 1.6 * 160) / (1 - r), (sy - ty0 * r - 1.6 * 100) / (1 - r)
    a.page.touchscreen.tap(box["x"] + zx, box["y"] + zy)  # 먼저 확대한다
    time.sleep(0.2)
    pointer = """([kind, x, y]) => document.querySelector('[data-t="map"]').dispatchEvent(new PointerEvent(kind, { pointerId: 7, clientX: x, clientY: y, bubbles: true }))"""
    px, py = box["x"] + sx, box["y"] + sy
    a.page.evaluate("HTMLCanvasElement.prototype.setPointerCapture = () => {}")  # 만든 포인터는 붙잡을 수 없다
    a.page.evaluate(pointer, ["pointerdown", px, py])
    a.page.evaluate(pointer, ["pointerup", px, py])
    time.sleep(0.2)
    assert a.page.locator("[data-from]").count() == 0, "손을 떼는 순간 화면이 바뀜"
    a.page.evaluate("""() => document.querySelector('[data-t="map"]').click()""")
    a.see("[data-from]")
    # 실제 터치로도 고를 수 있다
    a.t("map-close")
    a.t("pick")
    a.see('[data-t="map"]')
    time.sleep(0.2)
    a.tap(".mapctl .mini")
    time.sleep(0.1)
    a.page.touchscreen.tap(box["x"] + zx, box["y"] + zy)
    time.sleep(0.2)
    a.page.touchscreen.tap(px, py)
    a.see("[data-from]")
    a.close()
    return a


def test_no_flip_button(p, url):
    """재는 중 더 보기에서 한 번에 방향을 뒤집는 버튼이 없다. 고치기는 구간 머리 줄에서 한다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.see('[data-t="next-mark"]')
    a.t("more")
    a.see('[data-t="break"]')
    assert a.page.locator('[data-t="flip-from"]').count() == 0
    a.close()
    return a


def test_break_not_doubled_after_crash(p, url):
    """끊김 저장 직후 앱이 죽어도 같은 끊김이 두 번 들어가지 않는다."""
    a = App(p, url)
    a.setup_day()
    to_seg0(a)
    a.t("more")
    a.t("break")
    a.num("200")
    a.num("0")
    time.sleep(0.4)
    a.page.evaluate(DROP_UI)
    a.t("form-save")
    a.poll("window.__bf.events().some(e => e.kind === 'break')")
    reopen(a)
    assert a.page.locator('[data-t="form-save"]').count() == 0, "저장한 끊김 입력이 되살아남: " + a.text()[:160]
    assert sum(1 for e in a.events() if e["kind"] == "break") == 1
    a.close()
    return a


def test_run_end_not_restored_after_crash(p, url):
    """구간을 닫은 직후 앱이 죽어도 닫기 화면이 되살아나지 않는다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.tap('[data-tool="end"]')
    a.num("160")
    a.opt("ok")
    a.opt("checked")
    a.see('[data-t="close-run"]')
    time.sleep(0.4)
    a.page.evaluate(DROP_UI)
    a.t("close-run")
    a.poll("window.__bf.events().some(e => e.kind === 'run_end')")
    reopen(a)
    assert a.page.locator('[data-t="close-run"]').count() == 0, "닫기 화면이 되살아남"
    a.close()
    return a


def test_morning_check_all_or_nothing(p, url):
    """도구 점검은 네 기록이 한 번에 저장되고, 중간에 실패하면 아침 점검으로 돌아온다."""
    a = App(p, url)
    a.load_pack()
    a.t("login-skip")
    day_form(a)
    a.t("phone-ok")
    a.sign(True); a.keys("15")
    a.sign(False); a.keys("16")
    a.num("0"); a.num("265"); a.num("0"); a.num("100")
    a.opt("yes")
    a.see('[data-t="form-save"]')
    time.sleep(0.4)
    a.page.evaluate("""() => { const o = IDBObjectStore.prototype.add; IDBObjectStore.prototype.add = function (v) { if (v.data && v.data.tool === 'wheel') throw new Error('죽음'); return o.apply(this, arguments); }; }""")
    a.t("form-save")
    time.sleep(0.4)
    reopen(a)
    tools = sorted(e["data"]["tool"] for e in a.events() if e["kind"] == "tool_check")
    assert tools == ["phone_setup"], tools
    assert a.page.locator('[data-t="arrive"]').count() == 0, "점검 없이 측정으로 감: " + a.text()[:160]
    a.errors.clear()
    a.close()
    return a


def test_level_fail_retry_after_crash(p, url):
    """수평계 실패 뒤 앱이 죽어도 다시 점검을 건너뛰지 않는다."""
    a = App(p, url)
    a.load_pack()
    a.t("login-skip")
    day_form(a)
    a.t("phone-ok")
    a.sign(True); a.keys("15")
    a.sign(False); a.keys("25")
    a.num("0"); a.num("265"); a.num("0"); a.num("100")
    a.opt("yes")
    a.see('[data-t="form-save"]')
    time.sleep(0.4)
    a.page.evaluate(DROP_UI)
    a.t("form-save")
    a.wait_text("수평계 다시 점검")
    reopen(a)
    a.wait_text("수평계 다시 점검")
    assert a.page.locator('[data-t="arrive"]').count() == 0
    a.close()
    return a


def test_bump_has_no_eye_value(p, url):
    """턱 값 칸에 눈높이 숫자를 넣는 길이 없다. 매뉴얼은 값을 비우고 이유를 적으라고 한다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.see('[data-t="next-mark"]')
    a.tap('[data-tool="bump"]')
    a.num("30")
    a.num("30")
    a.opt("up")
    a.opt("square")
    a.num("100")
    a.t("edit-tool")
    a.see('[data-opt="caliper"]')
    assert a.page.locator('[data-opt="eye"]').count() == 0
    a.close()
    return a


def test_target_keeps_both_point(p, url):
    """4를 4.6으로 재도 5 m 의무 지점이 다음 차례로 남고, 어느 예정을 잰 것인지 저장된다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.see('[data-t="next-mark"]')
    a.fill_point("11")
    a.save_point()
    a.first_flow()
    a.see('[data-t="next-mark"]')
    for _ in range(3):
        a.tap('[data-adj="0.2"]')
    a.fill_point("11")
    a.save_point()
    e = [x for x in a.events() if x["kind"] == "slope"][-1]
    assert e["data"]["target"] == 4 and e["data"]["mark"] == 4.6, e["data"]
    d = a.page.evaluate("window.__bf.draft()")
    assert d["mark"] == 5 and d["both"], (d["mark"], d["both"])
    a.close()
    return a


def other_site():
    return custom_pack("other3.json", lambda b: b.update(site="fake2", name="둘째 대상지", net="othernet0000"))


def test_day_form_can_switch_pack(p, url):
    """날짜가 바뀐 오늘 준비 화면에서 다른 자료를 넣을 수 있고 지금 자료 이름이 보인다."""
    from datetime import datetime, timedelta
    other = other_site()
    a = App(p, url)
    a.setup_day()
    a.see('[data-t="arrive"]')
    a.page.clock.set_fixed_time(datetime.now() + timedelta(days=1))
    reopen(a)
    a.see('[data-opt="sunny"]')
    assert "가짜 대상지" in a.text(), a.text()[:200]
    a.load_pack(other)
    a.see('[data-t="login-skip"]')
    assert len(a.events()) == 0
    a.close()
    return a


def test_empty_store_back_to_first_site(p, url):
    """기록 있는 A에서 빈 B로 갔다가 A를 다시 넣으면 A 기록으로 돌아온다."""
    other = other_site()
    a = App(p, url)
    a.setup_day()
    a.see('[data-t="arrive"]')
    n = len(a.events())
    a.t("more")
    a.load_pack(other)
    a.see('[data-t="login-skip"]')
    assert len(a.events()) == 0
    a.t("login-skip")
    a.see('[data-opt="sunny"]')
    a.load_pack()
    a.see('[data-t="login-skip"]')
    time.sleep(0.3)
    assert len(a.events()) == n, (len(a.events()), n)
    a.close()
    return a


def test_switch_failure_stays_on_old_site(p, url):
    """자료 바꾸기가 실패하면 앞 대상지 저장소에 계속 쓴다."""
    other = other_site()
    a = App(p, url)
    a.setup_day()
    a.see('[data-t="arrive"]')
    n = len(a.events())
    a.t("more")
    a.see('input[data-t="pack-file"]')
    a.page.evaluate("""() => { const o = IDBObjectStore.prototype.put; IDBObjectStore.prototype.put = function (v, k) { if (k === 'current') throw new Error('시험용 공간 부족'); return o.apply(this, arguments); }; }""")
    a.load_pack(other)
    a.wait_text("시험용 공간 부족")
    a.t("more-close")
    a.t("skip")
    a.poll(f"window.__bf.events().length === {n + 1}")
    reopen(a)
    assert len(a.events()) == n + 1, (len(a.events()), n)
    a.close()
    return a


def test_test_and_real_stores_separate(p, url):
    """같은 대상지의 시험 자료와 실제 자료는 기록이 섞이지 않는다."""
    real = custom_pack("real.json", lambda b: b.update(test=False))
    a = App(p, url)
    a.setup_day()
    a.see('[data-t="arrive"]')
    a.t("more")
    a.load_pack(real)
    a.see('[data-t="login-skip"]')
    time.sleep(0.3)
    assert len(a.events()) == 0, len(a.events())
    a.close()
    return a


def test_single_phone_wording(p, url):
    """폰 한 대로 재므로 화면에 예비 폰과 두 폰 항목이 없다."""
    a = App(p, url)
    a.load_pack()
    a.t("login-skip")
    a.see('[data-opt="sunny"]')
    assert "예비" not in a.text(), a.text()[:300]
    day_form(a)
    a.see('[data-t="phone-ok"]')
    tx = a.text()
    assert "예비" not in tx and "두 폰" not in tx, tx[:500]
    a.close()
    return a


def test_back_keeps_form(p, url):
    """폰의 뒤로 가기가 입력 중인 양식을 지우지 않는다. 나가려면 화면의 취소를 누른다."""
    a = App(p, url)
    a.setup_day()
    a.start_run()
    a.see('[data-t="next-mark"]')
    a.tap('[data-tool="bump"]')
    a.num("30")
    a.page.go_back()
    a.wait_text("뒤로 가기로 나갈 수 없습니다")
    assert a.page.locator('[data-t="next-mark"]').count() == 0, a.text()[:200]
    a.num("30")
    a.opt("up")
    a.opt("square")
    a.num("100")
    a.see('[data-t="form-save"]')
    assert "30" in a.text(), a.text()[:300]
    a.t("form-cancel")
    a.see('[data-t="next-mark"]')
    assert not [e for e in a.events() if e["kind"] == "barrier"]
    a.close()
    return a


def test_phone_setup_shows_db(p, url):
    """폰 설정에 데이터베이스 상태가 보이고, 로그인을 안 했으면 경고하고 바로 로그인할 수 있다."""
    pk = TMP / "fake_db_pack3.json"
    pk.write_text(json.dumps(fake_pack.build(HERE.parent / "tools" / "rules.json", db=FAKE_DB), ensure_ascii=False), encoding="utf-8")
    a = App(p, url)

    def handler(route, request):
        if "/auth/v1/token" in request.url:
            return route.fulfill(status=200, json={"access_token": "tok", "refresh_token": "ref", "expires_in": 3600})
        if "/rest/v1/field_records" in request.url:
            return route.fulfill(status=201, body="") if request.method == "POST" else route.fulfill(status=200, json=[])
        return route.abort()

    a.ctx.route("https://fake-project.supabase.co/**", handler)
    a.load_pack(pk)
    a.t("login-skip")
    day_form(a)
    a.see('[data-t="phone-ok"]')
    cell = a.page.locator('[data-chk="데이터베이스"]')
    assert "로그인 안 함" in cell.inner_text() and "warn-text" in (cell.get_attribute("class") or ""), cell.inner_text()
    a.t("setup-login")
    a.page.locator('[data-t="email"]').fill("x@test.invalid")
    a.page.locator('[data-t="password"]').fill("y")
    a.t("login")
    a.see('[data-t="phone-ok"]')
    cell = a.page.locator('[data-chk="데이터베이스"]')
    assert "로그인됨" in cell.inner_text() and "warn-text" not in (cell.get_attribute("class") or ""), cell.inner_text()
    assert a.page.locator('[data-t="setup-login"]').count() == 0
    a.close()
    return a


def test_swap_role_saves_file_without_share(p, url):
    """역할을 바꾸면 보낼 폰을 묻지 않고 백업 파일을 폰에 저장한다."""
    a = App(p, url)
    a.setup_day()
    a.see('[data-t="more"]')
    a.page.evaluate("""() => { window.__shared = 0; navigator.canShare = () => true; navigator.share = () => { window.__shared += 1; return Promise.resolve(); }; }""")
    a.t("more")
    with a.page.expect_download() as dl:
        a.t("swap-role")
    assert dl.value.suggested_filename.endswith(".txt")
    assert a.page.evaluate("window.__shared") == 0
    a.poll("window.__bf.events().some(e => e.kind === 'role')")
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
