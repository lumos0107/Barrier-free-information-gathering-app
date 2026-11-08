// 현장 측정 기록 앱. 화면 상태는 S 하나에 두고, 기록은 사건으로만 쌓는다.
import { APP_VERSION } from "./version.js";
import * as C from "./calc.js";
import * as F from "./fields.js";
import { MapView, lonLatToPx, distToPolyline } from "./map.js";
import * as DB from "./store.js";
import * as Sync from "./sync.js";

const root = document.getElementById("app");
const S = {
  pack: null, rules: null, image: null, events: [], st: null, dev: "",
  screen: "boot", params: {}, stack: [], draft: null, form: null, flow: [],
  notices: [], msg: "", storeError: "", other: false, gps: null, gpsError: "", battery: null, wake: "", persist: null,
  pendingN: 0, lastSent: null, lastSaved: null, lastBackup: null, lastShared: null, syncError: "", user: null, recover: "",
  photoDue: null, routePick: null, mapSel: null, mapList: false, mapMode: "pick", drawXy: [], view: null, canvas: null, focusDone: false, sw: {},
};

// 도우미 -------------------------------------------------------------------
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else if (k === "disabled" || k === "checked" || k === "multiple") el[k] = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}
const btn = (label, onclick, attrs = {}) => h("button", { type: "button", onclick, ...attrs }, label);
const round1 = (x) => Math.round(x * 10) / 10;
const round2 = (x) => Math.round(x * 100) / 100;
const fmt1 = (v) => (v == null ? "-" : Number(v).toFixed(1));
const signed = (v) => (v == null ? "-" : `${v >= 0 ? "+" : "-"}${Math.abs(v).toFixed(1)}`);
const nowIso = () => new Date().toISOString();
const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false }) : "-");
const tap = () => { if (navigator.vibrate) navigator.vibrate(8); };

const refold = () => { S.st = C.foldEvents(S.events, S.rules, S.dev, geoOfRun); };
const today = () => new Date().toLocaleDateString("sv-SE");
const dayOf = (iso) => new Date(iso).toLocaleDateString("sv-SE");
// 오늘 출발 전 점검을 했는지. 다른 폰에서 복원한 기록도 센다.
const checkedToday = (tool) => S.st.toolChecks.some((t) => t.tool === tool && t.when === "before" && dayOf(t.at) === today());
const toolsDoneToday = () => ["level", "caliper", "wheel", "phone"].every(checkedToday);
// 수평계가 실패한 채 다시 점검을 안 끝냈으면 그 기록을 돌려준다. 마친 뒤 점검은 다시 재지 않는다.
function levelPending() {
  const last = [...S.st.toolChecks].reverse().find((t) => t.tool === "level");
  return last && last.mode === "pending" && last.when !== "after" ? last : null;
}
const openRun = () => (S.st && S.st.openRun ? S.st.runs[S.st.openRun] : null);

const newPathSeg = (id, n) => (n ? { seg: id, a: `${id}a`, b: `${id}b`, len: n.len, xy: n.xy, isNew: true } : null);
function segOf(id) {
  if (typeof id === "number") return S.pack.segs[id];
  return newPathSeg(id, S.st.newPaths[id]);
}
function geoOfRun(run, st) {
  if (!S.pack) return null;
  const seg = typeof run.seg === "number" ? S.pack.segs[run.seg] : newPathSeg(run.seg, st.newPaths[run.seg]);
  return seg ? C.geoFor(seg, run.from) : null;
}
const { fineFor, stopFor } = C;
const fromLabel = (s, from) => (from === s.a ? "A" : "B");
const distOf = (run, p) => C.continued(p.mark, run.start, run.breaks.slice(0, p.breakCount ?? run.breaks.length));
const markOfDist = (run, dist) => round1(dist - C.continued(0, run.start, run.breaks));
// 지금 표시값. 마지막 지점 뒤에 끊김이 있으면 그 끊김 뒤에 읽은 값이다.
const lastMark = (run) => {
  const pt = run.points[run.points.length - 1];
  const nb = run.breaks.length;
  if (nb && (!pt || (pt.breakCount ?? nb) < nb)) return run.breaks[nb - 1].now;
  return pt ? pt.mark : run.start;
};

// 사건 쓰기. 디스크 기록이 끝난 뒤에만 돌아온다. 실패하면 화면 위에 붉은 띠를 고정한다.
async function emitMany(list) {
  if (S.switching) throw new Error("자료를 바꾸는 중입니다");
  try {
    let ord = S.st ? S.st.maxOrd : 0;
    const evs = await DB.addEvents(list.map(([kind, data, opt = {}]) => (seq) => {
      ord = C.nextOrd(Date.now(), ord);
      return {
        id: opt.id || DB.uid(), seq, ord, kind, run: opt.run || undefined, at: nowIso(), dev: S.dev, app: APP_VERSION,
        site: S.pack.site, test: !!S.pack.test, net: S.pack.net, pack: S.pack.hash, rules: S.rules.version,
        by: S.st ? { m: S.st.people.measurer, r: S.st.people.recorder } : {}, gps: gpsStamp(), data,
      };
    }));
    S.events.push(...evs);
    refold();
    S.pendingN += evs.length;
    S.storeError = "";
    const last = evs.filter((e) => e.kind !== "track").pop();
    if (last) S.lastSaved = last.at;
    scheduleSync();
    return evs;
  } catch (e) {
    if (e && e.name === "ConstraintError") {
      // 이미 저장된 번호. 원값은 그대로 두고 쓰던 칸을 새로 연다.
      S.draft = null;
      S.form = null;
      await reloadEvents();
      S.notices = [{ text: "이 기록은 이미 저장돼 있습니다. 기록 목록에서 값을 확인하세요" }];
      home();
      throw e;
    }
    S.storeError = `저장 실패: ${e.message || e}. 지금 값은 종이에 적어 두세요`;
    render();
    throw e;
  }
}

const emit = async (kind, data, opt = {}) => (await emitMany([[kind, data, opt]]))[0];

// 사건을 쓰는 버튼. 쓰는 동안 다른 쓰기 버튼을 받지 않는다(연타로 시작, 닫기, 찍음이 겹치지 않게).
let acting = false;
const act = (fn) => async (...args) => {
  if (acting) return;
  acting = true;
  try {
    await fn(...args);
  } catch {
    /* 붉은 띠나 알림으로 이미 알렸다 */
  } finally {
    acting = false;
  }
};

function gpsStamp() {
  if (!S.gps) return null;
  return { lon: S.gps.lon, lat: S.gps.lat, acc: S.gps.acc, t: S.gps.t };
}

// 화면 이동 ------------------------------------------------------------------
function go(screen, params = {}, { push = true } = {}) {
  if (push && S.screen !== "boot") S.stack.push({ screen: S.screen, params: S.params });
  if (S.stack.length > 20) S.stack.shift();
  S.screen = screen;
  S.params = params;
  S.focusDone = false;
  render();
  flushUi();
}

function goBack() {
  const prev = S.stack.pop();
  if (prev) {
    S.screen = prev.screen;
    S.params = prev.params;
    S.focusDone = false;
    render();
    flushUi();
  } else home();
}

function home() {
  S.stack = [];
  S.form = null;
  if (!S.pack) return go("pack", {}, { push: false });
  // 날짜가 바뀌면 오늘 준비부터 다시 한다(이틀째 측정, 시험 뒤 실제 측정)
  if (!S.st.day || S.st.day.date !== today()) return startDay();
  // 폰 설정 화면에서 앱이 다시 열려도 아침 점검을 건너뛰지 않는다
  if (!checkedToday("phone_setup")) return go("phone_setup", {}, { push: false });
  // 도구 점검 네 기록이 다 있어야 끝난 것이다. 수평계가 실패했으면 다시 점검부터 한다.
  if (!toolsDoneToday()) return openForm("tool", null, { run: null, ctx: { when: "before" } });
  const lv = levelPending();
  if (lv) return openForm("level_retry", null, { run: null, ctx: { first: Math.abs(Math.abs(lv.values[0]) - Math.abs(lv.values[1])), when: lv.when } });
  if (openRun()) return go("measure", {}, { push: false });
  if (routeNeeded()) return go("route", {}, { push: false });
  return go("move", {}, { push: false });
}

let uiTimer = null;
function persistUi() {
  clearTimeout(uiTimer);
  uiTimer = setTimeout(flushUi, 120);
}
function flushUi() {
  clearTimeout(uiTimer);
  if (!S.pack || S.switching) return;
  const form = S.form ? { ...S.form, saving: undefined } : null;
  DB.setMeta("ui", { draft: S.draft, form, flow: S.flow, photoDue: S.photoDue }).catch(() => {});
}

function render() {
  const body = (SCREENS[S.screen] || homeScreen)();
  const top = topBar();
  const bands = [];
  if (S.storeError) bands.push(h("div", { class: "band-red", "data-t": "store-error" }, S.storeError));
  if (S.other) bands.push(h("div", { class: "band-red", "data-t": "other-tab" }, "다른 창이 열려 있습니다. 한 창에서만 입력하세요"));
  if (/KAKAOTALK|Instagram|NAVER\(/i.test(navigator.userAgent)) bands.push(h("div", { class: "band-red" }, "메신저 안 브라우저입니다. Chrome으로 여세요"));
  root.replaceChildren(top, ...bands, body);
  if (S.afterRender) {
    const f = S.afterRender;
    S.afterRender = null;
    requestAnimationFrame(f);
  }
  persistUi();
}

function topBar() {
  const parts = [];
  if (S.lastSaved) parts.push(h("span", { class: "saved" }, `저장됨 ${clock(S.lastSaved)}`));
  if (S.pack) {
    if (Sync.isConfigured()) {
      if (!S.user) parts.push(h("span", {}, "폰에만 저장"));
      else if (S.syncError) parts.push(h("span", { class: "warn" }, `전송 대기 ${S.pendingN}`));
      else parts.push(h("span", {}, S.pendingN ? `전송 대기 ${S.pendingN}` : "전송 끝"));
    }
    if (S.gps) parts.push(h("span", { class: S.gps.acc > S.rules.app.gps_acc_warn_m ? "warn" : "" }, `위치 ±${Math.round(S.gps.acc)} m`));
    else if (watchId !== null && !S.gpsError) parts.push(h("span", {}, "위치 찾는 중"));
    else parts.push(btn(S.gpsError ? "위치 안 됨: 다시 켜기" : "위치 켜기", () => startGps(true), { class: "warn", "data-t": "gps-retry" }));
    if (S.battery != null) parts.push(h("span", { class: S.battery <= S.rules.app.battery_warn ? "warn" : "" }, `전지 ${S.battery}%`));
    if (S.wake === "off") parts.push(h("span", { class: "warn" }, "화면 켜짐 안 됨"));
    const p = S.st && S.st.people;
    if (p && p.since) {
      const m = Math.floor((Date.now() - Date.parse(p.since)) / 60000);
      parts.push(h("span", { class: m >= S.rules.app.role_minutes ? "warn" : "" }, `${p.recorder || "-"} 기록 ${m}분`));
    }
  }
  return h("div", { class: "top", id: "top" }, parts.length ? parts : "현장 측정 기록");
}
const refreshTop = () => { const t = document.getElementById("top"); if (t) t.replaceWith(topBar()); };

// 자료 파일과 로그인 ----------------------------------------------------------
function b64ToBlob(b64) {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) u8[i] = bin.charCodeAt(i);
  return new Blob([u8], { type: "image/jpeg" });
}

async function usePack(stored) {
  S.pack = stored;
  S.rules = stored.rules;
  Sync.configure(stored.db);
  if (stored.aerialBlob) {
    try {
      S.image = await createImageBitmap(stored.aerialBlob);
    } catch {
      S.image = null;
    }
  }
  // 위치는 사람이 누를 때 처음 묻는다. 터치 없이 물으면 창 없이 막히는 브라우저가 있다.
  try {
    const st = await navigator.permissions.query({ name: "geolocation" });
    if (st.state === "granted") startGps();
  } catch { /* 권한 조회가 없는 브라우저는 '위치 켜기'로 켠다 */ }
}

// 저장소를 바꾼다. 지금 기록은 이 저장소에 그대로 남는다. 실패하면 앞 저장소로 돌아간다.
async function switchPack(stored, key, curKey) {
  const oldName = DB.currentName();
  flushUi();
  S.switching = true;
  try {
    DB.claim(curKey, oldName);
    const name = DB.nameFor(key);
    await DB.switchTo(name);
    await DB.putPack(stored);
    DB.claim(key, name);
  } catch (e) {
    await DB.switchTo(oldName);
    DB.claim(curKey, oldName);
    S.switching = false;
    throw e;
  }
  sessionStorage.setItem("bf-after-switch", `${S.pack.name} 기록은 이 폰에 그대로 있습니다. 그 자료를 다시 넣으면 이어집니다`);
  location.reload();
}

async function importPack(file) {
  S.msg = "";
  try {
    const j = JSON.parse(await file.text());
    if (j.format !== 1 || !j.segs || !j.rules) throw new Error("자료 파일 형식이 아닙니다");
    const { aerial, ...rest } = j;
    const stored = { ...rest, aerialBlob: aerial ? b64ToBlob(aerial) : null };
    const key = DB.siteKey(j);
    const curKey = S.pack ? DB.siteKey(S.pack) : null;
    // 다른 대상지: 그 대상지 저장소로 옮긴다. 지금 저장소가 비어 있어도 이미 있는 저장소는 그쪽으로 간다.
    if (S.pack && curKey !== key && (S.events.length || DB.hasStore(key))) {
      await switchPack(stored, key, curKey);
      return;
    }
    await DB.putPack(stored);
    DB.claim(key, DB.currentName());
    await usePack(stored);
    refold();
    go("login", {}, { push: false });
  } catch (e) {
    S.msg = e.message;
    render();
  }
}

const packInput = () => h("input", { type: "file", accept: ".json,.txt,application/json", "data-t": "pack-file", onchange: (e) => e.target.files[0] && importPack(e.target.files[0]) });

function packScreen() {
  return h("div", { class: "screen" },
    h("h1", {}, "자료 파일 넣기"),
    h("p", {}, "PC에서 받은 자료 파일(.json)을 고르세요. 구간표와 항공사진이 이 폰에만 저장됩니다."),
    packInput(),
    S.msg && h("div", { class: "notice" }, S.msg),
    h("p", { class: "small" }, `앱 판 ${APP_VERSION}`));
}

function restoreInput() {
  return h("input", { type: "file", accept: ".txt,.json,application/json,text/plain", "data-t": "restore-file", onchange: (e) => e.target.files[0] && restoreFile(e.target.files[0]) });
}

