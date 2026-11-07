// 측정 규칙 계산. 화면과 저장을 모르는 순수 함수만 둔다. 브라우저와 Node 시험이 같은 파일을 읽는다.

const EPS = 1e-9;
const round1 = (x) => Math.round(x * 10) / 10;
const median3ByMagnitude = (values) => [...values].sort((a, b) => Math.abs(a) - Math.abs(b))[1];

export const atLeast = (value, limit) => value >= limit - EPS;
export const inRanges = (x, ranges) => ranges.some(([lo, hi]) => atLeast(x, lo) && atLeast(hi, x));

// 매뉴얼 9장 다: 경로에 넘길 대표값
export function longRoute(values, method) {
  if (!values.length) return null;
  if (method === "both" && values.length >= 2) return (values[0] + values[1]) / 2;
  if (method === "three" && values.length >= 3) return median3ByMagnitude(values);
  return values[0];
}

export function crossRoute(values, method) {
  if (!values || !values.length) return null;
  const abs = values.map(Math.abs);
  if (method === "both" && abs.length >= 2) return (abs[0] + abs[1]) / 2;
  if (method === "three" && abs.length >= 3) return abs[1];
  return abs[0];
}

export function isBoundary(values, limits) {
  const mags = values.map(Math.abs);
  return limits.some((lim) => mags.some((m) => atLeast(m, lim)) && mags.some((m) => !atLeast(m, lim)));
}

// 시작값과 끊김을 이어 잰 거리
export function continued(mark, start, breaks = []) {
  let dist = 0;
  let from = start;
  for (const b of breaks) {
    dist += b.orig - from;
    from = b.now;
  }
  return dist + (mark - from);
}

const inFine = (m, fine) => fine.some(([a, b]) => m > a + EPS && m <= b + EPS);

// 매뉴얼 5장 다, 4장 가: 앞으로 잴 자리. 표시값이 아니라 출발 마디에서 잰 거리다.
export function planMarks(len, fine = [], stop = null, rules) {
  const S = rules.slope;
  if (len < S.short_skip) return [];
  if (len < S.short_mid) return [{ mark: round1(len / 2), kind: "gap", both: false, cross: true }];
  const limit = stop ?? len;
  const out = new Map();
  for (let m = S.first; m < limit - EPS; m += S.step) {
    if (!inFine(m, fine)) out.set(round1(m), { mark: round1(m), kind: "gap", both: false, cross: true });
  }
  for (const [a, b] of fine) {
    const top = Math.min(b, limit);
    for (const step of [S.fine_step, S.fine_both_step]) {
      for (let m = Math.ceil((a + EPS) / step) * step; m <= top + EPS && m < limit - EPS; m += step) {
        if (m <= 0) continue;
        const multiple = Math.abs(m / S.fine_both_step - Math.round(m / S.fine_both_step)) < EPS;
        out.set(round1(m), { mark: round1(m), kind: "fine", both: multiple, cross: multiple });
      }
    }
  }
  const list = [...out.values()].sort((p, q) => p.mark - q.mark);
  if (!list.length) return [{ mark: round1(limit / 2), kind: "gap", both: false, cross: true }];
  if (limit - list[list.length - 1].mark > S.end_gap + EPS) {
    list.push({ mark: round1(limit - S.end_back), kind: "end", both: false, cross: true });
  }
  return list;
}

