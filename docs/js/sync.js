// 데이터베이스 사본. 폰 저장이 원본이므로 여기서 실패해도 측정은 멈추지 않는다.
import { clearPending, getMeta, importEvents, pendingBatch, setMeta } from "./store.js";

const BATCH = 100;
let cfg = null;
let busy = false;

export function configure(db) {
  cfg = db || null;
}

export const isConfigured = () => !!cfg;

export async function currentUser() {
  const s = await getMeta("session");
  return s ? s.email : null;
}

export async function login(email, password) {
  if (!cfg) throw new Error("자료 파일에 데이터베이스 정보가 없습니다");
  const r = await fetch(`${cfg.url}/auth/v1/token?grant_type=password`, {
    method: "POST",
    headers: { apikey: cfg.key, "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) throw new Error(r.status === 400 ? "이메일이나 비밀번호가 맞지 않습니다" : `로그인 실패 (${r.status})`);
  const j = await r.json();
  await saveSession(j, email);
  return email;
}

export async function logout() {
  await setMeta("session", null, true);
}

async function saveSession(j, email) {
  await setMeta("session", {
    access: j.access_token, refresh: j.refresh_token, email,
    expires: Date.now() + (j.expires_in || 3600) * 1000,
  }, true);
}

async function token(force = false) {
  const s = await getMeta("session");
  if (!s) return null;
  if (!force && s.expires - Date.now() > 60000) return s.access;
  const r = await fetch(`${cfg.url}/auth/v1/token?grant_type=refresh_token`, {
    method: "POST",
    headers: { apikey: cfg.key, "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: s.refresh }),
  });
  if (!r.ok) {
    if (r.status === 400 || r.status === 401) throw new Error("다시 로그인이 필요합니다");
    throw new Error(`토큰 갱신 실패 (${r.status})`);
  }
  await saveSession(await r.json(), s.email);
  return (await getMeta("session")).access;
}

const headers = (t, extra = {}) => ({ apikey: cfg.key, Authorization: `Bearer ${t}`, "Content-Type": "application/json", ...extra });

function toRow(e) {
  return {
    id: e.id, run_id: e.run || "-", kind: e.kind, payload: e,
    device_id: e.dev, app_version: e.app || "?", recorded_at: e.at,
  };
}

async function postRows(rows, t) {
  return fetch(`${cfg.url}/rest/v1/field_records?on_conflict=id`, {
    method: "POST",
    headers: headers(t, { Prefer: "resolution=ignore-duplicates,return=minimal" }),
    body: JSON.stringify(rows),
  });
}

// 대기 중인 사건을 묶음으로 보낸다. 같은 사건을 다시 보내도 서버가 무시한다.
export async function pushPending() {
  if (!cfg || busy || !navigator.onLine) return { sent: 0, skipped: true };
  busy = true;
  let sent = 0;
  try {
    let t = await token();
    if (!t) return { sent: 0, noLogin: true };
    for (;;) {
      const { ids, events } = await pendingBatch(BATCH);
      if (!ids.length) break;
      if (events.length) {
        let r = await postRows(events.map(toRow), t);
        if (r.status === 401) {
          t = await token(true);
          r = await postRows(events.map(toRow), t);
        }
        if (!r.ok) throw new Error(`전송 실패 (${r.status})`);
      }
      await clearPending(ids);
      sent += ids.length;
      await setMeta("lastSentAt", new Date().toISOString());
    }
    return { sent };
  } finally {
    busy = false;
  }
}

// 빈 폰에 데이터베이스에서 내려받는다.
export async function pullAll(site) {
  if (!cfg) throw new Error("자료 파일에 데이터베이스 정보가 없습니다");
  let t = await token();
  if (!t) throw new Error("로그인이 필요합니다");
  const size = 1000;
  let offset = 0;
  let added = 0;
  let total = 0;
  for (;;) {
    const url = `${cfg.url}/rest/v1/field_records?select=payload&payload->>site=eq.${encodeURIComponent(site)}&order=recorded_at.asc,id.asc&limit=${size}&offset=${offset}`;
    let r = await fetch(url, { headers: headers(t) });
    if (r.status === 401) {
      t = await token(true);
      r = await fetch(url, { headers: headers(t) });
    }
    if (!r.ok) throw new Error(`내려받기 실패 (${r.status})`);
    const rows = await r.json();
    const res = await importEvents(rows.map((x) => x.payload), { markPending: false });
    added += res.added;
    total += rows.length;
    if (rows.length < size) break;
    offset += size;
  }
  return { added, total };
}