function loginScreen() {
  const switched = S.switchNote;
  const email = h("input", { type: "email", "data-t": "email", placeholder: "이메일", autocomplete: "username", value: S.loginEmail || "" });
  const password = h("input", { type: "password", "data-t": "password", placeholder: "비밀번호", autocomplete: "current-password" });
  const has = Sync.isConfigured();
  return h("div", { class: "screen" },
    h("h1", {}, "로그인"),
    switched && h("div", { class: "info" }, `자료를 바꿨습니다: ${S.pack.name}. ${switched}`),
    has ? h("p", {}, "로그인하면 통신될 때 기록의 사본이 데이터베이스로 갑니다. 통신이 없어도 폰에는 저장됩니다.") : h("p", {}, "이 자료 파일에는 데이터베이스 정보가 없습니다. 폰에만 저장합니다."),
    has && email, has && password,
    S.msg && h("div", { class: "notice" }, S.msg),
    has && btn("로그인", async () => {
      S.msg = "";
      S.loginEmail = email.value.trim();
      try {
        S.user = await Sync.login(S.loginEmail, password.value);
        home();
        scheduleSync();
      } catch (e) {
        S.msg = e.message;
        render();
      }
    }, { class: "primary", "data-t": "login" }),
    btn(has ? "로그인 없이 쓰기" : "다음", () => { S.msg = ""; home(); }, { "data-t": "login-skip" }),
    h("h2", {}, "빈 폰이라면"),
    h("p", { class: "small" }, "백업 파일을 고르면 기록을 복원하고 이어서 씁니다."),
    restoreInput());
}

async function restoreFile(file) {
  S.msg = "";
  try {
    const j = JSON.parse(await file.text());
    if (j.format !== "bf-backup-1" || !Array.isArray(j.events)) throw new Error("백업 파일이 아닙니다");
    if (j.site !== S.pack.site || j.net !== S.pack.net) throw new Error("다른 연결망의 백업입니다. 같은 자료 파일을 넣은 뒤 복원하세요");
    const good = j.events.filter(sameSite);
    const bad = j.events.length - good.length;
    const r = await DB.importEvents(good);
    await reloadEvents();
    setRecover(`복원 ${r.added}건, 이미 있던 ${r.skipped}건${bad ? `, 대상지나 시험 표시가 달라 넣지 않음 ${bad}건` : ""}`);
    S.notices = [];
    S.draft = null;
    home();
  } catch (e) {
    S.msg = e.message;
    render();
  }
}

// 이 자료와 같은 대상지, 연결망, 시험 표시의 사건만 받는다
const sameSite = (e) => !!e && e.site === S.pack.site && e.net === S.pack.net && !!e.test === !!S.pack.test;

async function reloadEvents() {
  S.events = await DB.allEvents();
  refold();
  S.pendingN = await DB.pendingCount();
  const last = [...S.events].filter((e) => e.kind !== "track").sort((a, b) => Date.parse(b.at) - Date.parse(a.at))[0];
  S.lastSaved = last ? last.at : null;
}

function setRecover(prefix = "") {
  const run = openRun();
  const parts = [];
  if (prefix) parts.push(prefix);
  if (run) {
    const pt = run.points[run.points.length - 1];
    parts.push(`구간 ${run.seg}${pt ? `, 표시값 ${fmt1(pt.mark)}` : ""}까지 저장됨`);
    if (S.draft && (S.draft.longs.length || S.draft.buf)) parts.push("쓰던 칸 있음");
  } else if (S.events.length) parts.push(`기록 ${S.events.length}건 저장됨`);
  S.recover = parts.join(". ");
}

// 단계 입력 정의 ---------------------------------------------------------------
const DAY_FORM = {
  label: "오늘 준비",
  steps: [
    { key: "weather", label: "날씨", type: "choice", options: F.WEATHER },
    { key: "measurer", label: "재는 사람", type: "text", required: true },
    { key: "recorder", label: "적는 사람", type: "text", required: true },
  ],
  photos: () => 0,
};
const TOOL_FORM = {
  label: "도구 점검",
  steps: [
    { key: "level_a", label: "수평계: A 끝을 위쪽으로 놓고", type: "signed", unit: "°", decimals: 1 },
    { key: "level_b", label: "수평계: A 끝을 아래쪽으로 놓고", type: "signed", unit: "°", decimals: 1 },
    { key: "cal_closed", label: "캘리퍼: 날을 닫아서", type: "num", unit: "mm", decimals: 1 },
    { key: "cal_coin", label: "캘리퍼: 500원 동전", type: "num", unit: "mm", decimals: 1 },
    { key: "cal_depth", label: "캘리퍼: 깊이 바", type: "num", unit: "mm", decimals: 1 },
    { key: "wheel", label: "워킹카운터: 표시한 10 m", type: "num", unit: "m", decimals: 1 },
    { key: "phone_geo", label: "폰: 사진에 위치가 붙나요", type: "choice", options: [["yes", "붙음"], ["no", "안 붙음"]] },
  ],
  photos: () => 0,
};
const LEVEL_FORM = { label: "수평계 점검", steps: TOOL_FORM.steps.slice(0, 2), photos: () => 0 };
const LEVEL_RETRY_FORM = {
  label: "수평계 다시 점검",
  steps: [
    { key: "level_a", label: "바닥을 닦고 같은 자리에서: A 끝 위쪽", type: "signed", unit: "°", decimals: 1 },
    { key: "level_b", label: "같은 자리에서: A 끝 아래쪽", type: "signed", unit: "°", decimals: 1 },
  ],
  photos: () => 0,
};
const ANGLE_FORM = {
  label: "낮 각도기 비교",
  steps: [
    { key: "level", label: "수평계 값", type: "signed", unit: "°", decimals: 1 },
    { key: "angle", label: "각도기 값", type: "signed", unit: "°", decimals: 1 },
  ],
  photos: () => 0,
};
const START_FORM = { label: "시작값", steps: [{ key: "start", label: "지금 워킹카운터 표시값", type: "mark", unit: "m", decimals: 1 }], photos: () => 0 };
const END_FORM = {
  label: "구간 끝",
  steps: [
    { key: "end", label: "끝값 (워킹카운터)", type: "mark", unit: "m", decimals: 1 },
    { key: "result", label: "구간 확인", type: "choice", options: F.RESULTS },
    { key: "reason", label: "멈춘 이유", type: "text", showIf: (a) => a.result === "stopped" && !a.planned },
    { key: "memo", label: "구간 메모", type: "text", auto: null },
  ],
  photos: () => 0,
};

// 구간 끝 질문. 장벽을 하나도 안 적었으면 '찾아봤고 없음'을 남기고, 순서에 없는 옆 선이 있으면 실제 길인지 묻는다.
function endDef(form) {
  const ctx = form.ctx;
  const walking = (a) => a.result === "ok" || a.result === "stopped";
  const [endStep, resultStep, reasonStep, memoStep] = END_FORM.steps;
  const steps = [endStep, resultStep, reasonStep,
    { key: "no_barrier", label: "턱, 틈, 좁은 곳을 찾아봤나요 (적은 장벽 없음)", type: "choice", options: [["checked", "찾아봤고 없음"], ["not_looked", "못 봄"]], showIf: (a) => ctx.noBarrierAsk && walking(a) }];
  if (ctx.twin != null) steps.push({ key: "twin", label: `옆 선 구간 ${ctx.twin}이 실제 길인가요`, type: "choice", options: [["yes", "있음"], ["no", "없음"], ["unknown", "모름"]], showIf: walking });
  steps.push(memoStep);
  return { ...END_FORM, steps };
}

function runFixDef(form) {
  const steps = [{ key: "start", label: "시작값", type: "mark", unit: "m", decimals: 1 }];
  if (form.ctx.closed) steps.push({ key: "end", label: "끝값", type: "mark", unit: "m", decimals: 1 }, { key: "result", label: "구간 확인", type: "choice", options: F.RESULTS });
  const seg = segOf(form.ctx.seg);
  if (seg) steps.push({ key: "from", label: "출발 마디", type: "choice", options: [[seg.a, "A에서 출발"], [seg.b, "B에서 출발"]] });
  return { label: `구간 ${form.ctx.seg} 고치기`, steps, photos: () => 0 };
}

function openRunFix(r) {
  const initial = { start: r.start, from: r.from };
  if (r.closed) Object.assign(initial, { end: r.end, result: r.result });
  openForm("run_fix", null, { run: r.id, initial, ctx: { seg: r.seg, closed: r.closed } });
}

function slopeEditDef(form) {
  const steps = [{ key: "mark", label: "표시값", type: "mark", unit: "m", decimals: 1 }];
  for (let i = 0; i < (form.ctx.longs || 0); i += 1) steps.push({ key: `long-${i}`, label: `앞뒤 ${i + 1}`, type: "signed", unit: "°", decimals: 1 });
  for (let i = 0; i < (form.ctx.crosses || 0); i += 1) steps.push({ key: `cross-${i}`, label: `좌우 ${i + 1}`, type: "cross", unit: "°", decimals: 1 });
  return { label: "경사 지점 고치기", steps, photos: () => 0 };
}

function defOf(form) {
  switch (form.kind) {
    case "barrier": return F.BARRIERS[form.type];
    case "surface": {
      if (form.answers.changed) return { ...F.SURFACE, steps: F.SURFACE.steps.map((s) => (s.key === "mark" ? { ...s, auto: undefined } : s)) };
      // 구간의 첫 노면은 구간 시작부터다
      const run = form.run && S.st.runs[form.run];
      if (run && !run.surfaces.length && !form.fixOf) return { ...F.SURFACE, steps: F.SURFACE.steps.map((s) => (s.key === "mark" ? { ...s, auto: "start" } : s)) };
      return F.SURFACE;
    }
    case "facility": return F.FACILITIES[form.type];
    case "map_check": return F.MAP_CHECK;
    case "break": return F.BREAK_FORM;
    case "day": return DAY_FORM;
    case "tool": return TOOL_FORM;
    case "level": return LEVEL_FORM;
    case "level_retry": return LEVEL_RETRY_FORM;
    case "angle": return ANGLE_FORM;
    case "start_value": return START_FORM;
    case "run_end": return endDef(form);
    case "point_note": return F.POINT_NOTE;
    case "slope_edit": return slopeEditDef(form);
    case "run_fix": return runFixDef(form);
    default: return null;
  }
}

function openForm(kind, type, opts = {}) {
  S.form = { kind, type: type || null, id: DB.uid(), run: opts.run ?? (openRun() ? openRun().id : null), answers: { ...(opts.initial || {}) }, buf: "", sign: null, ten: false, fixOf: opts.fixOf || null, ctx: opts.ctx || {}, editing: false };
  S.msg = "";
  go("form");
}

function stepsOf(form) {
  const def = defOf(form);
  return def.steps.filter((s) => !s.showIf || s.showIf(form.answers, S.rules));
}

function autoValue(step, form) {
  const run = form.run && S.st.runs[form.run];
  if (step.auto === "current") return run ? lastMark(run) : null;
  if (step.auto === "start") return run ? run.start : null;
  return step.auto;
}

// '못 잼'으로 비운 칸. 구간을 닫을 때 못 잰 항목으로 센다.
const unreadOf = (form) => stepsOf(form).filter((st) => st.blank === F.UNREADABLE && Object.hasOwn(form.answers, st.key) && form.answers[st.key] == null).map((st) => st.key);

function currentStep(form) {
  for (const s of stepsOf(form)) {
    if (Object.hasOwn(form.answers, s.key)) continue;
    if (s.auto !== undefined && !(form.ctx.askAuto || []).includes(s.key)) {
      form.answers[s.key] = autoValue(s, form);
      continue;
    }
    return s;
  }
  return null;
}

function displayAnswer(step, v) {
  if (v === null || v === undefined || v === "") return step.blank || "비움";
  if (step.type === "choice") return F.labelOf(step.options, v);
  if (step.type === "signed") return `${signed(v)}${step.unit || ""}`;
  if (step.type === "text") return v;
  const d = step.decimals ?? 0;
  return `${Number(v).toFixed(d)} ${step.unit || ""}`.trim();
}

function setAnswer(form, step, value) {
  form.answers[step.key] = value;
  form.buf = "";
  form.sign = null;
  form.ten = false;
  afterAnswer(form);
}

function afterAnswer(form) {
  const def = defOf(form);
  if (!currentStep(form) && def.autoSave) {
    saveForm();
    return;
  }
  render();
}

function photoCountFor(id) {
  return (S.st.photos && S.st.photos[id]) || 0;
}

function formScreen() {
  const form = S.form;
  if (!form) { setTimeout(home, 0); return h("div", { class: "screen" }); }
  const def = defOf(form);
  const step = currentStep(form);
  const answered = stepsOf(form).filter((s) => Object.hasOwn(form.answers, s.key));
  const list = h("div", { class: "answers" }, answered.map((s) => h("button", {
    type: "button", class: "answer", "data-t": `edit-${s.key}`,
    onclick: () => {
      delete form.answers[s.key];
      if (s.auto !== undefined) form.ctx.askAuto = [...(form.ctx.askAuto || []), s.key];
      form.buf = "";
      form.sign = null;
      render();
    },
  }, h("span", {}, s.label), h("b", {}, displayAnswer(s, form.answers[s.key])))));
  return h("div", { class: form.kind === "day" ? "screen" : "screen fill" },
    h("div", { class: "spread" }, h("h1", {}, def.label), form.kind !== "day" && btn("취소", cancelForm, { class: "mini", "data-t": "form-cancel" })),
    form.kind === "day" && S.user && !S.events.length && btn("다른 폰 기록을 데이터베이스에서 받기", pullDb, { class: "mini", "data-t": "pull-db" }),
    form.kind === "day" && h("div", { class: "info" },
      h("div", {}, `지금 자료: ${S.pack.name}${S.pack.test ? " (시험 자료)" : ""}. 다른 대상지를 재려면 자료 파일을 고르세요`), packInput(),
      h("div", {}, "다른 폰에서 이어 쓰려면 백업 파일을 고르세요"), restoreInput()),
    list,
    S.msg && h("div", { class: "notice" }, S.msg),
    step ? stepPanel(form, step) : summaryPanel(form, def));
}