// 아직 안 잰 자리. 값이 3.2° 이상인 간격 지점에는 앞뒤 5 m가 더해진다. 1순위 범위에서는 더하지 않는다.
export function pendingMarks(plan, saved, len, fine = [], rules) {
  const S = rules.slope;
  const taken = (m) => saved.some((p) => Math.abs(p.mark - m) <= S.match_tol + EPS);
  const extras = [];
  for (const p of saved) {
    if (p.kind === "more" || p.long == null) continue;
    if (inFine(p.mark, fine)) continue;
    if (!atLeast(Math.abs(p.long), S.more_from)) continue;
    for (const d of [-S.more_dist, S.more_dist]) {
      const m = round1(p.mark + d);
      if (m > EPS && m < len - EPS) extras.push({ mark: m, kind: "more", both: false, cross: true });
    }
  }
  const out = plan.filter((p) => !taken(p.mark));
  for (const e of extras) {
    if (taken(e.mark)) continue;
    if (out.some((p) => Math.abs(p.mark - e.mark) <= S.match_tol + EPS)) continue;
    out.push(e);
  }
  return out.sort((p, q) => p.mark - q.mark);
}

export const needLongRecheck = (long, fineBoth, rules) => fineBoth || inRanges(Math.abs(long), rules.slope.long_recheck);
export const needCrossRecheck = (cross, rules) => inRanges(Math.abs(cross), rules.slope.cross_recheck);
export const needMore = (long, inFineRange, rules) => !inFineRange && atLeast(Math.abs(long), rules.slope.more_from);

// 저장 때 검사. 막지 않고 다시 읽어 달라고만 한다.
export function checkPoint(prev, point, rules) {
  const out = [];
  const R = rules.range;
  const C = rules.check;
  const warn = (code, msg) => out.push({ code, msg });
  if (point.long != null && Math.abs(point.long) > R.long + EPS) warn("range_long", `앞뒤 ${R.long}° 넘음. 1번 더 읽어 주세요`);
  if (point.cross != null && Math.abs(point.cross) > R.cross + EPS) warn("range_cross", `좌우 ${R.cross}° 넘음. 1번 더 읽어 주세요`);
  if (point.values && point.values.length === 2) {
    const [a, b] = point.values;
    if (Math.sign(a) !== Math.sign(b) && Math.abs(a) >= 0.5 && Math.abs(b) >= 0.5) warn("both_sign", "양 끝 두 값의 부호가 다릅니다. 부호를 확인해 주세요");
  }
  const last = prev.length ? prev[prev.length - 1] : null;
  if (last && point.kind && point.kind !== "more") {
    if (point.mark < last.mark - EPS && last.kind !== "more") warn("mark_down", "표시값이 앞 지점보다 작습니다");
    if (point.mark - maxMark(prev) > C.gap_m + EPS) warn("gap", `앞 지점과 ${C.gap_m} m 넘게 떨어졌습니다`);
  }
  const before = nearestBelow(prev, point.mark);
  if (before && before.long != null && point.long != null) {
    if (Math.abs(before.long - point.long) > C.neighbor_deg + EPS) warn("neighbor", `이웃 지점과 ${C.neighbor_deg}° 넘게 다릅니다. 1번 더 읽어 주세요`);
    if (Math.sign(before.long) !== Math.sign(point.long) && Math.abs(before.long) >= 1 && Math.abs(point.long) >= 1) warn("sign", "앞 지점과 오르내림이 반대입니다. 부호를 확인해 주세요");
  }
  return out;
}

const maxMark = (pts) => pts.reduce((m, p) => Math.max(m, p.mark), -Infinity);
function nearestBelow(prev, mark) {
  let best = null;
  for (const p of prev) if (p.mark < mark - EPS && (!best || p.mark > best.mark)) best = p;
  return best;
}

export function lengthMismatch(measured, mapLen, rules) {
  const diff = Math.abs(measured - mapLen);
  return diff > rules.check.len_m + EPS && (diff / mapLen) * 100 > rules.check.len_pct + EPS;
}

export function photosRequired(pt, rules) {
  let n = pt.first ? 1 : 0;
  const recheck = pt.method === "both" || (pt.crossValues && pt.crossValues.length === 2);
  if (recheck) n += 1;
  if (pt.flags && pt.flags.includes("boundary")) n += 1;
  return n;
}

