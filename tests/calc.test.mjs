// 계산 규칙 시험. 같은 시험값 파일을 Python(tests/test_evening.py)도 통과한다.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as C from "../docs/js/calc.js";

const cases = JSON.parse(readFileSync(new URL("./calc_cases.json", import.meta.url), "utf8"));
const rules = JSON.parse(readFileSync(new URL("../tools/rules.json", import.meta.url), "utf8"));
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg}: ${a} != ${b}`);

for (const c of cases.long_route) test(`앞뒤 경로 값: ${c.name}`, () => near(C.longRoute(c.values, c.method), c.want, c.name));
for (const c of cases.cross_route) test(`좌우 경로 값: ${c.name}`, () => near(C.crossRoute(c.values, c.method), c.want, c.name));
for (const c of cases.at_least) test(`기준 비교: ${c.name}`, () => assert.equal(C.atLeast(c.value, c.limit), c.want));
for (const c of cases.boundary) test(`경계: ${c.name}`, () => assert.equal(C.isBoundary(c.values, c.limits), c.want));
for (const c of cases.continued) test(`이어 계산: ${c.name}`, () => near(C.continued(c.mark, c.start, c.breaks), c.want, c.name));

for (const c of cases.plan) {
  test(`재는 지점: ${c.name}`, () => {
    const got = C.planMarks(c.len, c.fine, c.stop, rules, c.inclines).map((p) => [p.mark, p.kind, p.both, p.cross]);
    assert.deepEqual(got, c.want);
  });
}

for (const c of cases.pending) {
  test(`남은 지점: ${c.name}`, () => {
    const plan = c.plan.map((m) => ({ mark: m, kind: c.fine.length ? "fine" : "gap", both: false, cross: true }));
    const saved = c.saved.map(([mark, long, kind, added]) => ({ mark, long, kind, added }));
    const got = C.pendingMarks(plan, saved, c.len, c.fine, rules, c.stop ?? null).map((p) => [p.mark, p.kind]);
    assert.deepEqual(got, c.want);
  });
}

for (const c of cases.recheck) {
  test(`양 끝 다시 재기: ${c.name}`, () => assert.equal(C.needLongRecheck(c.long, c.fine_both, rules), c.want));
}

for (const c of cases.check_point) {
  test(`저장 때 검사: ${c.name}`, () => {
    const got = C.checkPoint(c.prev, c.point, rules).map((w) => w.code).sort();
    assert.deepEqual(got, [...c.want].sort());
  });
}

for (const c of cases.check_len) {
  test(`길이 검사: ${c.name}`, () => assert.equal(C.lengthMismatch(c.measured, c.map, rules), c.want));
}

// 사건 쌓기 -----------------------------------------------------------------
const ev = (id, seq, kind, data, extra = {}) => ({ id, seq, kind, at: `2026-11-23T09:${String(seq).padStart(2, "0")}:00+09:00`, dev: "d1", data, ...extra });

test("고친 값은 최신 값으로 보이고 원값이 남는다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("p1", 2, "slope", { mark: 5, values: [2.0], method: "one", cross: [1.0], kind: "gap" }, { run: "r1" }),
    ev("f1", 3, "fix", { of: "p1", data: { values: [-2.0] } }, { run: "r1" }),
  ]);
  const pt = s.runs.r1.points[0];
  assert.deepEqual(pt.values, [-2.0]);
  assert.equal(pt.long, -2.0);
  assert.deepEqual(pt.original.values, [2.0]);
  assert.equal(pt.rev, 2);
});

test("지운 기록은 목록에서 빠지되 사건은 남는다", () => {
  const events = [
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("p1", 2, "slope", { mark: 5, values: [2.0], method: "one", cross: [1.0], kind: "gap" }, { run: "r1" }),
    ev("v1", 3, "void", { of: "p1" }, { run: "r1" }),
  ];
  const s = C.foldEvents(events);
  assert.equal(s.runs.r1.points.length, 0);
  assert.equal(s.eventCount, 3);
});

test("같은 사건을 두 번 받아도 한 건이다", () => {
  const p = ev("p1", 2, "slope", { mark: 5, values: [2.0], method: "one", cross: [1.0], kind: "gap" }, { run: "r1" });
  const s = C.foldEvents([ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }), p, { ...p }]);
  assert.equal(s.runs.r1.points.length, 1);
  assert.equal(s.eventCount, 2);
});

test("순서가 뒤섞여 들어와도 결과가 같다", () => {
  const a = ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 });
  const b = ev("p1", 2, "slope", { mark: 5, values: [2.0], method: "one", cross: [1.0], kind: "gap" }, { run: "r1" });
  const c = ev("f1", 3, "fix", { of: "p1", data: { values: [3.0] } }, { run: "r1" });
  assert.deepEqual(C.foldEvents([c, b, a]).runs.r1.points[0].values, [3.0]);
});

test("구간 끝 사건으로 닫히고 결과가 남는다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("e1", 2, "run_end", { end: 16.2, result: "ok", missing: [] }, { run: "r1" }),
  ]);
  assert.equal(s.runs.r1.closed, true);
  assert.equal(s.runs.r1.end, 16.2);
  assert.equal(s.segStatus[7], "done");
});

test("끝까지 못 감이면 구간 상태가 일부다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("e1", 2, "run_end", { end: 9.5, result: "stopped", missing: [] }, { run: "r1" }),
  ]);
  assert.equal(s.segStatus[7], "partial");
});

test("다시 잴 목록에 넣으면 구간 상태가 다시 잼이다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("e1", 2, "run_end", { end: 16, result: "ok", missing: [] }, { run: "r1" }),
    ev("x1", 3, "redo", { seg: 7, why: "length" }),
  ]);
  assert.equal(s.segStatus[7], "redo");
  assert.deepEqual(s.redo.map((r) => r.seg), [7]);
});

test("역할을 바꾸면 현재 측정자와 기록자가 바뀐다", () => {
  const s = C.foldEvents([
    ev("d1", 1, "day", { site: "x", measurer: "가", recorder: "나" }),
    ev("o1", 2, "role", { measurer: "나", recorder: "가" }),
  ]);
  assert.equal(s.people.measurer, "나");
  assert.equal(s.people.recorder, "가");
  assert.equal(s.people.since, "2026-11-23T09:02:00+09:00");
});

test("사진은 찍은 수를 기록별로 센다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("h1", 2, "photo", { of: "p1" }, { run: "r1" }),
    ev("h2", 3, "photo", { of: "p1" }, { run: "r1" }),
  ]);
  assert.equal(s.photos.p1, 2);
  assert.equal(s.runs.r1.photoCount, 2);
});

test("점검 실패 표시가 그날 경사 지점에 붙는다", () => {
  const s = C.foldEvents([
    ev("t1", 1, "tool_check", { when: "before", tool: "level", values: [1.0, 1.6], passed: false, mode: "both_avg" }),
    ev("r1", 2, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("p1", 3, "slope", { mark: 5, values: [2.0, 2.2], method: "both", cross: [1.0], kind: "gap" }, { run: "r1" }),
  ]);
  assert.equal(s.levelMode, "both_avg");
  assert.ok(s.runs.r1.points[0].flags.includes("tool_fail"));
});

test("세 값이 기준에 걸치면 경계 표시가 붙는다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("p1", 2, "slope", { mark: 5, values: [4.0, 5.0, 4.5], method: "three", cross: [1.0], kind: "gap" }, { run: "r1" }),
  ], rules);
  assert.ok(s.runs.r1.points[0].flags.includes("boundary"));
  assert.equal(s.runs.r1.points[0].long, 4.5);
});

test("사진 요구 수: 구간 첫 지점 1장, 다시 잰 지점 1장", () => {
  assert.equal(C.photosRequired({ first: true, method: "one", cross: [1.0], long: 1.0, flags: [] }, rules), 1);
  assert.equal(C.photosRequired({ first: false, method: "both", cross: [1.0], long: 4.6, flags: [] }, rules), 1);
  assert.equal(C.photosRequired({ first: true, method: "both", cross: [1.0], long: 4.6, flags: [] }, rules), 2);
  assert.equal(C.photosRequired({ first: false, method: "one", cross: [1.0], long: 1.0, flags: [] }, rules), 0);
  assert.equal(C.photosRequired({ first: false, method: "three", cross: [1.0], long: 4.5, flags: ["boundary"] }, rules), 1);
});

test("도구 점검 통과 판단", () => {
  assert.equal(C.levelCheck(1.5, -1.7, rules), true);
  assert.equal(C.levelCheck(1.5, -2.0, rules), false);
  assert.equal(C.levelRepeat(0.5, 0.6, rules), "both_avg");
  assert.equal(C.levelRepeat(0.5, 0.8, rules), "no_judge");
  assert.equal(C.caliperCheck(0.0, 26.6, 0.0, rules), true);
  assert.equal(C.caliperCheck(0.0, 26.8, 0.0, rules), false);
  assert.equal(C.wheelCheck(10.0, rules), true);
  assert.equal(C.wheelCheck(10.4, rules), false);
});

test("고정 소수점 입력", () => {
  assert.equal(C.fixedValue("47", 1), 4.7);
  assert.equal(C.fixedValue("5", 1), 0.5);
  assert.equal(C.fixedValue("123", 1), 12.3);
  assert.equal(C.fixedValue("", 1), null);
  assert.equal(C.fixedValue("23", 0), 23);
});

test("앞뒤는 1번인데 좌우만 두 번 재면 좌우는 평균이다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("p1", 2, "slope", { mark: 5, values: [1.0], method: "one", cross: [2.2, 2.4], kind: "gap" }, { run: "r1" }),
  ]);
  assert.ok(Math.abs(s.runs.r1.points[0].crossValue - 2.3) < 1e-9);
});

test("좌우만 두 번 재도 사진 1장을 요구한다", () => {
  assert.equal(C.photosRequired({ first: false, method: "one", crossValues: [2.2, 2.4], flags: [] }, rules), 1);
});

test("순서 번호가 시각보다 먼저다: 시계가 뒤로 가도 지점이 구간에 붙는다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }, { at: "2026-11-23T09:05:00+09:00", ord: 1000 }),
    ev("p1", 2, "slope", { mark: 5, values: [2.0], method: "one", cross: [1.0], kind: "gap" }, { run: "r1", at: "2026-11-23T09:00:00+09:00", ord: 1001 }),
    ev("e1", 3, "run_end", { end: 10, result: "ok", missing: [] }, { run: "r1", at: "2026-11-23T09:01:00+09:00", ord: 1002 }),
  ]);
  assert.equal(s.runs.r1.points.length, 1);
  assert.equal(s.loose.length, 0);
  assert.equal(s.runs.r1.closed, true);
  assert.equal(s.maxOrd, 1002);
});

test("다음 순서 번호는 지금 시각과 본 것 + 1 중 큰 값", () => {
  assert.equal(C.nextOrd(500, 1000), 1001);
  assert.equal(C.nextOrd(5000, 1000), 5000);
});

test("앞뒤 지점 나누기: 저장한 곳보다 확실히 뒤에 남은 예정 지점은 다음 차례가 아니다", () => {
  const pend = [{ mark: 5, kind: "fine" }, { mark: 8, kind: "fine" }];
  const saved = [{ mark: 2, kind: "fine" }, { mark: 4, kind: "fine" }, { mark: 5.8, kind: "fine" }];
  const r = C.splitPending(pend, saved, rules);
  assert.deepEqual(r.ahead.map((p) => p.mark), [8]);
  assert.deepEqual(r.behind.map((p) => p.mark), [5]);
  const r2 = C.splitPending([{ mark: 5, kind: "fine" }, { mark: 6, kind: "fine" }], [{ mark: 4.4, kind: "fine" }], rules);
  assert.deepEqual(r2.ahead.map((p) => p.mark), [5, 6]);
  const r3 = C.splitPending([{ mark: 10, kind: "more" }, { mark: 25, kind: "gap" }], [{ mark: 15, kind: "gap" }], rules);
  assert.deepEqual(r3.ahead.map((p) => p.mark), [10, 25]);
});

test("경계 표시는 저장값을 믿지 않고 값으로 다시 정한다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("p1", 2, "slope", { mark: 5, values: [4.6, 4.9, 5.0], method: "three", cross: [1.0], kind: "gap", flags: ["boundary"] }, { run: "r1" }),
    ev("f1", 3, "fix", { of: "p1", data: { values: [4.0, 4.1, 4.2] } }, { run: "r1" }),
  ], rules);
  assert.ok(!s.runs.r1.points[0].flags.includes("boundary"), s.runs.r1.points[0].flags);
});

test("고침의 unset 칸은 합친 값에서 빠진다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("b1", 2, "barrier", { type: "bump", mark: 3, value: 20, value2: 19, remain_cm: 12 }, { run: "r1" }),
    ev("f1", 3, "fix", { of: "b1", data: { value: 10 }, unset: ["value2", "remain_cm"] }, { run: "r1" }),
  ]);
  const b = s.runs.r1.barriers[0];
  assert.equal(b.value, 10);
  assert.ok(!("value2" in b) && !("remain_cm" in b), JSON.stringify(b));
});

// 칸 정의 ------------------------------------------------------------------
import * as F from "../docs/js/fields.js";

test("숫자 칸은 모두 '못 잼'처럼 비울 수 있다 (표시값 빼고)", () => {
  const miss = [];
  for (const [name, def] of [...Object.entries(F.BARRIERS), ...Object.entries(F.FACILITIES)]) {
    for (const st of def.steps) if ((st.type === "num" || st.type === "signed") && !st.blank) miss.push(`${name}.${st.key}`);
  }
  assert.deepEqual(miss, []);
});

test("매뉴얼 칸: 대표 폭 둘째 값, 틈 반복 끝, 턱 둘째 도구, 둘째 등급 사진", () => {
  const keys = (d) => d.steps.map((s) => s.key);
  assert.ok(keys(F.BARRIERS.width_rep).includes("value2"));
  assert.ok(keys(F.BARRIERS.gap).includes("repeat") && keys(F.BARRIERS.gap).includes("mark_end"));
  assert.ok(keys(F.BARRIERS.bump).includes("tool2"));
  assert.equal(F.SURFACE.photos({ changed: false, grade2: "bad" }), 1);
  assert.equal(F.SURFACE.photos({ changed: false, grade2: "" }), 0);
  assert.equal(F.UNREADABLE, "못 잼");
});

test("지운 끊김 뒤의 지점은 남은 끊김만 쓴다", () => {
  const pt = (id, seq, mark, bc) => ev(id, seq, "slope", { mark, values: [1.0], method: "one", cross: [1.0], kind: "gap", breakCount: bc }, { run: "r1" });
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("k1", 2, "break", { orig: 20, now: 0 }, { run: "r1" }),
    pt("p1", 3, 5, 1),
    ev("k2", 4, "break", { orig: 10, now: 0 }, { run: "r1" }),
    pt("p2", 5, 3, 2),
    ev("v1", 6, "void", { of: "k1" }, { run: "r1" }),
  ]);
  assert.deepEqual(s.runs.r1.points.map((x) => x.breakCount), [0, 1]);
});

test("닫은 측정을 다른 구간으로 옮기면 옛 구간은 남은 측정의 상태로 돌아간다", () => {
  const s = C.foldEvents([
    ev("r1", 1, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("e1", 2, "run_end", { end: 10, result: "ok", missing: [] }, { run: "r1" }),
    ev("r2", 3, "run_start", { seg: 7, from: 3, start: 0 }),
    ev("e2", 4, "run_end", { end: 2, result: "temp_block", missing: [] }, { run: "r2" }),
    ev("m1", 5, "run_edit", { changes: { seg: 9, from: 4 }, prev_seg: 7, why: "wrong_seg" }, { run: "r2" }),
  ]);
  assert.equal(s.segStatus[7], "done");
  assert.equal(s.segStatus[9], "temp_block");
});