function stepPanel(form, step) {
  const warn = step.warn && form.buf ? step.warn(C.fixedValue(form.buf, step.decimals ?? 0), S.rules) : null;
  const q = h("div", { class: "question" }, step.label);
  if (step.type === "choice") {
    const opts = step.options.map(([v, label]) => btn(label, () => { tap(); setAnswer(form, step, v); }, { "data-opt": v }));
    if (form.kind === "surface" && step.key === "material" && !form.answers.changed && S.lastSurface()) {
      const ls = S.lastSurface();
      opts.unshift(btn(`앞과 같음: ${F.labelOf(F.MATERIALS, ls.material)}, ${F.labelOf(F.GRADES, ls.grade)}`, () => {
        Object.assign(form.answers, { material: ls.material, grade: ls.grade, grade2: ls.grade2 || "", same: true });
        saveForm();
      }, { "data-opt": "__same", class: "primary" }));
    }
    return h("div", { class: "panel" }, q, h("div", { class: `options${step.grid ? " grid" : ""}` }, opts));
  }
  if (step.type === "text") {
    const ta = h("textarea", { "data-t": "text", value: form.answers[`__${step.key}`] || "", rows: 2 });
    return h("div", { class: "panel" }, q, ta, btn(step.required ? "다음" : "다음 (비워도 됨)", () => {
      const v = ta.value.trim();
      if (step.required && !v) { S.msg = `${step.label}을 적어 주세요`; render(); return; }
      S.msg = "";
      setAnswer(form, step, v || null);
    }, { class: "primary", "data-t": "next" }));
  }
  // 숫자
  const decimals = step.decimals ?? 0;
  const isSigned = step.type === "signed";
  const auto = isSigned || step.type === "cross";
  const shown = form.buf ? C.fixedValue(form.buf, decimals).toFixed(decimals) : "";
  const onKey = (k) => {
    tap();
    if (k === "del") { form.buf = form.buf.slice(0, -1); render(); return; }
    if (k === "ok") {
      if (!form.buf) return;
      setAnswer(form, step, C.fixedValue(form.buf, decimals));
      return;
    }
    if (isSigned && !form.sign) { S.msg = "부호를 먼저 누르세요"; render(); return; }
    S.msg = "";
    if (form.buf.length >= 6) return;
    form.buf += k;
    if (auto && form.buf.length >= (form.ten ? 3 : 2)) {
      const v = C.fixedValue(form.buf, decimals);
      setAnswer(form, step, isSigned ? (form.sign === "minus" ? -v : v) : v);
      return;
    }
    render();
  };
  return h("div", { class: "panel" },
    q,
    h("div", { class: "numline", "data-t": "num" }, isSigned && form.sign ? (form.sign === "plus" ? "+" : "-") : "", shown || " ", h("span", { class: "unit" }, step.unit || "")),
    warn && h("div", { class: "notice" }, warn),
    isSigned && signRow(form.sign, (sg) => { form.sign = sg; S.msg = ""; render(); }, form.ten, () => { form.ten = !form.ten; render(); }),
    (step.blank || step.quick) && h("div", { class: "row" },
      (step.quick || []).map(([k, v, label]) => btn(label, () => setAnswer(form, step, v), { class: "mini", "data-quick": k })),
      step.blank && btn(step.blank, () => setAnswer(form, step, null), { class: "mini", "data-t": "blank" })),
    pad(onKey, auto ? null : "다음", auto ? false : !!form.buf, "ok"));
}

function summaryPanel(form, def) {
  if (form.kind === "run_end") return endReview(form);
  const need = def.photos ? def.photos(form.answers, S.rules) : 0;
  const got = photoCountFor(form.id);
  const armed = !!form.ctx.voidArm;
  return h("div", { class: "panel" },
    form.kind === "run_fix" && btn("구간 번호 바꾸기", () => openMap("change", form.run), { class: "mini", "data-t": "run-change-seg" }),
    form.fixOf && (form.kind === "slope_edit" || form.kind === "break") && btn(armed ? "한 번 더 누르면 지웁니다" : form.kind === "break" ? "이 끊김 지우기" : "이 지점 지우기", act(async () => {
      if (!armed) {
        form.ctx.voidArm = true;
        render();
        setTimeout(() => { if (S.form === form && form.ctx.voidArm) { form.ctx.voidArm = false; render(); } }, 4000);
        return;
      }
      await emit("void", { of: form.fixOf }, { run: form.run });
      S.draft = null;
      S.form = null;
      home();
    }), { class: armed ? "warn" : "mini", "data-t": "void-record" }),
    form.fixOf && h("p", { class: "small" }, "고칠 칸은 위 목록에서 누르세요"),
    need > 0 && def.shot && h("p", { class: "small" }, `사진: ${def.shot}`),
    (need > 0 || form.kind === "barrier" || form.kind === "surface" || form.kind === "facility" || form.kind === "map_check") &&
      btn(`사진 찍음 ${got}/${need}`, act(async () => { tap(); await emit("photo", { of: form.id }, { run: form.run }); render(); }), { class: got < need ? "warn" : "", "data-t": "photo" }),
    btn("저장", saveForm, { class: "primary", "data-t": "form-save" }));
}

function cancelForm() {
  S.afterClose = null;
  S.form = null;
  S.flow = [];
  S.msg = "";
  goBack();
}

function cleanAnswers(form) {
  const out = {};
  const visible = new Set(stepsOf(form).map((s) => s.key));
  for (const [k, v] of Object.entries(form.answers)) {
    if (k.startsWith("__")) continue;
    if (visible.has(k) || !defOf(form).steps.some((s) => s.key === k)) out[k] = v;
  }
  return out;
}

async function saveForm() {
  const form = S.form;
  if (!form || form.saving) return;
  form.saving = true;
  const data = cleanAnswers(form);
  const def = defOf(form);
  const need = def.photos ? def.photos(form.answers, S.rules) : 0;
  try {
    switch (form.kind) {
      case "day":
        await emit("day", { ...data, site: S.pack.site, date: today(), net: S.pack.net }, { id: form.id });
        S.form = null;
        return go("phone_setup", {}, { push: false });
      case "tool": return await saveTool(data, form.ctx.when || "before");
      case "level": return await saveLevel(data, form.ctx.when || "drop");
      case "level_retry": return await saveLevelRetry(data, form.ctx);
      case "angle":
        await emit("tool_check", { when: "midday", tool: "angle", values: [data.level, data.angle], passed: true });
        S.form = null;
        return goBack();
      case "start_value":
        S.form = null;
        return await beginRun({ ...form.ctx, start: data.start });
      case "run_end": return await closeRun(form, data, false);
      case "point_note":
        if (S.draft) Object.assign(S.draft, { clear: data.clear || null, memo: data.memo || "" });
        S.form = null;
        return goBack();
      case "slope_edit": {
        const values = Object.keys(data).filter((k) => k.startsWith("long-")).sort().map((k) => data[k]);
        const cross = Object.keys(data).filter((k) => k.startsWith("cross-")).sort().map((k) => data[k]);
        await emit("fix", { of: form.fixOf, data: { mark: data.mark, values, cross } }, { run: form.run });
        S.draft = null;
        S.form = null;
        S.notices = [];
        return goBack();
      }
      case "run_fix": {
        const run = S.st.runs[form.run];
        const changes = {};
        if (data.start != null && data.start !== run.start) changes.start = data.start;
        if (data.from != null && data.from !== run.from) changes.from = data.from;
        if (Object.keys(changes).length) await emit("run_edit", { changes, why: "fix_run" }, { run: run.id });
        S.draft = null;
        if (run.closed && run.endId && (data.end !== run.end || data.result !== run.result)) await emit("fix", { of: run.endId, data: { end: data.end, result: data.result } }, { run: run.id });
        S.form = null;
        return goBack();
      }
      case "break":
        if (form.fixOf) await emit("fix", { of: form.fixOf, data }, { run: form.run });
        else await emit("break", data, { id: form.id, run: form.run });
        S.draft = null;
        S.form = null;
        return goBack();
      default: break;
    }
    if (form.fixOf) {
      // 고친 뒤 숨은 칸은 합친 값에서 지운다(unset)
      const shown = new Set(stepsOf(form).map((st) => st.key));
      const unset = def.steps.map((st) => st.key).filter((k) => !shown.has(k));
      await emit("fix", { of: form.fixOf, data: { ...data, photos_required: need, unread: unreadOf(form) }, unset }, { run: form.run });
    } else {
      const run = form.run && S.st.runs[form.run];
      await emit(form.kind, { type: form.type, ...data, photos_required: need, unread: unreadOf(form), breakCount: run ? run.breaks.length : undefined }, { id: form.id, run: form.run });
    }
    const got = photoCountFor(form.id);
    S.form = null;
    S.msg = "";
    if (got < need) S.photoDue = { of: form.id, n: need - got, label: def.label, run: form.run };
    if (form.ctx.flow) return continueFlow();
    home();
  } catch {
    /* 붉은 띠로 알렸다. 입력은 그대로 둔다 */
  } finally {
    form.saving = false;
  }
}

// 오늘 준비와 도구 점검 ---------------------------------------------------------
function startDay() {
  S.stack = [];
  S.form = { kind: "day", type: null, id: DB.uid(), run: null, answers: {}, buf: "", sign: null, ten: false, fixOf: null, ctx: {} };
  S.screen = "form";
  render();
}

const PHONE_ITEMS = [
  "홈 화면 아이콘으로 열었다 (메신저 링크 아님)", "위치 권한이 '정확한 위치'다",
  "화면 자동 꺼짐을 늘렸다", "절전 모드를 껐다", "자동 회전을 껐다", "방해 금지를 켰다", "폰의 시각이 자동이다", "저장 공간 5 GB 이상, 전지 충분",
  "비행기 모드로 앱을 다시 열어 봤다", "이 폰에서 같은 주소의 다른 사이트를 열지 않는다",
];

// 폰이 한 대라 데이터베이스가 폰 밖의 유일한 사본이다.
function dbCheck() {
  const name = "데이터베이스";
  if (!Sync.isConfigured()) return [name, "자료 파일에 정보 없음 (폰에만 저장)", false];
  if (!S.user) return [name, "로그인 안 함 (기록이 폰에만 남습니다)", false];
  if (S.syncError) return [name, `전송 대기 ${S.pendingN}건. ${S.syncError}`, false];
  return [name, S.pendingN ? `로그인됨, 전송 대기 ${S.pendingN}건` : "로그인됨, 전송 끝", true];
}

function autoChecks() {
  const sw = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
  return [
    ["위치", S.gps ? `수신 ±${Math.round(S.gps.acc)} m` : S.gpsError || (watchId === null ? "아직 안 켬" : "기다리는 중"), !!S.gps],
    ["통신 없이 열기", sw ? "준비됨" : "아직 안 됨 (앱을 닫았다 다시 여세요)", sw],
    ["저장 유지", S.persist === null ? "확인 전" : S.persist ? "허용됨" : "허용 안 됨 (백업 간격을 지키세요)", !!S.persist],
    ["화면 켜짐", S.wake === "on" ? "유지 중" : S.wake === "off" ? "안 됨" : "확인 전", S.wake === "on"],
    dbCheck(),
    ["앱 판", APP_VERSION, true],
    ["자료 판", `${S.pack.hash.slice(0, 6)}${S.pack.test ? " (시험 자료)" : ""}`, true],
  ];
}

function phoneSetupScreen() {
  const rows = autoChecks();
  const save = (passed) => act(async () => {
    await emit("tool_check", { when: "before", tool: "phone_setup", checked: passed ? PHONE_ITEMS.length : null, of: PHONE_ITEMS.length, passed, auto: Object.fromEntries(rows.map(([k, , ok]) => [k, ok])) });
    openForm("tool", null, { run: null, ctx: { when: "before" } });
  });
  return h("div", { class: "screen" },
    h("h1", {}, "폰 설정 확인"),
    h("table", {}, h("tbody", {}, rows.map(([a, b, ok]) => h("tr", {}, h("th", {}, a), h("td", { class: ok ? "" : "warn-text", "data-chk": a }, b))))),
    !S.gps && btn("위치 켜기", () => { startGps(true); render(); }, { class: "primary", "data-t": "gps-on" }),
    Sync.isConfigured() && !S.user && btn("로그인", () => go("login"), { class: "primary", "data-t": "setup-login" }),
    h("h2", {}, "손으로 확인할 것"),
    h("ul", { class: "plain" }, PHONE_ITEMS.map((t) => h("li", {}, t))),
    btn("모두 확인함, 도구 점검으로", save(true), { class: "primary", "data-t": "phone-ok" }),
    btn("못 한 것 있음 (그래도 진행)", save(false), { "data-t": "phone-partial" }));
}

async function saveTool(d, when) {
  const R = S.rules;
  const levelOk = C.levelCheck(d.level_a, d.level_b, R);
  const calOk = C.caliperCheck(d.cal_closed, d.cal_coin, d.cal_depth, R);
  const wheelOk = C.wheelCheck(d.wheel, R);
  // 네 기록을 한 번에 쓴다. 중간에 앱이 죽어 일부만 남으면 아침 점검이 끝난 것처럼 보인다.
  await emitMany([
    ["tool_check", { when, tool: "level", values: [d.level_a, d.level_b], passed: levelOk, mode: levelOk ? null : "pending" }],
    ["tool_check", { when, tool: "caliper", values: [d.cal_closed, d.cal_coin, d.cal_depth], passed: calOk }],
    ["tool_check", { when, tool: "wheel", values: [d.wheel], passed: wheelOk }],
    ["tool_check", { when, tool: "phone", values: [d.phone_geo], passed: d.phone_geo === "yes" }],
  ]);
  S.form = null;
  S.notices = [];
  if (!calOk) S.notices.push({ text: "캘리퍼 점검 실패. 전지를 갈고 다시 하세요. 안 되면 철자로 읽고 '철자'로 적습니다" });
  if (!wheelOk) S.notices.push({ text: "워킹카운터 점검 범위 밖. 값은 저장했습니다. 그대로 재도 위치는 끝값으로 나눠 씁니다" });
  if (d.phone_geo !== "yes") S.notices.push({ text: "사진에 위치가 안 붙습니다. 카메라 위치 설정을 켜세요" });
  if (!levelOk && when !== "after") {
    return openForm("level_retry", null, { run: null, ctx: { first: Math.abs(Math.abs(d.level_a) - Math.abs(d.level_b)), when } });
  }
  if (!levelOk && when === "after") S.notices.push({ text: "마친 뒤 수평계 실패. 마지막 통과 뒤 경사 값은 저녁에 표시됩니다" });
  home();
}