// 도구 점검 (매뉴얼 10장)
export const levelCheck = (a, b, rules) => Math.abs(Math.abs(a) - Math.abs(b)) <= rules.tool.level_diff + EPS;
export const levelRepeat = (d1, d2, rules) => (Math.abs(d1 - d2) <= rules.tool.level_repeat + EPS ? "both_avg" : "no_judge");
export function caliperCheck(closed, coin, depth, rules) {
  const [a, b, c] = rules.tool.caliper;
  const t = rules.tool.caliper_tol;
  return Math.abs(closed - a) <= EPS + 0.05 && Math.abs(coin - b) <= t + EPS && Math.abs(depth - c) <= EPS + 0.05;
}
export const wheelCheck = (v, rules) => v >= rules.tool.wheel[0] - EPS && v <= rules.tool.wheel[1] + EPS;

// 소수점 키 없는 입력: 47이면 4.7
export function fixedValue(digits, decimals) {
  if (!digits) return null;
  return Number(digits) / 10 ** decimals;
}

// 사건을 처음부터 쌓아 지금 상태를 만든다 --------------------------------------
const timeOf = (e) => Date.parse(e.at) || 0;

export function sortEvents(events) {
  const seen = new Map();
  for (const e of events) if (!seen.has(e.id)) seen.set(e.id, e);
  return [...seen.values()].sort((a, b) => timeOf(a) - timeOf(b) || String(a.dev).localeCompare(String(b.dev)) || (a.seq || 0) - (b.seq || 0));
}

function effectiveRecords(sorted) {
  const fixes = new Map();
  const voided = new Set();
  for (const e of sorted) {
    if (e.kind === "fix") {
      if (!fixes.has(e.data.of)) fixes.set(e.data.of, []);
      fixes.get(e.data.of).push(e);
    } else if (e.kind === "void") voided.add(e.data.of);
  }
  return (e) => {
    if (voided.has(e.id)) return null;
    const fx = fixes.get(e.id);
    if (!fx) return { ...e.data, id: e.id, at: e.at, gps: e.gps, by: e.by, rev: 1 };
    const data = { ...e.data };
    for (const f of fx) Object.assign(data, f.data.data);
    return { ...data, id: e.id, at: e.at, gps: e.gps, by: e.by, rev: fx.length + 1, original: e.data, fixedAt: fx[fx.length - 1].at };
  };
}

