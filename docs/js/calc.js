// 측정 규칙 계산. 화면과 저장을 모르는 순수 함수만 둔다. 브라우저와 Node 시험이 같은 파일을 읽는다.

const EPS = 1e-9;
const round1 = (x) => Math.round(x * 10) / 10;
const round2 = (x) => Math.round(x * 100) / 100;
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

// 구간표의 값을 출발 방향 기준으로 바꾼다.
export const fineFor = (s, from) => (s.fine || []).map(([a, b]) => (from === s.a ? [a, b] : [round2(s.len - b), round2(s.len - a)])).sort((p, q) => p[0] - q[0]);
export const stopFor = (s, from) => (s.stop && s.stop.from === from ? s.stop.m : null);
export const geoFor = (s, from) => ({ len: s.len, fine: fineFor(s, from), stop: stopFor(s, from), inclines: s.inclines || null });

// 매뉴얼 5장 다, 4장 가: 앞으로 잴 자리. 표시값이 아니라 출발 마디에서 잰 거리다.
// inclines: 구간표의 지도 경사 표시. 3 m 미만 구간도 표시가 있으면 가운데 1곳을 잰다(5장 다 3).
export function planMarks(len, fine = [], stop = null, rules, inclines = null) {
  const S = rules.slope;
  if (len < S.short_skip) return inclines && inclines.some((v) => v > 0) ? [{ mark: round1(len / 2), kind: "gap", both: false, cross: true }] : [];
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
// 저장한 값 하나는 허용 폭 안의 가장 가까운 예정 지점 하나만 지운다. '여기 더 재기'(added)는 지우지 않는다.
// stop: 계획된 중단 거리. 그 너머로는 더하지 않는다.
export function pendingMarks(plan, saved, len, fine = [], rules, stop = null) {
  const S = rules.slope;
  const limit = stop ?? len;
  const near = (a, b) => Math.abs(a - b) <= S.match_tol + EPS;
  const pool = plan.map((p) => ({ ...p }));
  for (const p of saved) {
    if (p.kind === "more" || p.long == null) continue;
    if (inFine(p.mark, fine)) continue;
    if (!atLeast(Math.abs(p.long), S.more_from)) continue;
    for (const d of [-S.more_dist, S.more_dist]) {
      const m = round1(p.mark + d);
      if (m > EPS && m < limit - EPS && !pool.some((x) => near(x.mark, m))) pool.push({ mark: m, kind: "more", both: false, cross: true });
    }
  }
  const used = new Set();
  const free = (i) => !used.has(i);
  const top = topMark(saved);
  const take = (p) => {
    // 끝 앞 지점은 실제 끝에서 재므로 거리와 상관없이 끝 앞 예정을 지운다. 되돌아가 잰 앞쪽 지점은 아니다.
    if (p.kind === "end" && p.mark >= top - EPS) {
      const i = pool.findIndex((x, j) => free(j) && x.kind === "end");
      if (i >= 0) return i;
    }
    // 어느 예정을 재려던 것인지 알면 그 예정만 지운다. 4를 4.6에서 재도 5의 의무가 남는다.
    if (p.target != null) {
      const i = pool.findIndex((x, j) => free(j) && Math.abs(x.mark - p.target) < 1e-6);
      if (i >= 0 && near(pool[i].mark, p.mark)) return i;
    }
    let best = -1;
    for (let i = 0; i < pool.length; i += 1) {
      if (!free(i) || !near(pool[i].mark, p.mark)) continue;
      if (pool[i].both && p.n != null && p.n < 2) continue; // 양 끝 의무 지점은 값 하나로 지우지 않는다
      if (best < 0 || Math.abs(pool[i].mark - p.mark) < Math.abs(pool[best].mark - p.mark)) best = i;
    }
    return best;
  };
  for (const p of saved) {
    if (p.added) continue;
    const i = take(p);
    if (i >= 0) used.add(i);
  }
  return pool.filter((_, i) => !used.has(i)).sort((p, q) => p.mark - q.mark);
}

// 차례대로 잰 지점 가운데 가장 먼 거리. 더한 지점은 세지 않는다.
function topMark(saved) {
  return saved.filter((p) => p.kind !== "more" && !p.added).reduce((m, p) => Math.max(m, p.mark), -Infinity);
}

// 남은 지점을 다음 차례(ahead)와 지나친 것(behind)으로 나눈다. 더한 지점(more)은 뒤에 있어도 차례에 둔다.
// 지나친 예정 지점은 다음 일로 되돌아가지 않고 구간 끝에서 못 잰 지점으로 센다.
export function splitPending(pending, saved, rules) {
  const top = topMark(saved);
  const ahead = [];
  const behind = [];
  for (const p of pending) (p.kind === "more" || p.mark >= top - rules.slope.match_tol - EPS ? ahead : behind).push(p);
  return { ahead, behind };
}

const distIn = (run, p) => continued(p.mark, run.start, run.breaks.slice(0, p.breakCount ?? run.breaks.length));

// 아직 안 잰 예정 지점. 잰 거리 너머의 예정은 세지 않는다(끝까지 못 감, 실제 끝이 지도보다 짧은 길).
// 다만 길이 경고가 있는 '길 맞음'은 끝값을 믿지 않는다. '길 맞음'에서 마지막 지점부터 끝까지 end_gap을 넘으면 끝 앞 한 곳이 남는다(매뉴얼 5장 다 2).
// 계획된 중단이 있으면 그 너머는 재지 않으므로 끝을 중단 거리로 본다.
export function leftMarks(run, geo, rules) {
  if (run.result !== "ok" && run.result !== "stopped") return [];
  const plan = planMarks(geo.len, geo.fine, geo.stop, rules, geo.inclines);
  const saved = run.points.filter((p) => p.long != null).map((p) => ({ mark: distIn(run, p), long: p.long, kind: p.kind, added: p.added, target: p.target, n: (p.values || []).length }));
  const left = pendingMarks(plan, saved, geo.len, geo.fine, rules, geo.stop);
  const measured = run.end != null ? continued(run.end, run.start, run.breaks) : null;
  if (measured == null) return run.result === "stopped" ? [] : left;
  const S = rules.slope;
  const kept = run.result === "ok" && lengthMismatch(measured, geo.len, rules) ? left : left.filter((p) => p.mark < measured - S.match_tol - EPS);
  if (run.result !== "ok") return kept;
  const reach = geo.stop != null ? Math.min(measured, geo.stop) : measured;
  const last = [...saved, ...kept].reduce((m, p) => Math.max(m, p.mark), 0);
  if (reach - last <= S.end_gap + EPS) return kept;
  return [...kept, { mark: round1(reach - S.end_back), kind: "end", both: false, cross: true }];
}

// 좌우 '못 잼': 값이 없거나, 재확인 범위의 첫 값만 있고 둘째를 못 읽었다. 값을 나중에 넣으면 빠진다.
function crossUnread(p, rules) {
  if (!p.no_cross) return false;
  const c = p.cross || [];
  return !c.length || (c.length === 1 && needCrossRecheck(c[0], rules));
}

// 구간 측정의 못 잰 항목. 저장한 값이 아니라 지금의 원값으로 계산한다(매뉴얼 1장 나 5, 9장 다).
// 저녁 도구 evening.py의 run_missing과 같고 같은 시험값(calc_cases.json)을 통과한다.
export function runMissing(run, geo, rules) {
  if (run.result !== "ok" && run.result !== "stopped") return [];
  const out = [];
  if (!run.points.some((p) => p.long != null)) out.push("slope");
  else if (leftMarks(run, geo, rules).length) out.push("slope_points");
  if (geo.len >= rules.width.skip_len && !run.barriers.some((b) => b.type === "width_rep" && b.value != null)) out.push("width");
  if (!run.surfaces.length) out.push("surface");
  if (run.barriers.some((b) => b.unread && b.unread.length)) out.push("barrier_value");
  if (run.points.some((p) => crossUnread(p, rules))) out.push("cross");
  if (run.no_barrier === "not_looked") out.push("barrier_look");
  return out;
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
// 순서 번호(ord): 쓸 때의 시각과 그 폰이 본 마지막 순서 번호 + 1 중 큰 값이다.
// 시계가 뒤로 가거나 시계가 느린 다른 폰으로 이어 써도 순서가 유지된다. 번호가 없는 옛 기록은 시각(ms)을 쓴다.
export const orderOf = (e) => (typeof e.ord === "number" ? e.ord : timeOf(e));
export const nextOrd = (now, maxSeen) => Math.max(now, (maxSeen || 0) + 1);

export function sortEvents(events) {
  const seen = new Map();
  for (const e of events) if (!seen.has(e.id)) seen.set(e.id, e);
  return [...seen.values()].sort((a, b) => orderOf(a) - orderOf(b) || String(a.dev).localeCompare(String(b.dev)) || (a.seq || 0) - (b.seq || 0));
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
    for (const f of fx) {
      Object.assign(data, f.data.data);
      for (const k of f.data.unset || []) delete data[k];
    }
    return { ...data, id: e.id, at: e.at, gps: e.gps, by: e.by, rev: fx.length + 1, original: e.data, fixedAt: fx[fx.length - 1].at };
  };
}

// 끊김 수는 저장값이 아니라 쌓는 순서로 센다. 앞의 끊김을 지워도 뒤 기록이 다음 끊김을 받지 않는다.
const withBreaks = (rec, run) => (run ? { ...rec, breakCount: run.breaks.length } : rec);

// geoOf(run, 상태): 구간의 지도 길이와 예정 값. 주면 닫은 구간의 못 잰 항목과 상태를 지금의 원값으로 다시 계산한다.
export function foldEvents(events, rules = null, dev = null, geoOf = null) {
  const sorted = sortEvents(events);
  const eff = effectiveRecords(sorted);
  const s = {
    eventCount: sorted.length, day: null, people: { measurer: "", recorder: "", since: null },
    runs: {}, runOrder: [], openRun: null, segStatus: {}, redo: [], skipped: [], routeChoice: null,
    levelMode: null, toolChecks: [], newPaths: {}, facilities: [], mapChecks: [], loose: [], photos: {}, lastSeq: {}, maxOrd: 0,
  };
  const statusBy = {}; // 구간 상태를 정한 측정
  const pushRun = (e, list, rec) => {
    const run = s.runs[e.run];
    if (run) run[list].push(rec);
    else s.loose.push({ kind: e.kind, ...rec });
  };

  for (const e of sorted) {
    s.lastSeq[e.dev] = Math.max(s.lastSeq[e.dev] || 0, e.seq || 0);
    s.maxOrd = Math.max(s.maxOrd, orderOf(e));
    if (e.kind === "photo") {
      if (!eff(e)) continue;
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
          by: e.by, endId: null, dev: e.dev,
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
          if (rec.changes.seg != null) {
            s.segStatus[rec.changes.seg] = run.closed ? statusOf(run) : "open";
            if (run.closed) statusBy[rec.changes.seg] = run.id;
          }
          if (rec.prev_seg != null) {
            // 옛 구간은 남은 측정의 상태로 돌린다. 남은 측정이 없으면 안 잰 구간이다.
            const rest = s.runOrder.map((id) => s.runs[id]).filter((r) => r.seg === rec.prev_seg);
            const last = rest[rest.length - 1];
            if (last) s.segStatus[rec.prev_seg] = last.closed ? statusOf(last) : "open";
            else delete s.segStatus[rec.prev_seg];
            if (last && last.closed) statusBy[rec.prev_seg] = last.id;
            else delete statusBy[rec.prev_seg];
          }
        }
        break;
      }
      case "slope": {
        const run = s.runs[e.run];
        const pt = slopePoint(withBreaks(rec, run), s.levelMode, rules, run ? run.points.length === 0 : false);
        pushRun(e, "points", pt);
        break;
      }
      case "barrier":
        pushRun(e, "barriers", withBreaks(rec, s.runs[e.run]));
        break;
      case "surface":
        pushRun(e, "surfaces", withBreaks(rec, s.runs[e.run]));
        break;
      case "break":
        pushRun(e, "breaks", rec);
        break;
      case "facility":
        s.facilities.push({ ...withBreaks(rec, s.runs[e.run]), run: e.run || null });
        break;
      case "map_check":
        s.mapChecks.push({ ...withBreaks(rec, s.runs[e.run]), run: e.run || null });
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
        run.extraMissing = run.missing.filter((m) => m === "other"); // 사람이 더한 것만 저장값을 쓴다
        run.no_barrier = rec.no_barrier ?? null;
        run.twin = rec.twin ?? null;
        run.memo = rec.memo ?? run.memo;
        run.endedAt = e.at;
        run.planned = !!rec.planned;
        if (s.openRun === run.id) s.openRun = null;
        s.segStatus[run.seg] = statusOf(run);
        statusBy[run.seg] = run.id;
        s.redo = s.redo.filter((r) => r.seg !== run.seg);
        s.skipped = s.skipped.filter((x) => x !== run.seg);
        break;
      }
      default:
        break;
    }
  }
  // 닫은 뒤 고치거나 지워도 못 잰 항목과 상태가 낡지 않게 지금의 원값으로 다시 계산한다.
  if (rules && geoOf) {
    for (const id of s.runOrder) {
      const run = s.runs[id];
      const geo = run.closed ? geoOf(run, s) : null;
      if (geo) run.missing = [...runMissing(run, geo, rules), ...(run.extraMissing || [])];
    }
    for (const [seg, id] of Object.entries(statusBy)) {
      if (s.segStatus[seg] === "done" || s.segStatus[seg] === "partial") s.segStatus[seg] = statusOf(s.runs[id]);
    }
  }
  // 열린 구간: 이 폰이 시작한 것 가운데 마지막. 없으면 열린 것 가운데 마지막(다른 폰으로 이어 쓸 때).
  // 다른 폰 기록을 합쳐도 이 폰에서 재던 구간이 바뀌지 않는다.
  const open = s.runOrder.filter((id) => !s.runs[id].closed);
  const mine = dev ? open.filter((id) => s.runs[id].dev === dev) : [];
  s.openRun = (mine.length ? mine : open).slice(-1)[0] ?? null;
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
  // 경계 표시는 저장값을 믿지 않고 값으로 다시 정한다. 고친 뒤 옛 표시가 남지 않게 한다.
  const flags = (rec.flags || []).filter((f) => !(rules && f === "boundary"));
  if (levelMode && !flags.includes("tool_fail")) flags.push("tool_fail");
  const method = rec.method || "one";
  const values = rec.values || [];
  const crossValues = rec.cross || [];
  if (rules && method === "three" && values.length === 3 && isBoundary(values, rules.slope.bound_long)) flags.push("boundary");
  return {
    ...rec, flags, method, values, cross: crossValues, crossValues, first,
    long: longRoute(values, method), crossValue: crossRoute(crossValues, crossValues.length === 2 ? "both" : method),
  };
}