async function saveLevel(d, when) {
  const ok = C.levelCheck(d.level_a, d.level_b, S.rules);
  await emit("tool_check", { when, tool: "level", values: [d.level_a, d.level_b], passed: ok, mode: ok ? null : "pending" });
  S.form = null;
  if (!ok) return openForm("level_retry", null, { run: null, ctx: { first: Math.abs(Math.abs(d.level_a) - Math.abs(d.level_b)), when } });
  home();
}

async function saveLevelRetry(d, ctx) {
  const second = Math.abs(Math.abs(d.level_a) - Math.abs(d.level_b));
  const mode = C.levelCheck(d.level_a, d.level_b, S.rules) ? null : C.levelRepeat(ctx.first, second, S.rules);
  await emit("tool_check", { when: ctx.when, tool: "level", values: [d.level_a, d.level_b], passed: mode === null, mode, retry: true });
  S.form = null;
  S.notices = S.notices || [];
  if (mode === "both_avg") S.notices.push({ text: "영점 오차가 일정합니다. 오늘 모든 지점의 앞뒤를 양 끝 2번 잽니다. 값에 '점검 실패'가 붙습니다" });
  if (mode === "no_judge") S.notices.push({ text: "원인을 알 수 없습니다. 경사는 재더라도 판정에 쓰지 않습니다. 폭, 턱, 노면, 시설은 계속 잽니다" });
  S.draft = null;
  home();
}

// 걷는 순서 -------------------------------------------------------------------
const CLOSED = new Set(["done", "partial", "not_path", "no_entry", "temp_block"]);
const isClosed = (seg) => CLOSED.has(S.st.segStatus[seg]);
// 걷는 순서에서는 '다시 잼'도 지나간 것으로 친다. 다시 잴 목록으로 따로 간다.
const passed = (seg) => isClosed(seg) || S.st.segStatus[seg] === "redo";

function walkList() {
  const walks = S.pack.walks || {};
  if (S.st.routeChoice) return walks[S.st.routeChoice.route] || [];
  const base = walks["11"] || Object.values(walks)[0] || [];
  if (!Object.keys(S.pack.p1_groups || {}).length) return base;
  // 3순위 길을 고르기 전에는 1, 2순위까지만 걷는다
  return base.filter((w) => w.group === "p1" || w.group === "p2");
}

function routeNeeded() {
  const g = S.pack.p1_groups || {};
  if (!Object.keys(g).length || S.st.routeChoice) return false;
  if (Object.values(g).flat().every(isClosed)) return true;
  // 1순위를 건너뛰었어도 1, 2순위를 다 지나면 값이 모자란 채로 묻는다
  const skipped = new Set(S.st.skipped);
  return walkList().every((w) => passed(w.seg) || skipped.has(w.seg));
}

function nextJob() {
  const list = walkList();
  const skipped = new Set(S.st.skipped);
  return list.find((w) => !passed(w.seg) && !skipped.has(w.seg)) || list.find((w) => !passed(w.seg)) || null;
}

function progressLine() {
  const list = walkList();
  const out = [];
  for (const [p, label] of [[1, "1순위"], [2, "2순위"], [3, "3순위"]]) {
    const ss = list.filter((w) => S.pack.segs[w.seg].prio === p);
    if (ss.length) out.push(`${label} ${ss.filter((w) => isClosed(w.seg)).length}/${ss.length}`);
  }
  return out.join(" · ");
}

function mapBox() {
  if (!S.canvas) {
    S.canvas = h("canvas", { "data-t": "map" });
    S.view = new MapView(S.canvas, S.pack, S.image);
  }
  syncView();
  const box = h("div", { class: "mapbox" }, S.canvas, h("div", { class: "mapctl" },
    btn("+", () => S.view.zoomBy(1.6), { "data-t": "zoom-in" }),
    btn("-", () => S.view.zoomBy(1 / 1.6), { "data-t": "zoom-out" }),
    btn("전체", () => S.view.fit(), { class: "mini" })));
  return box;
}

function syncView() {
  if (!S.view) return;
  S.view.status = S.st.segStatus;
  S.view.extraLines = Object.values(S.st.newPaths).map((n) => ({ xy: n.xy }));
  if (S.gps) S.view.gps = { px: lonLatToPx(S.gps.lon, S.gps.lat, S.pack.map), acc: S.gps.acc };
  S.view.draw();
}

function moveScreen() {
  const job = nextJob();
  const redo = S.st.redo.length;
  if (S.view) { S.view.onTap = null; S.view.draft = null; }
  if (!job) {
    if (S.view) { S.view.selected = null; S.view.selFrom = null; }
    return h("div", { class: "screen fill" },
      h("h1", {}, "순서에 있는 구간을 다 했습니다"),
      S.recover && h("div", { class: "info" }, S.recover),
      noticeList(),
      h("p", { class: "small" }, progressLine()),
      mapBox(),
      h("div", { class: "row" }, btn("지도에서 고르기", () => openMap("pick"), { class: "primary", "data-t": "pick" }), btn(`다시 잴 목록 ${redo}`, () => go("redo"), { "data-t": "redo-list" })),
      h("h2", {}, "마치기 전에"),
      h("div", { class: "row" },
        btn("마친 뒤 도구 점검", () => openForm("tool", null, { run: null, ctx: { when: "after" } }), { "data-t": "after-check-end" }),
        btn("백업 파일 저장", downloadBackup, { "data-t": "backup-file-end" })),
      btn("더 보기", () => go("more"), { "data-t": "more" }));
  }
  const seg = segOf(job.seg);
  mapBox();
  S.view.selected = seg;
  S.view.selFrom = job.from;
  if (!S.focusDone) {
    S.focusDone = true;
    S.afterRender = () => { S.view.resize(); S.view.focus(seg.xy, 0.9); };
  }
  const notes = segNotes(seg);
  return h("div", { class: "screen fill" },
    h("div", { class: "spread" }, h("h1", {}, `다음 일: 구간 ${job.seg}`), btn("더 보기", () => go("more"), { class: "mini", "data-t": "more" })),
    S.recover && h("div", { class: "info" }, S.recover),
    shiftBand(),
    noticeList(),
    h("p", { class: "small" }, `${progressLine()} · ${job.move > 3 ? `바퀴를 들고 약 ${Math.round(job.move)} m 이동` : "바로 이어짐"}`),
    h("p", {}, `시작은 ${fromLabel(seg, job.from)}에서, 구간 길이 ${fmt1(seg.len)} m${seg.prio ? `, ${seg.prio}순위` : ""}`),
    notes.map((n) => h("p", { class: "small" }, n)),
    mapBox(),
    btn("도착, 여기서 시작", () => go("start", { seg: job.seg, from: job.from }), { class: "primary", "data-t": "arrive" }),
    h("div", { class: "row" },
      btn("건너뜀", act(async () => { await emit("skip", { seg: job.seg }); S.recover = ""; home(); }), { "data-t": "skip" }),
      btn("다른 구간 고르기", () => openMap("pick"), { "data-t": "pick" })),
    redo ? btn(`다시 잴 목록 ${redo}`, () => go("redo"), { class: "mini", "data-t": "redo-list" }) : null);
}

function segNotes(seg) {
  const out = [];
  if (seg.twin && seg.twin.length) out.push(`옆 갈래(구간 ${seg.twin.join(", ")})와 길이가 비슷합니다. 고른 선을 눈으로 확인하세요`);
  if (seg.road) out.push("차가 다니는 곳입니다. 차를 볼 때는 넣지 말고 나와서 넣으세요");
  if (seg.drawn) out.push(`지도에 없던 그린 선이 ${seg.drawn} m 있습니다`);
  if (seg.stop) out.push(`이 구간은 ${seg.stop.m} m까지만 잽니다`);
  return out;
}

function startScreen() {
  const { seg: id, from, retry, line: lineIn } = S.params;
  const seg = segOf(id);
  const st = S.st.segStatus[id];
  const wet = S.params.wet ?? !!(S.st.day && (S.st.day.weather === "wet" || S.st.day.weather === "rain"));
  const line = lineIn || "main";
  const setLine = (l) => { S.params = { ...S.params, line: l }; render(); };
  const setWet = (v) => { S.params = { ...S.params, wet: v }; render(); };
  const ctx = { seg: id, from, retry: retry || (st ? "again" : ""), line, routeLine: line === "gentle", wet };
  return h("div", { class: "screen" },
    h("h1", {}, `구간 ${id} 시작`),
    noticeList(),
    h("p", {}, `${fromLabel(seg, from)}에서 출발, 지도 길이 ${fmt1(seg.len)} m`),
    segNotes(seg).map((n) => h("div", { class: "info" }, n)),
    h("p", { class: "small" }, "수평계 화면 단위가 °인지 보세요. 진행 방향 쪽이 높으면 +입니다."),
    btn(wet ? "바닥 젖음 (켜짐, 누르면 끔)" : "바닥 젖음이면 누르세요", () => setWet(!wet), { class: `mini${wet ? " on" : ""}`, "data-t": "wet" }),
    seg.prio === 1 && h("div", {},
      h("h2", {}, "폭이 3 m를 넘으면 줄을 고르세요"),
      h("div", { class: "row" }, Object.entries(F.LINES).map(([k, label]) => btn(label, () => setLine(k), { class: `mini${line === k ? " on" : ""}`, "data-line": k })))),
    btn("0으로 맞추고 시작", act(() => beginRun({ ...ctx, start: 0 })), { class: "primary", "data-t": "start-zero" }),
    btn("시작값 넣기", () => openForm("start_value", null, { run: null, ctx }), { "data-t": "start-value" }),
    btn("돌아가기", goBack, { class: "mini" }));
}

async function beginRun(ctx) {
  if (openRun()) {
    S.notices = [{ text: `구간 ${openRun().seg}을 먼저 닫으세요` }];
    return go("measure", {}, { push: false });
  }
  const seg = segOf(ctx.seg);
  const stop = stopFor(seg, ctx.from);
  S.recover = "";
  S.notices = [];
  S.photoDue = null;
  const ev = await emit("run_start", { seg: ctx.seg, from: ctx.from, start: ctx.start ?? 0, line: ctx.line || "main", routeLine: !!ctx.routeLine, retry: ctx.retry || "", wet: !!ctx.wet, planned_stop: stop });
  S.draft = newDraft(S.st.runs[ev.id]);
  S.stack = [];
  S.form = null;
  const plan = C.planMarks(seg.len, fineFor(seg, ctx.from), stop, S.rules, seg.inclines);
  S.flow = plan.length ? [] : ["surface"];
  go("measure", {}, { push: false });
  if (S.flow.length) continueFlow();
}

// 측정 화면 -------------------------------------------------------------------
function newDraft(run) {
  const seg = segOf(run.seg);
  const fine = fineFor(seg, run.from);
  const stop = stopFor(seg, run.from);
  const plan = C.planMarks(seg.len, fine, stop, S.rules, seg.inclines);
  const saved = run.points.map((p) => ({ mark: distOf(run, p), long: p.long, kind: p.kind, added: p.added, target: p.target, n: (p.values || []).length }));
  const pend = C.pendingMarks(plan, saved, seg.len, fine, S.rules, stop);
  const { ahead, behind } = C.splitPending(pend, saved, S.rules);
  const nx = ahead[0] || null;
  const both = S.st.levelMode === "both_avg" || !!(nx && nx.both);
  return {
    id: DB.uid(), run: run.id, target: nx ? nx.mark : null, dist: nx ? nx.mark : null, mark: nx ? markOfDist(run, nx.mark) : null, planned: !!nx, edited: false,
    kind: nx ? nx.kind : "more", both: !!(nx && nx.both), crossNeeded: nx ? nx.cross || S.st.levelMode === "both_avg" : true,
    method: both ? "both" : "one", baseMethod: both ? "both" : "one", sign: null, longs: [], crosses: [], buf: "", phase: nx ? "long" : "long", ten: false,
    queue: ahead.slice(1, 4).map((x) => markOfDist(run, x.mark)), behind: behind.map((x) => markOfDist(run, x.mark)), noMarkPlan: !nx, note: null, clear: null, noLong: false, noCross: false,
  };
}

function afterLong(d) {
  const n = d.longs.length;
  if (d.method === "three") {
    if (n < 3) { d.phase = "long"; return; }
    d.phase = "cross";
    return;
  }
  if (n === 1 && (d.method === "both" || C.needLongRecheck(d.longs[0], d.both, S.rules))) {
    d.method = "both";
    d.phase = "long";
    return;
  }
  d.phase = d.crossNeeded ? "cross" : "done";
}

function afterCross(d) {
  if (d.method !== "three" && d.crosses.length === 1 && C.needCrossRecheck(d.crosses[0], S.rules)) {
    d.phase = "cross";
    return;
  }
  d.phase = "done";
}

function undoLast(d) {
  if (d.phase === "mark") { d.phase = d.prevPhase || "long"; return; }
  if (d.crosses.length && (d.phase === "done" || d.phase === "cross")) {
    d.crosses.pop();
    d.phase = "cross";
    return;
  }
  if (d.phase === "cross" || d.phase === "done") d.phase = "long";
  if (d.longs.length) {
    d.longs.pop();
    if (!d.longs.length) d.method = d.baseMethod;
    d.phase = "long";
  }
}

function measureKey(k) {
  const d = S.draft;
  tap();
  if (k === "del") {
    if (d.buf) d.buf = d.buf.slice(0, -1);
    else undoLast(d);
    render();
    return;
  }
  if (k === "save") { saveDraft(); return; }
  if (k === "ok") {
    if (d.phase === "mark" && d.buf) {
      setMark(d, C.fixedValue(d.buf, 1));
      d.buf = "";
      d.phase = d.prevPhase || "long";
      render();
    }
    return;
  }
  if (d.phase === "done") return;
  if (d.phase === "mark") {
    if (d.buf.length < 5) d.buf += k;
    render();
    return;
  }
  if (d.phase === "long" && !d.sign) {
    S.signHint = true;
    render();
    return;
  }
  S.signHint = false;
  d.buf += k;
  if (d.buf.length >= (d.ten ? 3 : 2)) {
    const v = C.fixedValue(d.buf, 1);
    d.buf = "";
    d.ten = false;
    if (d.phase === "long") {
      d.longs.push(d.sign === "minus" ? -v : v);
      d.sign = null;
      afterLong(d);
    } else {
      d.crosses.push(v);
      afterCross(d);
    }
  }
  render();
}

function setMark(d, mark) {
  const run = openRun();
  d.mark = round1(mark);
  d.dist = round2(C.continued(d.mark, run.start, run.breaks));
  d.edited = true;
}

function draftFirst(run) { return run.points.length === 0; }