export function foldEvents(events, rules = null) {
  const sorted = sortEvents(events);
  const eff = effectiveRecords(sorted);
  const s = {
    eventCount: sorted.length, day: null, people: { measurer: "", recorder: "", since: null },
    runs: {}, runOrder: [], openRun: null, segStatus: {}, redo: [], skipped: [], routeChoice: null,
    levelMode: null, toolChecks: [], newPaths: {}, facilities: [], mapChecks: [], loose: [], photos: {}, lastSeq: {},
  };
  const pushRun = (e, list, rec) => {
    const run = s.runs[e.run];
    if (run) run[list].push(rec);
    else s.loose.push({ kind: e.kind, ...rec });
  };

  for (const e of sorted) {
    s.lastSeq[e.dev] = Math.max(s.lastSeq[e.dev] || 0, e.seq || 0);
    if (e.kind === "photo") {
      if (e.data.of) s.photos[e.data.of] = (s.photos[e.data.of] || 0) + 1;
      if (e.run && s.runs[e.run]) s.runs[e.run].photoCount += 1;
      continue;
    }
    if (e.kind === "fix" || e.kind === "void" || e.kind === "track") continue;
    const rec = eff(e);
    if (!rec) continue;

    switch (e.kind) {
      case "day":
        s.day = rec;
        s.people = { measurer: rec.measurer || "", recorder: rec.recorder || "", since: e.at };
        break;
      case "role":
        s.people = { measurer: rec.measurer, recorder: rec.recorder, since: e.at };
        break;
      case "tool_check":
        s.toolChecks.push(rec);
        if (rec.tool === "level") s.levelMode = rec.passed ? null : (rec.mode || "no_judge");
        break;
      case "run_start": {
        s.runs[e.id] = {
          id: e.id, seg: rec.seg, from: rec.from, start: rec.start ?? 0, line: rec.line || "main", routeLine: !!rec.routeLine,
          retry: rec.retry || "", startedAt: e.at, closed: false, end: null, result: null, missing: [], points: [], barriers: [],
          surfaces: [], breaks: [], photoCount: 0, wet: !!rec.wet, memo: rec.memo || "", planned_stop: rec.planned_stop ?? null,
          by: e.by, endId: null,
        };
        s.runOrder.push(e.id);
        s.openRun = e.id;
        if (s.segStatus[rec.seg] !== "done") s.segStatus[rec.seg] = "open";
        break;
      }
      case "run_edit": {
        const run = s.runs[e.run];
        if (run) {
          Object.assign(run, rec.changes);
          if (rec.changes.seg != null) s.segStatus[rec.changes.seg] = run.closed ? statusOf(run) : "open";
          if (rec.prev_seg != null) delete s.segStatus[rec.prev_seg];
        }
        break;
      }
      case "slope": {
        const run = s.runs[e.run];
        const pt = slopePoint(rec, s.levelMode, rules, run ? run.points.length === 0 : false);
        pushRun(e, "points", pt);
        break;
      }
      case "barrier":
        pushRun(e, "barriers", rec);
        break;
      case "surface":
        pushRun(e, "surfaces", rec);
        break;
      case "break":
        pushRun(e, "breaks", rec);
        break;
      case "facility":
        s.facilities.push({ ...rec, run: e.run || null });
        break;
      case "map_check":
        s.mapChecks.push({ ...rec, run: e.run || null });
        break;
      case "new_path":
        s.newPaths[rec.no] = rec;
        break;
      case "route_choice":
        s.routeChoice = rec;
        break;
      case "skip":
        s.skipped.push(rec.seg);
        break;
      case "unskip":
        s.skipped = s.skipped.filter((x) => x !== rec.seg);
        break;
      case "redo":
        s.redo = s.redo.filter((r) => r.seg !== rec.seg);
        s.redo.push(rec);
        s.segStatus[rec.seg] = "redo";
        break;
      case "run_end": {
        const run = s.runs[e.run];
        if (!run) break;
        run.closed = true;
        run.endId = e.id;
        run.end = rec.end;
        run.result = rec.result;
        run.missing = rec.missing || [];
        run.memo = rec.memo ?? run.memo;
        run.endedAt = e.at;
        run.planned = !!rec.planned;
        if (s.openRun === run.id) s.openRun = null;
        s.segStatus[run.seg] = statusOf(run);
        s.redo = s.redo.filter((r) => r.seg !== run.seg);
        s.skipped = s.skipped.filter((x) => x !== run.seg);
        break;
      }
      default:
        break;
    }
  }
  return s;
}

function statusOf(run) {
  if (run.result === "ok") return run.missing && run.missing.length ? "partial" : "done";
  if (run.result === "stopped") return "partial";
  if (run.result === "not_path") return "not_path";
  if (run.result === "no_entry") return "no_entry";
  if (run.result === "temp_block") return "temp_block";
  return "partial";
}

function slopePoint(rec, levelMode, rules, first) {
  const flags = [...(rec.flags || [])];
  if (levelMode && !flags.includes("tool_fail")) flags.push("tool_fail");
  const method = rec.method || "one";
  const values = rec.values || [];
  const crossValues = rec.cross || [];
  if (rules && method === "three" && values.length === 3) {
    const longBound = isBoundary(values, rules.slope.bound_long);
    if (longBound && !flags.includes("boundary")) flags.push("boundary");
  }
  return {
    ...rec, flags, method, values, cross: crossValues, crossValues, first,
    long: longRoute(values, method), crossValue: crossRoute(crossValues, crossValues.length === 2 ? "both" : method),
  };
}
