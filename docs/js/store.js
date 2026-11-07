// 폰 저장. 기록 1건이 IndexedDB 행 1개다. 쓰기가 디스크까지 끝난 뒤에만 호출자에게 돌려준다.
const DB_NAME = "bf-gather-v1";
const DB_VER = 1;
let db = null;

function req(r) {
  return new Promise((ok, no) => {
    r.onsuccess = () => ok(r.result);
    r.onerror = () => no(r.error);
  });
}

function done(tx) {
  return new Promise((ok, no) => {
    tx.oncomplete = () => ok();
    tx.onerror = () => no(tx.error);
    tx.onabort = () => no(tx.error || new Error("저장 취소됨"));
  });
}

export async function openStore() {
  if (db) return db;
  db = await new Promise((ok, no) => {
    const r = indexedDB.open(DB_NAME, DB_VER);
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

// 사건 1건을 쓴다. 일련번호, 사건, 전송 대기 표시를 한 트랜잭션으로 묶는다.
export async function addEvent(make) {
  const tx = db.transaction(["events", "pending", "meta"], "readwrite", { durability: "strict" });
  const meta = tx.objectStore("meta");
  const seq = ((await req(meta.get("seq"))) || 0) + 1;
  meta.put(seq, "seq");
  const ev = make(seq);
  tx.objectStore("events").put(ev);
  tx.objectStore("pending").put({ id: ev.id });
  await done(tx);
  return ev;
}

export async function allEvents() {
  return req(db.transaction("events").objectStore("events").getAll());
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