function draftFlags(d) {
  const flags = [];
  if (d.method === "three" && d.longs.length === 3 && C.isBoundary(d.longs, S.rules.slope.bound_long)) flags.push("boundary");
  return flags;
}

function photosNeed(d, run) {
  return C.photosRequired({ first: draftFirst(run), method: d.method, crossValues: d.crosses, flags: draftFlags(d) }, S.rules);
}

async function saveDraft() {
  const d = S.draft;
  const run = openRun();
  if (!run || d.phase !== "done" || S.saving) return;
  if (d.mark == null) { S.notices = [{ text: "표시값을 넣어 주세요" }]; d.prevPhase = d.phase; d.phase = "mark"; render(); return; }
  const dist = d.dist ?? C.continued(d.mark, run.start, run.breaks);
  const longVal = C.longRoute(d.longs, d.method);
  const crossVal = C.crossRoute(d.crosses, d.crosses.length === 2 ? "both" : d.method);
  const prev = run.points.map((p) => ({ mark: distOf(run, p), long: p.long, kind: p.kind }));
  const warns = C.checkPoint(prev, { mark: dist, long: longVal, cross: crossVal, values: d.method === "both" ? d.longs : null, kind: d.kind }, S.rules);
  const need = photosNeed(d, run);
  const data = {
    mark: d.mark, dist: round2(dist), breakCount: run.breaks.length, kind: d.kind, method: d.method, values: d.longs, cross: d.crosses,
    flags: draftFlags(d), planned: d.planned && !d.edited, photos_required: need, note: d.note, clear: d.clear, memo: d.memo || "",
    no_long: d.noLong || undefined, no_cross: d.noCross || undefined, added: d.added || undefined, target: d.target ?? undefined,
  };
  let ev;
  S.saving = true;
  try {
    ev = await emit("slope", data, { id: d.id, run: run.id });
  } catch {
    return;
  } finally {
    S.saving = false;
  }
  const taken = photoCountFor(d.id);
  S.photoDue = taken < need ? { of: ev.id, n: need - taken, label: `표시값 ${fmt1(d.mark)}`, run: run.id } : null;
  S.notices = warns.map((w) => ({ text: w.msg, fix: ev.id }));
  const after = S.st.runs[run.id];
  S.draft = newDraft(after);
  S.signHint = false;
  S.recover = "";
  if (after.points.length === 1) {
    const seg = segOf(run.seg);
    const flow = [];
    if (seg.len >= S.rules.width.skip_len && !after.barriers.some((b) => b.type === "width_rep")) flow.push("width");
    if (!after.surfaces.length) flow.push("surface");
    S.flow = flow;
    if (flow.length) return continueFlow();
  }
  render();
}

function continueFlow() {
  const next = S.flow.shift();
  const run = openRun();
  if (!next || !run) { S.form = null; S.stack = []; go("measure", {}, { push: false }); return; }
  if (next === "width") {
    openForm("barrier", "width_rep", { ctx: { flow: true } });
  } else {
    openForm("surface", null, { initial: { changed: false }, ctx: { flow: true } });
  }
}

S.lastSurface = () => {
  const runs = S.st.runOrder.map((id) => S.st.runs[id]).reverse();
  for (const r of runs) if (r.surfaces.length) return r.surfaces[r.surfaces.length - 1];
  return null;
};

function signRow(sign, onSign, ten, onTen) {
  return h("div", { class: "sign" },
    btn("+ 오르막", () => { tap(); onSign("plus"); }, { class: sign === "plus" ? "on" : "", "data-sign": "plus" }),
    btn("- 내리막", () => { tap(); onSign("minus"); }, { class: sign === "minus" ? "on" : "", "data-sign": "minus" }),
    onTen && h("button", { type: "button", class: `adj${ten ? " on" : ""}`, onclick: onTen, "data-t": "ten" }, "10+"));
}

function pad(onKey, okLabel, okEnabled, okKey) {
  const keys = ["7", "8", "9", "4", "5", "6", "1", "2", "3"];
  // 손을 뗄 때(click) 처리한다. 닿는 순간 화면을 바꾸면 손을 뗄 때 새 화면의 같은 자리 버튼이 또 눌린다.
  const mk = (k, label, cls = "", disabled = false) => h("button", {
    type: "button", class: cls, "data-k": k, disabled,
    onclick: () => { if (!disabled) onKey(k); },
  }, label);
  return h("div", { class: "pad" },
    keys.map((k) => mk(k, k)),
    mk("del", "지움", "txt"),
    mk("0", "0"),
    okLabel ? mk(okKey, okLabel, "txt primary", !okEnabled) : mk("noop", "", "txt", true));
}

// 알림은 한 번에 하나만 보인다. 닫으면 다음 것이 나온다.
function noticeList() {
  if (!S.notices || !S.notices.length) return null;
  const n = S.notices[0];
  const more = S.notices.length - 1;
  return h("div", { class: "notice" }, h("span", {}, `${n.text}${more ? ` (알림 ${more}개 더)` : ""}`),
    n.fix ? btn("고침", () => editRecord(n.fix), { "data-t": "notice-fix" }) : null,
    btn("닫기", () => { S.notices.splice(0, 1); render(); }, { "data-t": "notice-close" }));
}

function gpsOffNote(run) {
  if (!S.gps) return null;
  const seg = segOf(run.seg);
  const [x, y] = lonLatToPx(S.gps.lon, S.gps.lat, S.pack.map);
  const d = distToPolyline(x, y, seg.xy) * S.pack.map.mpp;
  if (d > S.rules.check.gps_warn_m && d < 5000) return h("div", { class: "notice" }, `내 위치가 고른 구간에서 약 ${Math.round(d)} m. 구간 번호를 다시 보세요`);
  return null;
}

function measureScreen() {
  const run = openRun();
  if (!run) { setTimeout(home, 0); return h("div", { class: "screen" }); }
  if (!S.draft || S.draft.run !== run.id) S.draft = newDraft(run);
  const d = S.draft;
  const seg = segOf(run.seg);
  const curDist = d.dist ?? (run.points.length ? distOf(run, run.points[run.points.length - 1]) : 0);
  const left = Math.max(0, (stopFor(seg, run.from) ?? seg.len) - curDist);
  const last = run.points[run.points.length - 1];
  const need = photosNeed(d, run);
  const got = photoCountFor(d.id);
  const hint = hintFor(d, run, need);
  const inMark = d.phase === "mark";

  return h("div", { class: "screen fill" },
    h("div", { class: "m-head" },
      h("div", { class: "m-title" }, `구간 ${run.seg}${run.line !== "main" ? ` (${F.LINES[run.line]})` : ""} · 끝까지 약 ${Math.round(left)} m`),
      h("div", { class: "row tight" },
        btn(d.added ? "더 재기 취소" : "여기 더 재기", () => toggleAdd(d, run), { class: `mini${d.added ? " on" : ""}`, "data-t": "add-here", disabled: !d.added && (d.longs.length > 0 || d.crosses.length > 0) }),
        btn(d.clear || d.memo ? "메모 있음" : "메모", () => openForm("point_note"), { class: `mini${d.clear || d.memo ? " on" : ""}`, "data-t": "note" }),
        btn("지도", () => openMap("view"), { class: "mini", "data-t": "map-btn" }),
        btn("더 보기", () => go("more"), { class: "mini", "data-t": "more" }))),
    measureBand(run, d),
    h("div", { class: "m-next" },
      h("button", {
        type: "button", class: `val${inMark ? " active" : ""}`, "data-t": "next-mark",
        onclick: () => { if (d.phase !== "mark") { d.prevPhase = d.phase; d.phase = "mark"; d.buf = ""; render(); } },
      }, h("span", { class: "small" }, "다음"), h("span", { class: `num${d.edited ? "" : " plan"}` }, inMark && d.buf ? fmt1(C.fixedValue(d.buf, 1)) : d.mark == null ? "끝" : `${fmt1(d.mark)} m`), h("span", { class: "small" }, F.POINT_KIND[d.kind] || "")),
      [-0.2, -0.1, 0.1, 0.2].map((x) => h("button", { type: "button", class: "adj", disabled: d.mark == null, "data-adj": x, onclick: () => { setMark(d, d.mark + x); render(); } }, `${x > 0 ? "+" : ""}${x}`))),
    d.queue.length ? h("div", { class: "small" }, `다음 차례: ${d.queue.map(fmt1).join(" > ")}`) : null,
    d.behind && d.behind.length ? h("div", { class: "small" }, `지나친 예정 지점 ${d.behind.map(fmt1).join(", ")}: 구간 끝에서 못 잰 지점으로 셉니다`) : null,
    h("button", { type: "button", class: "m-last", "data-t": "last", disabled: !last, onclick: () => last && editRecord(last.id) },
      last ? `직전 ${fmt1(last.mark)} m  ${last.values.map(signed).join(" / ") || "못 잼"}  ${last.crossValue == null ? "" : fmt1(last.crossValue)}  (눌러서 고침)` : "아직 저장한 지점이 없습니다"),
    h("div", { class: "m-fields" },
      h("div", { class: `m-field${d.phase === "long" ? " active" : ""}`, "data-t": "f-long" }, h("span", {}, "앞뒤"), h("span", { class: "v" }, longText(d))),
      h("div", { class: `m-field${d.phase === "cross" ? " active" : ""}`, "data-t": "f-cross" }, h("span", {}, "좌우"), h("span", { class: "v" }, crossText(d)))),
    h("div", { class: `m-hint${hint.must ? " must" : ""}` }, h("span", {}, hint.text),
      h("span", { class: "row tight" },
        d.phase === "long" && !d.longs.length && btn("거친 곳", () => { d.method = d.method === "three" ? d.baseMethod : "three"; render(); }, { class: d.method === "three" ? "on" : "", "data-t": "rough" }),
        (d.phase === "cross" || (d.phase === "long" && !d.longs.length)) && btn("못 잼", () => skipSlot(d), { "data-t": "skip-slot" }),
        btn(`찍음 ${got}/${need}`, act(async () => { tap(); await emit("photo", { of: d.id }, { run: run.id }); render(); }), { "data-t": "photo" }))),
    d.phase === "done" && draftFlags(d).includes("boundary") && h("div", { class: "row" }, F.BOUNDARY_NOTES.map(([k, label]) => btn(label, () => { d.note = k; render(); }, { class: `mini${d.note === k ? " on" : ""}`, "data-opt": k }))),
    signRow(d.sign, (sg) => { d.sign = sg; S.signHint = false; render(); }, d.ten, () => { d.ten = !d.ten; render(); }),
    S.signHint && h("div", { class: "notice" }, "부호를 먼저 누르세요"),
    pad(measureKey, inMark ? "확인" : "저장", inMark ? !!d.buf : d.phase === "done", inMark ? "ok" : "save"),
    h("div", { class: "tools" },
      btn("턱", () => openForm("barrier", "bump"), { "data-tool": "bump" }),
      btn("틈", () => openForm("barrier", "gap"), { "data-tool": "gap" }),
      btn("폭", () => openForm("barrier", run.barriers.some((b) => b.type === "width_rep") ? "narrow" : "width_rep"), { "data-tool": "width" }),
      btn("노면", () => openForm("surface", null, { initial: { changed: run.surfaces.length > 0 } }), { "data-tool": "surface" }),
      btn("구간 끝", () => openEnd(run), { class: "warn", "data-tool": "end" })));
}

// 1시간마다 역할을 바꾼다(매뉴얼 1장). 윗줄 글자색만으로는 놓치므로 띠로 보인다.
function shiftBand() {
  const p = S.st && S.st.people;
  if (!p || !p.since) return null;
  const m = Math.floor((Date.now() - Date.parse(p.since)) / 60000);
  if (m < S.rules.app.role_minutes) return null;
  return h("div", { class: "notice" }, h("span", {}, `교대 시간입니다 (${p.recorder || "-"} 기록 ${m}분)`), btn("역할 바꾸기", swapRole, { "data-t": "swap-role-band" }));
}

// 측정 화면의 띠는 한 번에 하나만 보인다. 알림, 남은 사진, 위치, 복구 순이다.
function measureBand(run, d) {
  if (S.notices && S.notices.length) return noticeList();
  const shift = shiftBand();
  if (shift) return shift;
  const debts = runPhotoRecords(run).filter((r) => r.got < r.need && r.id !== d.id).sort((a, b) => String(a.at).localeCompare(String(b.at)));
  if (debts.length) {
    const last = debts[debts.length - 1];
    return h("div", { class: "notice" }, h("span", {}, `${last.label} 사진 ${last.need - last.got}장 남음${debts.length > 1 ? ` (외 ${debts.length - 1}곳)` : ""}`),
      btn("찍음", act(async () => { tap(); await emit("photo", { of: last.id }, { run: run.id }); render(); }), { "data-t": "photo-due" }));
  }
  const g = gpsOffNote(run);
  if (g) return g;
  return S.recover ? h("div", { class: "info" }, S.recover) : null;
}

function toggleAdd(d, run) {
  if (d.added) { S.draft = newDraft(run); render(); return; }
  if (d.longs.length || d.crosses.length) return;
  const both = S.st.levelMode === "both_avg";
  Object.assign(d, { added: "here", target: null, kind: "more", planned: false, both: false, crossNeeded: true, method: both ? "both" : "one", baseMethod: both ? "both" : "one", prevPhase: "long", phase: "mark", buf: "", sign: null });
  render();
}

function longText(d) {
  const parts = d.longs.map(signed);
  if (d.phase === "long") {
    const typed = (d.sign === "plus" ? "+" : d.sign === "minus" ? "-" : "") + (d.buf ? (d.buf.length === 1 ? `${d.buf}_` : d.buf) : "");
    parts.push(typed || "_");
  }
  return parts.join(" / ");
}

function crossText(d) {
  const parts = d.crosses.map(fmt1);
  if (d.phase === "cross") parts.push(d.buf ? (d.buf.length === 1 ? `${d.buf}_` : d.buf) : "_");
  if (!parts.length) return d.crossNeeded || d.method === "three" ? "" : "안 잼";
  return parts.join(" / ");
}

function skipSlot(d) {
  d.buf = "";
  d.sign = null;
  if (d.phase === "cross") { d.noCross = true; d.phase = "done"; } else { d.noLong = true; d.phase = d.crossNeeded ? "cross" : "done"; }
  render();
}

