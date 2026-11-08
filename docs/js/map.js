// 캔버스 지도. 항공사진 위에 구간을 상태 색으로 그리고, 눌러서 구간 후보를 고른다.
const INK = "#1d2330";
const BLUE = "#1f5fbf";
const ORANGE = "#e8590c";
const DARK = "#a63a0a";
const TILE = 256;

export function lonLatToPx(lon, lat, map) {
  const n = TILE * 2 ** map.zoom;
  const s = Math.sin((lat * Math.PI) / 180);
  const x = ((lon + 180) / 360) * n;
  const y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n;
  return [x - map.origin[0], y - map.origin[1]];
}

// 점에서 구간 선까지의 거리 (지도 픽셀)
export function distToPolyline(px, py, xy) {
  let best = Infinity;
  for (let i = 0; i + 3 < xy.length; i += 2) {
    const ax = xy[i], ay = xy[i + 1], bx = xy[i + 2], by = xy[i + 3];
    const dx = bx - ax, dy = by - ay;
    const L2 = dx * dx + dy * dy;
    const t = L2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2)) : 0;
    best = Math.min(best, Math.hypot(px - ax - t * dx, py - ay - t * dy));
  }
  return best;
}

export class MapView {
  constructor(canvas, pack, image) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.pack = pack;
    this.image = image;
    this.k = 1;
    this.tx = 0;
    this.ty = 0;
    this.status = {};
    this.selected = null;
    this.selFrom = null;
    this.gps = null;
    this.extraLines = [];
    this.draft = null;
    this.onlyRanked = true;
    this.onTap = null;
    this.paths = pack.segs.map((s) => this.toPath(s.xy));
    this.pointers = new Map();
    this.pinch = null;
    this.moved = 0;
    this.downAt = 0;
    this.bind();
    this.resize();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(canvas);
  }

  destroy() {
    this.ro.disconnect();
  }

  toPath(xy) {
    const p = new Path2D();
    for (let i = 0; i + 1 < xy.length; i += 2) {
      if (i === 0) p.moveTo(xy[0], xy[1]);
      else p.lineTo(xy[i], xy[i + 1]);
    }
    return p;
  }

  resize() {
    const r = this.c.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.dpr = dpr;
    this.w = r.width;
    this.h = r.height;
    this.c.width = Math.max(1, Math.round(r.width * dpr));
    this.c.height = Math.max(1, Math.round(r.height * dpr));
    if (!this.fitted && r.width > 0) {
      this.fit();
      this.fitted = true;
    }
    this.draw();
  }

  fit() {
    const { W, H } = this.pack.map;
    this.k = Math.min(this.w / W, this.h / H);
    this.tx = (this.w - W * this.k) / 2;
    this.ty = (this.h - H * this.k) / 2;
    this.draw();
  }

  focus(xy, k = 1.6) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let i = 0; i + 1 < xy.length; i += 2) {
      x0 = Math.min(x0, xy[i]); x1 = Math.max(x1, xy[i]);
      y0 = Math.min(y0, xy[i + 1]); y1 = Math.max(y1, xy[i + 1]);
    }
    const span = Math.max(x1 - x0, y1 - y0, 1);
    this.k = Math.min(k, (Math.min(this.w, this.h) * 0.7) / span);
    this.tx = this.w / 2 - ((x0 + x1) / 2) * this.k;
    this.ty = this.h / 2 - ((y0 + y1) / 2) * this.k;
    this.draw();
  }

  zoomBy(f, cx = this.w / 2, cy = this.h / 2) {
    const k = Math.max(0.05, Math.min(12, this.k * f));
    const r = k / this.k;
    this.tx = cx - (cx - this.tx) * r;
    this.ty = cy - (cy - this.ty) * r;
    this.k = k;
    this.draw();
  }

  toMap(x, y) {
    return [(x - this.tx) / this.k, (y - this.ty) / this.k];
  }

  // 눌린 자리의 구간 후보. 가까운 순서.
  candidates(x, y, radiusPx = 24) {
    const [mx, my] = this.toMap(x, y);
    const r = radiusPx / this.k;
    const out = [];
    for (const s of this.pack.segs) {
      if (this.onlyRanked && !s.prio) continue;
      const d = distToPolyline(mx, my, s.xy);
      if (d <= r) out.push({ seg: s.seg, d });
    }
    return out.sort((a, b) => a.d - b.d).map((c) => c.seg);
  }

  bind() {
    const c = this.c;
    const pos = (e) => {
      const r = c.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      this.pointers.set(e.pointerId, pos(e));
      this.moved = 0;
      this.downAt = performance.now();
      if (this.pointers.size === 2) {
        const [a, b] = [...this.pointers.values()];
        this.pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), cx: (a[0] + b[0]) / 2, cy: (a[1] + b[1]) / 2 };
      }
    });
    c.addEventListener("pointermove", (e) => {
      if (!this.pointers.has(e.pointerId)) return;
      const prev = this.pointers.get(e.pointerId);
      const p = pos(e);
      this.pointers.set(e.pointerId, p);
      if (this.pointers.size === 1) {
        this.tx += p[0] - prev[0];
        this.ty += p[1] - prev[1];
        this.moved += Math.hypot(p[0] - prev[0], p[1] - prev[1]);
        this.draw();
      } else if (this.pointers.size === 2 && this.pinch) {
        const [a, b] = [...this.pointers.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        this.zoomBy(d / this.pinch.d, this.pinch.cx, this.pinch.cy);
        this.pinch.d = d;
        this.moved += 20;
      }
    });
    const up = (e) => {
      const had = this.pointers.has(e.pointerId);
      const p = pos(e);
      this.pointers.delete(e.pointerId);
      if (this.pointers.size < 2) this.pinch = null;
      // 손을 뗀 자리만 기억하고 고르기는 click에서 한다. 여기서 화면을 바꾸면 뒤따르는 click이 새로 올라온 버튼을 누른다.
      this.pendingTap = had && this.moved < 10 && performance.now() - this.downAt < 500 ? p : null;
    };
    c.addEventListener("pointerup", up);
    c.addEventListener("click", () => {
      const t = this.pendingTap;
      this.pendingTap = null;
      if (t && this.onTap) this.onTap(t[0], t[1]);
    });
    c.addEventListener("pointercancel", (e) => this.pointers.delete(e.pointerId));
  }

  colorOf(s) {
    const st = this.status[s.seg];
    if (st === "done") return { c: BLUE, w: 5 };
    if (st === "partial" || st === "open" || st === "temp_block") return { c: BLUE, w: 5, dash: [8, 6] };
    if (st === "redo") return { c: DARK, w: 6, dash: [6, 5] };
    if (st === "not_path" || st === "no_entry") return { c: INK, w: 4, dash: [3, 6] };
    if (s.prio && s.prio <= 3) return { c: ORANGE, w: s.prio === 1 ? 6 : 4.5 };
    return { c: "rgba(255,255,255,0.75)", w: 2 };
  }

  draw() {
    const g = this.ctx;
    if (!g || !this.w) return;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#dfe3e6";
    g.fillRect(0, 0, this.c.width, this.c.height);
    g.setTransform(this.dpr * this.k, 0, 0, this.dpr * this.k, this.dpr * this.tx, this.dpr * this.ty);
    if (this.image) g.drawImage(this.image, 0, 0, this.pack.map.W, this.pack.map.H);
    g.lineCap = "round";
    g.lineJoin = "round";
    const px = 1 / this.k;
    const stroke = (path, color, width, dash) => {
      g.strokeStyle = color;
      g.lineWidth = width * px;
      g.setLineDash(dash ? dash.map((d) => d * px) : []);
      g.stroke(path);
    };
    this.pack.segs.forEach((s, i) => {
      if (!s.prio && this.status[s.seg] == null) stroke(this.paths[i], "rgba(255,255,255,0.75)", 2);
    });
    this.pack.segs.forEach((s, i) => {
      if (!s.prio && this.status[s.seg] == null) return;
      const st = this.colorOf(s);
      stroke(this.paths[i], "#ffffff", st.w + 2);
      stroke(this.paths[i], st.c, st.w, st.dash);
    });
    for (const line of this.extraLines) {
      const p = this.toPath(line.xy);
      stroke(p, "#ffffff", 6);
      stroke(p, line.color || BLUE, 4);
    }
    if (this.selected != null) {
      const s = this.selected;
      const p = this.toPath(s.xy);
      stroke(p, "#ffffff", 11);
      stroke(p, INK, 7);
      const ends = [[s.xy[0], s.xy[1], "A", s.a], [s.xy[s.xy.length - 2], s.xy[s.xy.length - 1], "B", s.b]];
      for (const [x, y, label, node] of ends) this.badge(x, y, label, node === this.selFrom);
    }
    if (this.draft && this.draft.length) {
      const p = this.toPath(this.draft);
      stroke(p, "#ffffff", 7);
      stroke(p, DARK, 4);
      for (let i = 0; i + 1 < this.draft.length; i += 2) this.dot(this.draft[i], this.draft[i + 1], 6, DARK);
    }
    if (this.gps) {
      const [x, y] = this.gps.px;
      const r = (this.gps.acc || 0) / this.pack.map.mpp;
      g.setLineDash([]);
      if (r > 0) {
        g.beginPath();
        g.arc(x, y, r, 0, Math.PI * 2);
        g.fillStyle = "rgba(31,95,191,0.15)";
        g.fill();
      }
      this.dot(x, y, 8, BLUE);
    }
  }

  dot(x, y, r, color) {
    const g = this.ctx;
    const px = 1 / this.k;
    g.setLineDash([]);
    g.beginPath();
    g.arc(x, y, r * px, 0, Math.PI * 2);
    g.fillStyle = color;
    g.fill();
    g.lineWidth = 2.5 * px;
    g.strokeStyle = "#ffffff";
    g.stroke();
  }

  badge(x, y, label, on) {
    const g = this.ctx;
    const px = 1 / this.k;
    g.setLineDash([]);
    g.beginPath();
    g.arc(x, y, 13 * px, 0, Math.PI * 2);
    g.fillStyle = on ? INK : "#ffffff";
    g.fill();
    g.lineWidth = 2.5 * px;
    g.strokeStyle = INK;
    g.stroke();
    g.fillStyle = on ? "#ffffff" : INK;
    g.font = `800 ${15 * px}px sans-serif`;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(label, x, y);
  }
}
