// 폰 저장. 기록 1건이 IndexedDB 행 1개다. 쓰기가 디스크까지 끝난 뒤에만 호출자에게 돌려준다.
// 대상지(자료의 site와 연결망)마다 저장소를 따로 둔다. 다른 자료를 넣어도 앞 대상지 기록은 그대로 남는다.
export const DEFAULT_NAME = "bf-gather-v1";
const DB_VER = 1;
let db = null;
let dbName = DEFAULT_NAME;

const MAP_KEY = "bf-stores";
const CUR_KEY = "bf-store-cur";
const readMap = () => { try { return JSON.parse(localStorage.getItem(MAP_KEY) || "{}"); } catch { return {}; } };

// 시험 자료와 실제 자료는 대상지가 같아도 기록을 섞지 않는다.
export const siteKey = (pack) => `${pack.site}_${pack.net}${pack.test ? "_test" : ""}`;
export const hasStore = (key) => !!readMap()[key];
export const currentName = () => dbName;

// 시작할 때 열 저장소 이름. 처음 쓰는 폰은 기본 이름이다.
export function startName() {
  const cur = localStorage.getItem(CUR_KEY);
  return (cur && readMap()[cur]) || DEFAULT_NAME;
}

// 이 대상지의 저장소 이름을 정하고 지금 대상지로 적는다.
export function claim(key, name) {
  const map = readMap();
  for (const k of Object.keys(map)) if (map[k] === name && k !== key) delete map[k];
  map[key] = name;
  localStorage.setItem(MAP_KEY, JSON.stringify(map));
  localStorage.setItem(CUR_KEY, key);
}

export function nameFor(key) {
  return readMap()[key] || `${DEFAULT_NAME}-${key}`;
}

export async function switchTo(name) {
  if (db) db.close();
  db = null;
  await openStore(name);
}

function req(r) {
  return new Promise((ok, no) => {
    r.onsuccess = () => ok(r.result);
    r.onerror = () => no(r.error);
  });
}

function done(tx) {
  return new Promise((ok, no) => {
    tx.oncomplete = () => ok();
    // 요청 하나가 실패하면 tx.error가 아직 비어 있을 수 있다. 그 요청의 오류를 넘긴다.
    tx.onerror = (ev) => no(tx.error || (ev && ev.target && ev.target.error) || new Error("저장 실패"));
    tx.onabort = (ev) => no(tx.error || (ev && ev.target && ev.target.error) || new Error("저장 취소됨"));
  });
}

export async function openStore(name = dbName) {
  if (db && name === dbName) return db;
  if (db) db.close();
  dbName = name;
  db = await new Promise((ok, no) => {
    const r = indexedDB.open(name, DB_VER);
    r.onupgradeneeded = () => {
      const d = r.result;
      d.createObjectStore("events", { keyPath: "id" });
      d.createObjectStore("pending", { keyPath: "id" });
      d.createObjectStore("meta");
      d.createObjectStore("pack");
    };
    r.onsuccess = () => ok(r.result);
    r.onerror = () => no(r.error);
    r.onblocked = () => no(new Error("다른 창이 저장소를 막고 있습니다"));
  });
  return db;
}

export function uid() {
  return crypto.randomUUID();
}

export async function getDeviceId() {
  let id = await getMeta("device");
  if (!id) {
    id = uid().slice(0, 8);
    await setMeta("device", id, true);
  }
  return id;
}

// 사건을 쓴다. 일련번호, 사건, 전송 대기 표시를 한 트랜잭션으로 묶는다. 여러 건이면 모두 저장되거나 하나도 안 된다.
export async function addEvents(makers) {
  const tx = db.transaction(["events", "pending", "meta"], "readwrite", { durability: "strict" });
  const meta = tx.objectStore("meta");
  let seq = (await req(meta.get("seq"))) || 0;
  const out = [];
  try {
    for (const make of makers) {
      seq += 1;
      const ev = make(seq);
      // add: 같은 번호가 이미 있으면 실패한다. 저장 직후 앱이 죽어 옛 초안이 돌아와도 원값을 덮어쓰지 않는다.
      tx.objectStore("events").add(ev);
      tx.objectStore("pending").put({ id: ev.id });
      out.push(ev);
    }
    meta.put(seq, "seq");
  } catch (e) {
    try { tx.abort(); } catch { /* 이미 끝난 트랜잭션 */ }
    throw e;
  }
  await done(tx);
  return out;
}

export async function addEvent(make) {
  return (await addEvents([make]))[0];
}

export async function allEvents() {
  return req(db.transaction("events").objectStore("events").getAll());
}

// 시작이 실패했을 때 쓰는 꺼내기. getAll 대신 커서로 한 건씩 읽는다.
export async function rawEvents(name = dbName) {
  const d = await new Promise((ok, no) => {
    const r = indexedDB.open(name);
    r.onsuccess = () => ok(r.result);
    r.onerror = () => no(r.error);
  });
  return new Promise((ok, no) => {
    const out = [];
    const r = d.transaction("events").objectStore("events").openCursor();
    r.onsuccess = () => {
      const c = r.result;
      if (c) { out.push(c.value); c.continue(); } else ok(out);
    };
    r.onerror = () => no(r.error);
  });
}

// 복원과 내려받기. 이미 있는 사건은 건드리지 않는다.
export async function importEvents(list, { markPending = true } = {}) {
  const tx = db.transaction(["events", "pending"], "readwrite", { durability: "strict" });
  const events = tx.objectStore("events");
  const pending = tx.objectStore("pending");
  const have = new Set(await req(events.getAllKeys()));
  let added = 0;
  for (const e of list) {
    if (!e || !e.id || !e.kind || have.has(e.id)) continue;
    events.put(e);
    if (markPending) pending.put({ id: e.id });
    have.add(e.id);
    added += 1;
  }
  await done(tx);
  return { added, skipped: list.length - added };
}

export async function pendingCount() {
  return req(db.transaction("pending").objectStore("pending").count());
}

export async function pendingBatch(limit) {
  const tx = db.transaction(["pending", "events"]);
  const ids = await req(tx.objectStore("pending").getAllKeys(null, limit));
  const out = [];
  for (const id of ids) {
    const e = await req(tx.objectStore("events").get(id));
    if (e) out.push(e);
  }
  return { ids, events: out };
}

export async function clearPending(ids) {
  const tx = db.transaction("pending", "readwrite");
  const p = tx.objectStore("pending");
  for (const id of ids) p.delete(id);
  await done(tx);
}

export async function getMeta(key) {
  return req(db.transaction("meta").objectStore("meta").get(key));
}

export async function setMeta(key, value, strict = false) {
  const tx = db.transaction("meta", "readwrite", { durability: strict ? "strict" : "relaxed" });
  tx.objectStore("meta").put(value, key);
  await done(tx);
}

export async function getPack() {
  return req(db.transaction("pack").objectStore("pack").get("current"));
}

export async function putPack(pack) {
  const tx = db.transaction("pack", "readwrite", { durability: "strict" });
  tx.objectStore("pack").put(pack, "current");
  await done(tx);
}