function hintFor(d, run, need) {
  const first = draftFirst(run);
  if (d.phase === "mark") return { text: "표시값을 넣고 확인을 누르세요", must: true };
  if (d.method === "three" && d.phase === "long") return { text: `거친 곳 ${["왼쪽", "가운데", "오른쪽"][d.longs.length]} 자리`, must: true };
  if (d.phase === "long" && d.longs.length === 1 && d.method === "both") return { text: "양 끝 바꿔 1번 더, 사진 1장", must: true };
  if (d.phase === "cross" && d.crosses.length === 1) return { text: "좌우도 양 끝 바꿔 1번 더, 사진 1장", must: true };
  if (d.phase === "long" && d.method === "both" && !d.longs.length) return { text: `양 끝 2번${d.both || need ? ", 사진 1장" : ""}`, must: true };
  if (d.phase === "cross" && d.method === "three") return { text: "좌우는 가운데 자리에서 1번", must: true };
  if (d.phase === "done" && draftFlags(d).includes("boundary")) return { text: "경계: 숫자와 바닥 1장, 전체 기울기인지 돌 하나인지 메모", must: true };
  const inFine = fineFor(segOf(run.seg), run.from).some(([a, b]) => (d.dist ?? 0) > a && (d.dist ?? 0) <= b);
  if (d.longs.length && C.needMore(d.longs[0], inFine, S.rules) && d.kind !== "more") return { text: "앞뒤 5 m 더 잴 지점이 생깁니다", must: false };
  if (d.added) return { text: "여기 더 재는 지점 (예정 지점은 그대로 남음)", must: false };
  if (first && !d.noMarkPlan) return { text: "첫 지점: 수평계 숫자와 바닥이 보이게 사진 1장", must: true };
  if (d.mark == null) return { text: "순서에 있는 지점을 다 쟀습니다. 구간 끝으로", must: false };
  if (d.kind === "more") {
    const top = run.points.reduce((m, p) => Math.max(m, distOf(run, p)), -Infinity);
    return { text: d.dist != null && d.dist < top ? "더한 지점: 5 m 뒤로 돌아가 잽니다" : "더한 지점: 5 m 앞에서 잽니다", must: false };
  }
  return { text: "앞뒤를 먼저 불러 주세요", must: false };
}

function editRecord(id) {
  const e = S.events.find((x) => x.id === id);
  if (!e) return;
  const merged = effective(e);
  if (e.kind === "slope") {
    const initial = { mark: merged.mark };
    (merged.values || []).forEach((v, i) => { initial[`long-${i}`] = v; });
    (merged.cross || []).forEach((v, i) => { initial[`cross-${i}`] = v; });
    openForm("slope_edit", null, { run: e.run, initial, fixOf: id, ctx: { longs: (merged.values || []).length, crosses: (merged.cross || []).length } });
  } else if (e.kind === "barrier") {
    openForm("barrier", merged.type, { run: e.run, initial: pickData(merged), fixOf: id });
  } else if (e.kind === "surface") {
    openForm("surface", null, { run: e.run, initial: pickData(merged), fixOf: id });
  } else if (e.kind === "facility") {
    openForm("facility", merged.type, { run: e.run, initial: pickData(merged), fixOf: id });
  } else if (e.kind === "break") {
    openForm("break", null, { run: e.run, initial: pickData(merged), fixOf: id });
  }
}

// 고친 값을 쌓는다. 쌓기 함수와 같은 순서(순서 번호)로 돈다.
function effective(e) {
  let data = { ...e.data };
  for (const x of C.sortEvents(S.events)) {
    if (x.kind !== "fix" || x.data.of !== e.id) continue;
    data = { ...data, ...x.data.data };
    for (const k of x.data.unset || []) delete data[k];
  }
  return data;
}

function pickData(d) {
  const { type, photos_required, unread, breakCount, ...rest } = d;
  return rest;
}

// 구간 끝 ---------------------------------------------------------------------
function openEnd(run) {
  const seg = segOf(run.seg);
  const stop = stopFor(seg, run.from);
  const initial = {};
  if (stop) { initial.planned = true; initial.result = "stopped"; }
  const walked = new Set(Object.values(S.pack.walks || {}).flat().map((w) => w.seg));
  const twin = (seg.twin || []).find((t) => !walked.has(t));
  openForm("run_end", null, { run: run.id, initial, ctx: { twin: twin ?? null, noBarrierAsk: !run.barriers.some((b) => b.type !== "width_rep") } });
}

function endChecks(run, a) {
  const seg = segOf(run.seg);
  const R = S.rules;
  const geo = C.geoFor(seg, run.from);
  const trial = { ...run, end: a.end ?? run.end, result: a.result ?? run.result, no_barrier: a.no_barrier ?? run.no_barrier };
  const out = { warns: [], missing: C.runMissing(trial, geo, R) };
  const measured = trial.end != null ? C.continued(trial.end, run.start, run.breaks) : null;
  if (a.result === "ok" && measured != null && C.lengthMismatch(measured, seg.len, R)) {
    out.warns.push(`길이: 잰 값 ${fmt1(measured)} m, 지도 ${fmt1(seg.len)} m. 구간이 맞는지 보세요`);
    out.mismatch = true;
  }
  const left = C.leftMarks(trial, geo, R);
  if (left.length) out.warns.push(`아직 안 잰 지점 ${left.length}곳: ${left.slice(0, 4).map((p) => fmt1(markOfDist(run, p.mark))).join(", ")}`);
  return out;
}

const MISSING_LABEL = F.MISSING_LABEL;

// 사진 셈은 기록마다 요구와 찍음을 비교한다. 시설 사진은 구간 셈에 넣지 않는다.
function runPhotoRecords(run) {
  const recs = [];
  for (const p of run.points) recs.push({ id: p.id, at: p.at, need: p.photos_required || 0, label: `표시값 ${fmt1(p.mark)}` });
  for (const b of run.barriers) recs.push({ id: b.id, at: b.at, need: b.photos_required || 0, label: `${(F.BARRIERS[b.type] || {}).label || b.type} ${fmt1(b.mark)}` });
  for (const b of run.surfaces) recs.push({ id: b.id, at: b.at, need: b.photos_required || 0, label: `노면 ${fmt1(b.mark)}` });
  for (const f of S.st.facilities) if (f.run === run.id) recs.push({ id: f.id, at: f.at, need: f.photos_required || 0, label: `시설 ${(F.FACILITIES[f.type] || {}).label || f.type}`, fac: true });
  for (const m of S.st.mapChecks) if (m.run === run.id) recs.push({ id: m.id, at: m.at, need: m.photos_required || 0, label: "지도 표시 확인", fac: true });
  return recs.map((r) => ({ ...r, got: photoCountFor(r.id) }));
}

function photoSummary(run) {
  const recs = runPhotoRecords(run).filter((r) => !r.fac);
  return {
    need: recs.reduce((n, r) => n + r.need, 0),
    got: recs.reduce((n, r) => n + Math.min(r.got, r.need), 0),
    short: recs.filter((r) => r.got < r.need),
  };
}

function endReview(form) {
  const run = S.st.runs[form.run];
  const chk = endChecks(run, form.answers);
  const up = run.points.filter((p) => p.long != null && p.long > 0).length;
  const down = run.points.filter((p) => p.long != null && p.long < 0).length;
  const ph = photoSummary(run);
  const extra = form.ctx.extraMissing || [];
  const missing = [...new Set([...chk.missing, ...extra])];
  return h("div", { class: "panel" },
    chk.warns.map((w) => h("div", { class: "notice" }, w)),
    h("div", { class: "info" },
      h("div", {}, `잰 지점 ${run.points.length}곳: 오르막 ${up}, 내리막 ${down}. 방향이 맞나요`),
      h("div", {}, `사진: 요구 ${ph.need}장, 찍음 ${ph.got}장${ph.short.length ? `. 모자람: ${ph.short.slice(0, 4).map((r) => `${r.label} ${r.need - r.got}장`).join(", ")}` : ""}`),
      h("div", {}, `못 잰 항목: ${missing.length ? missing.map((m) => MISSING_LABEL[m] || m).join(", ") : "없음"}`)),
    h("div", { class: "row" },
      btn("못 잰 것 있음", () => { form.ctx.extraMissing = extra.includes("other") ? extra.filter((x) => x !== "other") : [...extra, "other"]; render(); }, { class: `mini${extra.includes("other") ? " on" : ""}`, "data-t": "missing-other" }),
      btn("지금 고침", () => { S.form = null; goBack(); }, { class: "mini", "data-t": "fix-now" })),
    chk.mismatch && btn("다시 잴 목록에 넣고 닫기", act(() => closeRun(form, cleanAnswers(form), true)), { class: "warn", "data-t": "close-redo" }),
    btn("닫고 다음 구간으로", act(() => closeRun(form, cleanAnswers(form), false)), { class: "primary", "data-t": "close-run" }));
}

async function closeRun(form, data, redo) {
  const run = S.st.runs[form.run];
  const chk = endChecks(run, form.answers);
  const missing = [...new Set([...chk.missing, ...(form.ctx.extraMissing || [])])];
  await flushTrack();
  await emit("run_end", {
    end: data.end, result: data.result, reason: data.reason || null, memo: data.memo || "", planned: !!form.answers.planned, missing,
    no_barrier: data.no_barrier || null, twin: data.twin ? { seg: form.ctx.twin, result: data.twin } : null,
  }, { id: form.id, run: run.id });
  if (redo) await emit("redo", { seg: run.seg, why: "length" });
  S.form = null;
  S.draft = null;
  S.notices = [];
  S.flow = [];
  S.photoDue = null;
  syncSoon();
  const segNow = segOf(run.seg);
  const others = { walk: "gentle", gentle: "walk" };
  const hasOther = S.st.runOrder.some((id) => S.st.runs[id].seg === run.seg && S.st.runs[id].line === others[run.line]);
  if (others[run.line] && !hasOther) {
    S.stack = [];
    S.notices = [{ text: `폭이 3 m를 넘는 구간입니다. 다른 줄(${F.LINES[others[run.line]]})을 반대로 걸으며 이어서 재세요` }];
    return go("start", { seg: run.seg, from: run.from === segNow.a ? segNow.b : segNow.a, line: others[run.line], retry: "line" }, { push: false });
  }
  if (S.afterClose === "draw") { S.afterClose = null; return openMap("draw"); }
  home();
}

// 3순위 고르기 -----------------------------------------------------------------
function groupStats(segIds) {
  const vals = [];
  for (const id of S.st.runOrder) {
    const r = S.st.runs[id];
    if (!segIds.includes(r.seg)) continue;
    if (r.line !== "main" && !r.routeLine) continue;
    for (const p of r.points) if (p.long != null) vals.push(Math.abs(p.long));
  }
  if (!vals.length) return { n: 0 };
  const sorted = [...vals].sort((a, b) => a - b);
  return { n: vals.length, max: sorted[sorted.length - 1], med: sorted[Math.floor(sorted.length / 2)], over: vals.filter((v) => C.atLeast(v, S.rules.slope.bound_long[0])).length };
}

function routeScreen() {
  const g = S.pack.p1_groups;
  const rows = Object.entries(g).map(([k, ids]) => {
    const s = groupStats(ids);
    return h("tr", {}, h("th", {}, `${k}번`), h("td", {}, s.n ? `${s.n}곳` : "값 없음"), h("td", {}, s.n ? `${fmt1(s.max)}°` : "-"), h("td", {}, s.n ? `${fmt1(s.med)}°` : "-"), h("td", {}, s.n ? `${s.over}곳` : "-"));
  });
  const pick = S.routePick;
  const choose = (route) => { S.routePick = route; render(); };
  const save = act(async (why) => {
    await emit("route_choice", { route: S.routePick, why, stats: Object.fromEntries(Object.entries(g).map(([k, ids]) => [k, groupStats(ids)])) });
    S.routePick = null;
    home();
  });
  return h("div", { class: "screen" },
    h("h1", {}, "3순위 길 고르기"),
    h("p", { class: "small" }, "1순위 값을 보고 사람이 고릅니다. 11번이 4.7° 이하면 11번 길, 11번이 4.8° 이상이고 10번이 4.7° 이하면 10번 길, 둘 다 넘으면 정문 쪽입니다."),
    h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "길"), h("th", {}, "지점"), h("th", {}, "최대"), h("th", {}, "중앙"), h("th", {}, "4.8° 이상"))), h("tbody", {}, rows)),
    !pick && btn("11번 길", () => choose("11"), { class: "primary", "data-t": "route-11" }),
    !pick && btn("10번 길", () => choose("10"), { class: "primary", "data-t": "route-10" }),
    !pick && btn("정문 쪽 (안쪽 길은 그만)", () => choose("gate"), { "data-t": "route-gate" }),
    pick && h("h2", {}, "고른 이유"),
    pick && h("div", { class: "options" },
      btn("값 기준대로", () => save("value"), { "data-opt": "value" }),
      btn("값이 기준에 가까워 사람이 판단", () => save("judged"), { "data-opt": "judged" }),
      btn("현장 사정 (사람, 공사 등)", () => save("site"), { "data-opt": "site" })),
    pick && btn("다시 고르기", () => choose(null), { class: "mini" }));
}

// 지도 화면 --------------------------------------------------------------------
function openMap(mode, changeRun = null) {
  S.changeRun = changeRun;
  S.mapMode = mode;
  S.mapSel = null;
  S.mapList = false;
  S.drawXy = [];
  go("map");
}

function segRow(id) {
  const s = S.pack.segs[id];
  const st = S.st.segStatus[id];
  return btn(`구간 ${id} · ${fmt1(s.len)} m${s.prio ? ` · ${s.prio}순위` : ""}${st ? ` · ${F.STATUS_LABEL[st] || st}` : ""}`, () => selectSeg(id), { "data-seg": id });
}

function selectSeg(id) {
  S.mapSel = { seg: id };
  S.mapList = false;
  const s = S.pack.segs[id];
  S.view.selected = s;
  S.view.selFrom = null;
  S.view.focus(s.xy, 1.5);
  render();
}

function mapScreen() {
  mapBox();
  const v = S.view;
  v.selected = S.mapSel ? S.pack.segs[S.mapSel.seg] : (openRun() && S.mapMode === "view" ? segOf(openRun().seg) : null);
  v.selFrom = openRun() && S.mapMode === "view" ? openRun().from : null;
  v.draft = S.mapMode === "draw" ? S.drawXy : null;
  v.onTap = S.mapMode === "view" ? null : (x, y) => {
    if (S.mapMode === "draw") {
      const [mx, my] = v.toMap(x, y);
      S.drawXy = [...S.drawXy, Math.round(mx * 10) / 10, Math.round(my * 10) / 10];
      v.draft = S.drawXy;
      v.draw();
      render();
      return;
    }
    if (v.k < 1.2) { v.zoomBy(1.6 / v.k, x, y); return; }
    const c = v.candidates(x, y);
    if (c.length === 1) selectSeg(c[0]);
    else if (c.length > 1) { S.mapCands = c; S.mapSel = null; S.view.selected = null; v.draw(); render(); }
  };
  if (!S.focusDone) {
    S.focusDone = true;
    S.afterRender = () => { v.resize(); if (v.selected) v.focus(v.selected.xy, 1.2); };
  }
  const kids = [
    h("div", { class: "spread" }, h("h1", {}, { pick: "구간 고르기", change: "구간 바꾸기", view: "지도", draw: "새 길 그리기" }[S.mapMode]), btn("닫기", () => { S.mapCands = null; goBack(); }, { class: "mini", "data-t": "map-close" })),
    mapBox(),
  ];
  if (S.mapMode === "draw") {
    kids.push(h("p", { class: "small" }, `양 끝과 꺾이는 곳을 2~4점 찍으세요. ${S.drawXy.length / 2}점`));
    kids.push(h("div", { class: "row" },
      btn("되돌리기", () => { S.drawXy = S.drawXy.slice(0, -2); v.draft = S.drawXy; v.draw(); render(); }, { "data-t": "draw-undo" }),
      btn("완료", act(() => finishDraw()), { class: "primary", disabled: S.drawXy.length < 4, "data-t": "draw-done" })));
    return h("div", { class: "screen fill" }, kids);
  }
  if (S.mapMode === "view") return h("div", { class: "screen fill" }, kids);
  if (S.mapSel) {
    const s = S.pack.segs[S.mapSel.seg];
    const pick = act(async (from) => {
      if (S.mapMode === "change") {
        const run = S.changeRun ? S.st.runs[S.changeRun] : openRun();
        await emit("run_edit", { changes: { seg: s.seg, from }, prev_seg: run.seg, why: "wrong_seg" }, { run: run.id });
        S.draft = null;
        S.mapCands = null;
        if (S.changeRun) {
          // 기록 목록에서 왔다. 옛 구간을 담은 고치기 화면은 건너뛰고 목록으로 돌아간다.
          S.changeRun = null;
          S.form = null;
          S.stack.pop();
        }
        return goBack();
      }
      S.mapCands = null;
      go("start", { seg: s.seg, from });
    });
    kids.push(h("p", {}, `구간 ${s.seg}, ${fmt1(s.len)} m. 어디서 출발하나요`));
    kids.push(h("div", { class: "row" }, btn("A에서 출발", () => pick(s.a), { class: "primary", "data-from": s.a }), btn("B에서 출발", () => pick(s.b), { class: "primary", "data-from": s.b })));
    kids.push(btn("다른 구간", () => { S.mapSel = null; v.selected = null; v.draw(); render(); }, { class: "mini" }));
    return h("div", { class: "screen fill" }, kids);
  }
  if (S.mapCands && S.mapCands.length) kids.push(h("div", { class: "cands" }, S.mapCands.map(segRow)));
  else if (!S.mapList) kids.push(h("p", { class: "small" }, "선을 누르세요. 멀리서 누르면 확대됩니다."));
  if (S.mapList) {
    const ids = S.pack.segs.filter((s) => (v.onlyRanked ? s.prio : true)).map((s) => s.seg);
    kids.push(h("div", { class: "cands" }, ids.map(segRow)));
  }
  kids.push(h("div", { class: "row" },
    btn(S.mapList ? "목록 닫기" : "목록으로 고르기", () => { S.mapList = !S.mapList; render(); }, { class: "mini", "data-t": "list-all" }),
    btn(v.onlyRanked ? "모든 구간" : "순위 구간만", () => { v.onlyRanked = !v.onlyRanked; render(); }, { class: "mini", "data-t": "all-segs" }),
    btn("새 길", () => { S.mapMode = "draw"; S.drawXy = []; S.mapCands = null; render(); }, { class: "mini", "data-t": "new-path" })));
  return h("div", { class: "screen fill" }, kids);
}

async function finishDraw() {
  const xy = S.drawXy;
  const mpp = S.pack.map.mpp;
  let len = 0;
  for (let i = 0; i + 3 < xy.length; i += 2) len += Math.hypot(xy[i + 2] - xy[i], xy[i + 3] - xy[i + 1]) * mpp;
  // 폰마다 N1이 겹치지 않게 폰 표시를 붙인다
  const no = `N${Object.keys(S.st.newPaths).length + 1}-${S.dev.slice(0, 4)}`;
  const near = (x, y) => {
    let best = null;
    for (const [id, p] of Object.entries(S.pack.nodes)) {
      const d = Math.hypot(p[0] - x, p[1] - y) * mpp;
      if (!best || d < best.d) best = { node: Number(id), d };
    }
    return best && best.d <= 15 ? { node: best.node, m: round1(best.d) } : null;
  };
  await emit("new_path", { no, xy, len: round2(len), end_a: near(xy[0], xy[1]), end_b: near(xy[xy.length - 2], xy[xy.length - 1]) });
  S.drawXy = [];
  S.view.draft = null;
  S.stack = [];
  const run = openRun();
  if (S.newPathFor && run && run.id === S.newPathFor) {
    // 잰 지점을 새 길로 옮긴다. 표시값은 걸은 거리 그대로라 값은 안 바뀐다. 옛 선에는 지점 없는 '길 아님'을 남긴다.
    S.newPathFor = null;
    const old = { seg: run.seg, from: run.from };
    await emit("run_edit", { changes: { seg: no, from: `${no}a` }, prev_seg: old.seg, why: "new_path" }, { run: run.id });
    const mark = await emit("run_start", { seg: old.seg, from: old.from, start: 0, line: "main", routeLine: false, retry: "not_path", wet: false, planned_stop: null });
    await emit("run_end", { end: null, result: "not_path", reason: null, memo: `새 길 ${no}로 옮김`, planned: false, missing: [] }, { run: mark.id });
    S.draft = null;
    return go("measure", {}, { push: false });
  }
  S.newPathFor = null;
  go("start", { seg: no, from: `${no}a` }, { push: false });
}

// 재는 중에 새 길을 그리려 하면 지금 구간을 어떻게 할지 먼저 묻는다
function newPathAskScreen() {
  const run = openRun();
  if (!run) { setTimeout(() => openMap("draw"), 0); return h("div", { class: "screen" }); }
  return h("div", { class: "screen" },
    h("h1", {}, "새 길 그리기"),
    h("p", {}, `지금 구간 ${run.seg}을 재는 중입니다. 어떻게 할까요`),
    btn("잰 지점을 새 길로 옮기기 (지도의 선이 실제 길이 아님)", () => { S.newPathFor = run.id; openMap("draw"); }, { class: "primary", "data-t": "np-move" }),
    btn("지금 구간을 닫고 새 길 재기", () => { S.afterClose = "draw"; openEnd(run); }, { "data-t": "np-close" }),
    btn("취소", goBack, { class: "mini", "data-t": "np-cancel" }));
}

// 더 보기 ----------------------------------------------------------------------
function redoScreen() {
  return h("div", { class: "screen" },
    h("h1", {}, "다시 잴 목록"),
    S.st.redo.length ? h("ul", { class: "plain" }, S.st.redo.map((r) => h("li", {}, btn(`구간 ${r.seg} · ${r.why === "length" ? "길이가 다름" : r.why}`, () => {
      const seg = segOf(r.seg);
      go("start", { seg: r.seg, from: seg.a, retry: "redo" });
    }, { "data-redo": r.seg })))) : h("p", {}, "없습니다."),
    S.st.skipped.length ? h("p", { class: "small" }, `건너뛴 구간: ${S.st.skipped.join(", ")}`) : null,
    btn("돌아가기", goBack));
}

function backupPayload() {
  return {
    format: "bf-backup-1", site: S.pack.site, name: S.pack.name, test: !!S.pack.test, net: S.pack.net, pack: S.pack.hash,
    rules: S.rules.version, app: APP_VERSION, dev: S.dev, at: nowIso(), count: S.events.length, events: S.events,
  };
}

function backupName() {
  const d = new Date();
  const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}_${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}`;
  return `bf_${S.pack.site}_${stamp}_${S.events.length}.txt`;
}

async function downloadBackup() {
  await flushTrack();
  const blob = new Blob([JSON.stringify(backupPayload())], { type: "text/plain" });
  const a = h("a", { href: URL.createObjectURL(blob), download: backupName() });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 30000);
  S.lastBackup = nowIso();
  await DB.setMeta("lastBackup", S.lastBackup);
  render();
}

async function shareBackup() {
  await flushTrack();
  const file = new File([JSON.stringify(backupPayload())], backupName(), { type: "text/plain" });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: "측정 백업" });
      S.lastShared = nowIso();
      await DB.setMeta("lastShared", S.lastShared);
      S.msg = `보냄 ${clock(S.lastShared)}. 받은 폰에서 ${S.events.length}건인지 확인하세요`;
    } catch (e) {
      S.msg = e.name === "AbortError" ? "보내기를 취소했습니다" : `보내기 실패: ${e.message}`;
    }
  } else {
    S.msg = "이 폰은 바로 보내기가 안 됩니다. 파일로 내려받아 옮기세요";
    await downloadBackup();
  }
  render();
}

const swapRole = act(async () => {
  const p = S.st.people;
  await emit("role", { measurer: p.recorder, recorder: p.measurer });
  syncSoon();
  // 폰이 한 대라 보낼 곳이 없다. 폰에 파일로 남기고, 통신되면 데이터베이스로 사본이 간다.
  await downloadBackup();
});

function moreScreen() {
  const run = openRun();
  const section = (title, ...items) => [h("h2", {}, title), h("div", { class: "options grid" }, items)];
  return h("div", { class: "screen" },
    h("div", { class: "spread" }, h("h1", {}, "더 보기"), btn("닫기", goBack, { class: "mini", "data-t": "more-close" })),
    S.msg && h("div", { class: "notice" }, S.msg),
    run && section("지금 구간",
      btn("끊김", () => openForm("break"), { "data-t": "break" }),
      btn("구간 바꾸기", () => openMap("change"), { "data-t": "change-seg" })),
    h("h2", {}, "장벽과 상태"),
    h("div", { class: "options grid" }, Object.entries(F.BARRIERS).filter(([k]) => !["bump", "gap", "width_rep"].includes(k)).map(([k, d]) => btn(d.label, () => openForm("barrier", k), { "data-barrier": k, class: "mini" }))),
    h("h2", {}, "시설"),
    h("div", { class: "options grid" }, Object.entries(F.FACILITIES).map(([k, d]) => btn(d.label, () => openForm("facility", k), { "data-fac": k, class: "mini" }))),
    h("div", { class: "row" }, btn("지도 표시 확인", () => openForm("map_check"), { class: "mini", "data-t": "map-check" }), btn("새 길", () => (run ? go("newpath_ask") : openMap("draw")), { class: "mini", "data-t": "new-path-more" })),
    h("h2", {}, "역할과 백업"),
    btn("역할 바꾸고 백업 파일 저장", swapRole, { class: "primary", "data-t": "swap-role" }),
    h("p", { class: "small" }, `기록 ${S.events.length}건. 파일 저장 ${clock(S.lastBackup)}, 보낸 시각 ${clock(S.lastShared)}`),
    h("div", { class: "row" }, btn("백업 파일 저장", downloadBackup, { "data-t": "backup-file" }), btn("백업 보내기", shareBackup, { "data-t": "backup-share" })),
    h("p", { class: "small" }, "다른 폰에 넣어 이어 쓰거나 기록을 합칠 때 백업 파일을 고르세요."),
    restoreInput(),
    h("h2", {}, "데이터베이스"),
    h("p", { class: "small" }, Sync.isConfigured() ? `${S.user ? "로그인됨" : "로그인 안 됨"}. 전송 대기 ${S.pendingN}건, 마지막 전송 ${clock(S.lastSent)}${S.syncError ? `. ${S.syncError}` : ""}` : "자료 파일에 데이터베이스 정보가 없습니다"),
    Sync.isConfigured() && h("div", { class: "row" },
      S.user ? btn("지금 보내기", syncNow, { "data-t": "sync-now" }) : btn("로그인", () => go("login"), { "data-t": "go-login" }),
      S.user && btn("로그아웃", async () => { await Sync.logout(); S.user = null; render(); }, { class: "mini", "data-t": "logout" })),
    h("h2", {}, "도구 다시 점검"),
    h("div", { class: "options grid" },
      btn("수평계 떨어뜨림", () => openForm("level", null, { run: null, ctx: { when: "drop" } }), { class: "mini", "data-t": "recheck-level" }),
      btn("낮 각도기 비교", () => openForm("angle", null, { run: null }), { class: "mini", "data-t": "angle" }),
      btn("마친 뒤 점검", () => openForm("tool", null, { run: null, ctx: { when: "after" } }), { class: "mini", "data-t": "after-check" })),
    h("h2", {}, "기록"),
    btn("기록 목록과 고치기", () => go("records"), { "data-t": "records" }),
    btn(`다시 잴 목록 ${S.st.redo.length}`, () => go("redo"), { "data-t": "redo-list" }),
    btn("이 폰 점검", () => go("device"), { "data-t": "device" }),
    Object.keys(S.pack.p1_groups || {}).length ? btn(S.st.routeChoice ? `3순위 다시 고르기 (지금 ${S.st.routeChoice.route === "gate" ? "정문 쪽" : `${S.st.routeChoice.route}번 길`})` : "3순위 길 고르기", () => go("route"), { "data-t": "route-again" }) : null,
    h("h2", {}, "다른 자료 넣기"),
    h("p", { class: "small" }, `지금 자료: ${S.pack.name}${S.pack.test ? " (시험 자료)" : ""}. 다른 대상지 자료를 넣어도 이 기록은 폰에 그대로 남습니다.`),
    packInput(),
    h("p", { class: "small" }, "13 mm 미만의 턱은 기록하지 않았고, 13 mm 이상도 걸으며 찾은 것만 적었습니다."));
}

function recordsScreen() {
  const items = [];
  for (const id of [...S.st.runOrder].reverse()) {
    const r = S.st.runs[id];
    items.push(btn(`구간 ${r.seg}${r.closed ? ` · ${F.labelOf(F.RESULTS, r.result)}` : " · 재는 중"} · 시작값 ${fmt1(r.start)} · 끝값 ${fmt1(r.end)} (눌러서 고침)`, () => openRunFix(r), { class: "mini on", "data-run": r.id }));
    for (const b of r.breaks) items.push(btn(`끊김 ${fmt1(b.orig)} → ${fmt1(b.now)}${b.rev > 1 ? " (고침)" : ""}`, () => editRecord(b.id), { class: "mini", "data-rec": b.id }));
    for (const p of r.points) {
      items.push(btn(`${fmt1(p.mark)} m ${p.values.map(signed).join(" / ") || "못 잼"} 좌우 ${fmt1(p.crossValue)}${p.flags.length ? ` (${p.flags.join(", ")})` : ""}${p.rev > 1 ? " (고침)" : ""}`, () => editRecord(p.id), { class: "mini", "data-rec": p.id }));
    }
    for (const b of r.barriers) items.push(btn(`${(F.BARRIERS[b.type] || {}).label || b.type} ${fmt1(b.mark)} m 값 ${b.value ?? "못 잼"}${b.rev > 1 ? " (고침)" : ""}`, () => editRecord(b.id), { class: "mini", "data-rec": b.id }));
    for (const b of r.surfaces) items.push(btn(`노면 ${fmt1(b.mark)} m ${F.labelOf(F.MATERIALS, b.material)} ${F.labelOf(F.GRADES, b.grade)}${b.rev > 1 ? " (고침)" : ""}`, () => editRecord(b.id), { class: "mini", "data-rec": b.id }));
  }
  for (const f of S.st.facilities) items.push(btn(`시설 ${(F.FACILITIES[f.type] || {}).label || f.type}`, () => editRecord(f.id), { class: "mini", "data-rec": f.id }));
  return h("div", { class: "screen" },
    h("div", { class: "spread" }, h("h1", {}, "기록 목록"), btn("닫기", goBack, { class: "mini" })),
    items.length ? items : h("p", {}, "기록이 없습니다."));
}

function deviceScreen() {
  const rows = [
    ["앱 판", `${APP_VERSION} (실행 ${S.sw.running || "-"}, 받은 판 ${S.sw.latest || "-"})`],
    ["자료 판", `${S.pack ? S.pack.hash : "-"} / 연결망 ${S.pack ? S.pack.net : "-"}${S.pack && S.pack.test ? " / 시험 자료" : ""}`],
    ["규칙표", S.rules ? S.rules.version : "-"],
    ["폰 표시", S.dev],
    ["보안 주소", window.isSecureContext ? "예" : "아니오"],
    ["서비스 워커", navigator.serviceWorker && navigator.serviceWorker.controller ? "됨" : "아직 안 됨"],
    ["저장 유지", S.persist === null ? "확인 전" : S.persist ? "허용됨" : "허용 안 됨 (설치하면 달라질 수 있음)"],
    ["위치", S.gpsError || (S.gps ? `수신 ±${Math.round(S.gps.acc)} m` : "기다리는 중")],
    ["화면 켜짐", S.wake === "on" ? "유지 중" : S.wake === "off" ? "안 됨" : "확인 전"],
    ["바로 보내기", navigator.canShare ? "됨" : "안 됨"],
    ["통신", navigator.onLine ? "연결됨" : "끊김"],
    ["브라우저", navigator.userAgent],
  ];
  return h("div", { class: "screen" },
    h("div", { class: "spread" }, h("h1", {}, "이 폰 점검"), btn("닫기", goBack, { class: "mini" })),
    h("table", {}, h("tbody", {}, rows.map(([a, b]) => h("tr", {}, h("th", {}, a), h("td", { "data-dev": a }, b))))),
    btn("새 판 확인", async () => {
      const reg = await navigator.serviceWorker?.getRegistration();
      if (reg) await reg.update();
      askVersions();
      S.msg = "확인했습니다";
      render();
    }, { "data-t": "check-update" }),
    S.sw.latest && S.sw.running && S.sw.latest !== S.sw.running && btn("새 판 받기", () => {
      navigator.serviceWorker.controller.postMessage("use-latest");
    }, { class: "warn", "data-t": "use-latest" }),
    h("p", { class: "small" }, "측정 전에 앱 판과 자료 판을 확인하세요. 새 판은 이 버튼을 눌렀을 때만 바뀝니다."),
    S.msg && h("div", { class: "info" }, S.msg));
}

function homeScreen() {
  setTimeout(home, 0);
  return h("div", { class: "screen" });
}

const SCREENS = {
  pack: packScreen, login: loginScreen, form: formScreen, phone_setup: phoneSetupScreen, move: moveScreen, start: startScreen,
  measure: measureScreen, route: routeScreen, map: mapScreen, more: moreScreen, redo: redoScreen, records: recordsScreen, device: deviceScreen,
  newpath_ask: newPathAskScreen,
};

// 전송 --------------------------------------------------------------------------
let syncTimer = null;
function scheduleSync() {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncNow, 1500);
}
const syncSoon = () => { clearTimeout(syncTimer); syncTimer = setTimeout(syncNow, 200); };

async function syncNow() {
  if (!S.pack || S.switching || !Sync.isConfigured()) return;
  try {
    S.user = await Sync.currentUser();
    if (!S.user) return;
    const r = await Sync.pushPending();
    if (!r.skipped) S.syncError = "";
    if (r.sent) S.lastSent = nowIso();
  } catch (e) {
    S.syncError = e.message;
    S.user = await Sync.currentUser().catch(() => S.user);
    if (S.screen === "more") render();
  }
  S.pendingN = await DB.pendingCount();
  refreshTop();
}

async function pullDb() {
  S.msg = "";
  try {
    const r = await Sync.pullAll(S.pack.site, sameSite);
    await reloadEvents();
    setRecover(`데이터베이스에서 ${r.added}건 받음`);
    S.msg = "";
    S.draft = null;
    home();
  } catch (e) {
    S.msg = e.message;
    render();
  }
}

// 위치, 화면 켜짐, 브라우저 사고 막기 ---------------------------------------------
let watchId = null;
let lastTrack = 0;
let trackBuf = [];
function startGps(force = false) {
  if (!navigator.geolocation) { S.gpsError = "이 브라우저는 위치를 못 씁니다"; return; }
  if (watchId !== null) {
    if (!force) return;
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }
  S.gpsError = "";
  watchId = navigator.geolocation.watchPosition((p) => {
    S.gps = { lon: p.coords.longitude, lat: p.coords.latitude, acc: p.coords.accuracy, t: new Date(p.timestamp).toISOString() };
    S.gpsError = "";
    const now = Date.now();
    if (openRun() && now - lastTrack >= S.rules.app.track_s * 1000) {
      lastTrack = now;
      trackBuf.push([round6(S.gps.lon), round6(S.gps.lat), Math.round(S.gps.acc), S.gps.t]);
    }
    refreshTop();
    if (S.view) syncView();
    if (S.screen === "phone_setup") render();
  }, (e) => {
    S.gpsError = e.code === 1 ? "위치 권한 거부됨" : e.message || "위치 오류";
    if (e.code === 1 && watchId !== null) { navigator.geolocation.clearWatch(watchId); watchId = null; }
    refreshTop();
    if (S.screen === "phone_setup") render();
  }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 });
}
const round6 = (x) => Math.round(x * 1e6) / 1e6;

async function flushTrack() {
  if (!trackBuf.length || !S.pack || S.switching) return;
  const pts = trackBuf;
  trackBuf = [];
  const run = openRun();
  try {
    await emit("track", { pts }, { run: run ? run.id : undefined });
  } catch {
    trackBuf = [...pts, ...trackBuf];
  }
}

let wakeLock = null;
async function keepAwake() {
  if (!("wakeLock" in navigator)) { S.wake = "off"; return; }
  if (wakeLock || document.visibilityState !== "visible") return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
    S.wake = "on";
    wakeLock.addEventListener("release", () => { wakeLock = null; });
  } catch {
    S.wake = "off";
  }
  refreshTop();
}

function guards() {
  // 뒤로 가기로 앱이 닫히지 않게 한다
  history.pushState({ bf: 1 }, "");
  window.addEventListener("popstate", () => {
    history.pushState({ bf: 1 }, "");
    if (S.screen === "measure" || S.screen === "move") {
      S.notices = [{ text: "측정 중에는 뒤로 가기로 나갈 수 없습니다. 나가려면 홈 버튼을 쓰세요" }];
      render();
    } else if (S.form) {
      S.msg = "입력 중에는 뒤로 가기로 나갈 수 없습니다. 그만두려면 취소를, 앱을 나가려면 홈 버튼을 쓰세요";
      render();
    } else goBack();
  });
  document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState === "visible") {
      keepAwake();
      await reloadFromStore();
    } else {
      flushUi();
      flushTrack();
    }
  });
  document.addEventListener("pointerdown", () => { if (S.wake !== "on") keepAwake(); }, { passive: true });
  window.addEventListener("online", () => { syncSoon(); refreshTop(); });
  setInterval(() => { refreshTop(); }, 30000);
  setInterval(() => { if (S.rules) flushTrack(); }, 60000);
  setInterval(() => { syncNow(); }, 30000);

  try {
    // 다른 창이 5초마다 알린다. 12초 동안 소식이 없거나 닫힌다고 하면 띠를 지운다.
    const ch = new BroadcastChannel("bf-gather");
    let seen = 0;
    const check = () => {
      const other = Date.now() - seen < 12000;
      if (other !== S.other) { S.other = other; render(); }
    };
    ch.onmessage = (m) => {
      if (m.data === "bye") seen = 0;
      else {
        seen = Date.now();
        if (m.data === "hello") ch.postMessage("here");
      }
      check();
    };
    ch.postMessage("hello");
    setInterval(() => { ch.postMessage("ping"); check(); }, 5000);
    window.addEventListener("pagehide", () => ch.postMessage("bye"));
  } catch { /* 없어도 동작한다 */ }

  if (navigator.getBattery) {
    navigator.getBattery().then((b) => {
      const up = () => { S.battery = Math.round(b.level * 100); refreshTop(); };
      up();
      b.addEventListener("levelchange", up);
    }).catch(() => {});
  }
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().then((v) => { S.persist = v; }).catch(() => {});
}

async function reloadFromStore() {
  const before = S.events.length;
  const list = await DB.allEvents();
  if (list.length !== before) {
    S.events = list;
    refold();
    S.pendingN = await DB.pendingCount();
    render();
  }
}

function askVersions() {
  const c = navigator.serviceWorker && navigator.serviceWorker.controller;
  if (c) c.postMessage("versions");
}

async function registerSw() {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  navigator.serviceWorker.addEventListener("message", (e) => {
    if (e.data.type === "versions") { S.sw = e.data; if (S.screen === "device") render(); }
    if (e.data.type === "pinned") location.reload();
  });
  try {
    await navigator.serviceWorker.register("sw.js", { scope: "./" });
    await navigator.serviceWorker.ready;
    setTimeout(askVersions, 500);
  } catch { /* 서비스 워커 없이도 온라인으로는 동작한다 */ }
}

// 시작 ----------------------------------------------------------------------------
// 시작이 실패하면 '불러오는 중'에 멈추지 않고 이유, 다시 열기, 기록 꺼내기를 보인다
function bootFail(e) {
  root.replaceChildren(h("div", { class: "screen", "data-t": "boot-fail" },
    h("h1", {}, "앱을 열지 못했습니다"),
    h("div", { class: "notice" }, String((e && e.message) || e)),
    h("p", {}, "저장된 기록은 폰에 남아 있습니다. 다시 열어 보고, 안 되면 기록을 내려받아 다른 폰에서 이어 쓰세요."),
    btn("다시 열기", () => location.reload(), { class: "primary", "data-t": "boot-reload" }),
    btn("저장된 기록 내려받기", async () => {
      try {
        const events = await DB.rawEvents(DB.currentName());
        const pk = await DB.getPack().catch(() => null);
        const body = { format: "bf-backup-1", site: pk && pk.site, net: pk && pk.net, test: !!(pk && pk.test), app: APP_VERSION, at: nowIso(), count: events.length, events };
        const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(body)], { type: "text/plain" })), download: `bf_rescue_${Date.now()}_${events.length}.txt` });
        document.body.append(a);
        a.click();
        a.remove();
      } catch (err) {
        root.append(h("div", { class: "notice" }, `내려받기도 실패: ${err.message || err}`));
      }
    }, { "data-t": "boot-backup" })));
}

async function boot() {
  try {
    await bootInner();
  } catch (e) {
    bootFail(e);
  }
}

async function bootInner() {
  try {
    await DB.openStore(DB.startName());
  } catch (e) {
    root.replaceChildren(h("div", { class: "band-red" }, `저장소를 열 수 없습니다: ${e.message}`));
    return;
  }
  S.dev = await DB.getDeviceId();
  const stored = await DB.getPack();
  if (stored) await usePack(stored);
  await reloadEvents();
  S.lastBackup = await DB.getMeta("lastBackup");
  S.lastShared = await DB.getMeta("lastShared");
  S.lastSent = await DB.getMeta("lastSentAt");
  S.user = await Sync.currentUser();
  guards();
  keepAwake();
  registerSw();
  if (!S.pack) { go("pack", {}, { push: false }); return; }
  const switched = sessionStorage.getItem("bf-after-switch");
  if (switched) {
    sessionStorage.removeItem("bf-after-switch");
    S.switchNote = switched;
    go("login", {}, { push: false });
    return;
  }
  const ui = await DB.getMeta("ui");
  if (ui) {
    // 저장 직후 앱이 죽었으면 화면 상태가 저장 전 것이다. 이미 저장된 번호의 초안과 입력은 버린다.
    const saved = new Set(S.events.map((e) => e.id));
    S.draft = ui.draft && !saved.has(ui.draft.id) ? ui.draft : null;
    S.form = ui.form && !(saved.has(ui.form.id) && !ui.form.fixOf) ? ui.form : null;
    if (S.form) delete S.form.saving;
    S.flow = ui.flow || [];
    S.photoDue = ui.photoDue || null;
  }
  setRecover();
  // 이미 끝낸 아침 입력이나 날짜가 지난 입력은 되살리지 않는다
  const stale = S.form && (
    (S.form.kind === "day" && S.st.day && S.st.day.date === today())
    || (S.form.kind === "tool" && (S.form.ctx.when || "before") === "before" && toolsDoneToday())
    || (S.form.kind === "level_retry" && !levelPending())
    || (S.form.kind !== "day" && (!S.st.day || S.st.day.date !== today())));
  if (stale) S.form = null;
  if (S.form) {
    S.screen = "form";
    S.stack = openRun() ? [{ screen: "measure", params: {} }] : [];
    render();
  } else home();
  scheduleSync();
}

window.__bf = {
  state: () => S.st,
  events: () => S.events,
  pending: () => S.pendingN,
  draft: () => S.draft,
  syncNow,
};

boot();
