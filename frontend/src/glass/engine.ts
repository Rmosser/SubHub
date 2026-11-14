import { FRAGMENT_SHADER, UNIFORMS, VERTEX_SHADER } from "./shader";

// 玻璃工作台的外壳背景。移植自定稿原型 design/glass-workbench/final.html（新沙洲）。
//
// 材质按时态分：恒定的结构刻在玻璃上，此刻的状态是光，等人处理的事浮成一片玻璃（DESIGN.md）。
// 形由流成：导航的选中态不画在 UI 上，而是玻璃下细流里的一处沙洲；aria-current 移动，沙洲随之迁移。
//
// 清透（浅色，WebGL 可用）：deep 层作为纹理，全屏着色器合成床面、点阵、沙洲耙痕、左侧切边和窗光。
// 烟熏（深色）或无 WebGL：deep / near 两张 2D canvas + 磨砂层，沙洲在 near 上画。
// 外壳只负责床面和玻璃；页面里有含义的数据流（订阅源 → 节点池 → 设备）属于页面内容。
//
// 惯性按层分：字最快，洲和它近旁的水跟不上，洲的形和折射再慢半拍。托盘一动，洲连同近旁几根线落在字后面一点
// （往上走落在下方，往下走落在上方），落在后面的那一侧岸微微鼓出、岸上的色散略微拉开；停下后先追上字，形和光随后复原。
// 落后量随速度软饱和，最多是洲高的三成，洲始终包着字。一阶跟随不过冲，侧栏不动就什么都不发生。
// 主动换选中项时洲滑到新位置（略有表现力）：洲边几根线往变速的反方向让开再归位，先行一岸顶出约 1px；滚动没有这一层。
// 背景层是 sticky（不是 fixed）：系统回弹把侧栏和整块玻璃一起带走。回弹的位移量不到，
// 只照 Chromium mac 的回弹规则从触控板滚动推算，用来驱动落后量。
// 岸线是白光，贴岸挤密的水再透出一点深海青蓝（像玻璃切边露出的厚度），往洲尾渐浅；浓淡沿岸缓缓往下游流，换选中项时流得快。
//
// 动效政策：prefers-reduced-motion 时只在有变化时画一帧（沙洲直接成形、不流动、不滞后），页面隐藏时停掉 rAF。

type RGB = [number, number, number];
type Layer = { el: HTMLCanvasElement; scale: number; ctx: CanvasRenderingContext2D | null };
type Trans = "none" | "settle" | "wash";
interface Variant { b: number; tail: [number, number]; bank: number; sand: number; flank: number; tone: number; glint: number; peb: boolean; trans: Trans }
interface Sand { dx: number; dy: number; u: number; k: number; wait: number; off: number; dur: number; dr: number; tone: boolean; s: number; a: number; dv: number; d0: number }
interface Goal { cy: number; xl: number; xr: number; xs: number; xe: number; b: number }
// 画出来的洲 = 目标几何 g（字的位置）+ 换选中项时的滑移偏移 o（cy、xl、xr、b，临界阻尼归零）+ 跟不上字的落后量 L（只在 cy 上）
interface Island extends Goal { g: Goal; o: number[]; ov: number[]; L: number; U: number; Uh: number; qT: number; qB: number; lock: number; cyLast: number; rest: number; sc: number; el: Element; peb: boolean; t: number; amp: number; dead: boolean; td: number; pres: number; target: number; sand: Sand[] }
interface Glint { u: number; x: number; v: number; bank: number; isl: Island | null; al: number; y0: number }
interface Loose { x: number; y: number; v: number; life: number; s: number; a: number }

// 默认变体：清透 a（最轻：轻微分流、背水面一小片沙楔），烟熏 c（洲首次出现时从洲头往洲尾长出，岸上有光点，悬停处是水里的小石头）
// tail：洲尾至少多长（px）、至少是字宽的几倍
const VARIANTS: Record<"a" | "c", Variant> = {
  a: { b: 11.5, tail: [56, 1.2], bank: .5, sand: 110, flank: 0, tone: .5, glint: 0, peb: false, trans: "none" },
  c: { b: 15, tail: [100, 2], bank: 1, sand: 340, flank: .22, tone: 1, glint: 1, peb: true, trans: "wash" },
};

const PAD = 28, SP = 4, GROW = 240, WASH = 200;
// 落后：c 每 px/s 的速度落后多少（s）、v0 速度软饱和（px/s）、cap 落后上限（洲高 b 的几成）、
// att / rel 加速或换向时跟上的快慢、减速停下时追回字上的快慢（s，一阶）、tau 位移滤波（s）、sig 近旁的水跟着落后的范围（px）。
// 换选中项时的流线偏折：k 冲量增益、wu 固有频率、vg 速度软饱和、capU 偏折上限（px）、lam 偏折离洲心多远最大（px）、
// bump 先行一岸的弧度上限（px）、hl 光比形慢多少（s）
const LAG = { c: .012, v0: 600, cap: .32, att: .03, rel: .085, tau: .03, sig: 46, k: .5, wu: 18, vg: 900, capU: 3.6, lam: 10, bump: 1.2, hl: .07 };
// 岸线的深海青蓝（--g-rim，往洲尾渐变到 --g-rim-tail）：k 清透下的浓度、kd 烟熏下的浓度，bank 岸线白光比定稿加深多少倍；
// 浓淡沿岸起伏 amp，波长 wl（px），平时每秒往下游流 v px，换选中项时加到 vx，滚动时再加 vs
const RIM = { k: .38, kd: .5, bank: 1.15, amp: .2, wl: 110, v: 14, vx: 320, vs: 120 };
// 滚动中的形变与折射：跟着落后量（占上限的几成）走，跟上用 att、复原用 rel（s，一阶，比洲的位置慢半拍）；
// 落在后面那一侧的岸最多再鼓出洲高的 bulge 倍，色散最多加宽 disp 倍，深海青蓝最多加深 deep 倍
const FLEX = { att: .05, rel: .14, bulge: .18, disp: 1, deep: .4 };
// 换选中项：同一片洲沿直线滑到新位置，临界阻尼，约 0.3s 到位
const GLIDE = 17;
// 回弹的影子，照 Chromium mac 的 ElasticOverscrollControllerExponential：拉开 = 没被消费的滚动量 / k，
// 松手或进入惯性后 (s0 + amp·v0·t)·e^(-w·t)。dead 起拉前要攒够的量；coast 惯性判定要连续变慢的事件数，
// vmin 惯性起点的最低速度（px/s）；idle 推完多久没动静就悄悄归零（s）
const RB = { k: 20, w: 12.5, amp: .31, dead: 10, coast: 4, vmin: 300, idle: .35 };
const ITEM = "[data-glass-item]";
const ETCH = "[data-glass-etch]";

const hash = (k: number) => { const x = Math.sin(k * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
const lineY = (k: number) => k * SP + (hash(k) - .5) * 2.4;
const lineW = (k: number) => .4 + .6 * hash(k + 71.3);
const sm = (t: number) => t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);
// 绕流：离洲心 d 的水被推到 (d^1.5 + h^1.5)^(2/3)
const part = (d: number, h: number) => { const v = d * Math.sqrt(d) + h * Math.sqrt(h); return Math.cbrt(v * v); };
const rgba = (c: RGB, a: number) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
const lighten = (c: RGB, k: number): RGB => [0, 1, 2].map((i) => Math.round(c[i] + (255 - c[i]) * k)) as RGB;
const mixRGB = (a: RGB, b: RGB, t: number): RGB => [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * t)) as RGB;
function parseColor(v: string): RGB {
  v = v.trim();
  if (v[0] === "#") {
    if (v.length === 4) v = "#" + v.slice(1).split("").map((c) => c + c).join("");
    return [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16)) as RGB;
  }
  const m = (v.match(/[\d.]+/g) || ["0", "0", "0"]).slice(0, 3).map(Number);
  return [m[0] || 0, m[1] || 0, m[2] || 0];
}

export function mountGlass(host: HTMLElement, rail: HTMLElement): () => void {
  const root = document.documentElement;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const darkMQ = matchMedia("(prefers-color-scheme: dark)");
  const narrowMQ = matchMedia("(max-width: 900px)");
  const rnd = Math.random;
  const range = document.createRange();
  const cleanups: Array<() => void> = [];
  const on = <T extends EventTarget>(t: T, type: string, fn: EventListener, opts?: AddEventListenerOptions) => {
    t.addEventListener(type, fn, opts);
    cleanups.push(() => t.removeEventListener(type, fn, opts));
  };

  const make = <K extends "canvas" | "div">(tag: K, cls: string, parent: HTMLElement = host) => {
    const e = document.createElement(tag);
    e.className = cls;
    parent.appendChild(e);
    return e;
  };
  const deepEl = make("canvas", "glass-layer glass-layer--deep");
  const nearEl = make("canvas", "glass-layer glass-layer--near");
  const glc = make("canvas", "glass-shader");
  const frost = make("div", "glass-frost");
  const cloud = make("canvas", "glass-cloud", frost);
  const sheen = make("div", "glass-sheen", frost);
  make("div", "glass-edge");

  const L: { deep: Layer; near: Layer } = {
    deep: { el: deepEl, scale: .5, ctx: null },
    near: { el: nearEl, scale: 1, ctx: null },
  };
  let W = innerWidth, H = innerHeight;
  // 背景层在文档流里（sticky），所有坐标都相对它；它自己随系统回弹整体移动
  const HR = { left: 0, top: 0 };
  let theme = { dark: false, liquid: false, flow: [43, 95, 230] as RGB, flow2: [14, 159, 182] as RGB, rim: [50, 142, 184] as RGB, rimT: [89, 189, 208] as RGB };

  // ---- WebGL（清透） ----
  let gl: WebGLRenderingContext | null = null, glFresh = true, deepTex: WebGLTexture | null = null;
  const U: Record<string, WebGLUniformLocation | null> = {};
  function initGL() {
    let g: WebGLRenderingContext | null = null;
    try { g = glc.getContext("webgl", { alpha: false, antialias: false, depth: false, stencil: false, premultipliedAlpha: false }); } catch { return; }
    if (!g || g.isContextLost()) return;
    const ctx = g;
    const shader = (type: number, src: string) => {
      const o = ctx.createShader(type);
      if (!o) throw new Error("shader");
      ctx.shaderSource(o, src); ctx.compileShader(o);
      if (!ctx.getShaderParameter(o, ctx.COMPILE_STATUS)) throw new Error(ctx.getShaderInfoLog(o) || "compile");
      return o;
    };
    const prog = ctx.createProgram();
    if (!prog) return;
    try {
      ctx.attachShader(prog, shader(ctx.VERTEX_SHADER, VERTEX_SHADER));
      ctx.attachShader(prog, shader(ctx.FRAGMENT_SHADER, FRAGMENT_SHADER));
      ctx.linkProgram(prog);
      if (!ctx.getProgramParameter(prog, ctx.LINK_STATUS)) throw new Error(ctx.getProgramInfoLog(prog) || "link");
    } catch {
      // 着色器不可用时安静地退回磨砂，不打扰控制台
      return;
    }
    ctx.useProgram(prog);
    ctx.bindBuffer(ctx.ARRAY_BUFFER, ctx.createBuffer());
    ctx.bufferData(ctx.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), ctx.STATIC_DRAW);
    const loc = ctx.getAttribLocation(prog, "a");
    ctx.enableVertexAttribArray(loc); ctx.vertexAttribPointer(loc, 2, ctx.FLOAT, false, 0, 0);
    for (const n of UNIFORMS) U[n] = ctx.getUniformLocation(prog, n);
    ctx.pixelStorei(ctx.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    ctx.activeTexture(ctx.TEXTURE0);
    deepTex = ctx.createTexture();
    ctx.bindTexture(ctx.TEXTURE_2D, deepTex);
    for (const [p, v] of [[ctx.TEXTURE_MIN_FILTER, ctx.LINEAR], [ctx.TEXTURE_MAG_FILTER, ctx.LINEAR], [ctx.TEXTURE_WRAP_S, ctx.CLAMP_TO_EDGE], [ctx.TEXTURE_WRAP_T, ctx.CLAMP_TO_EDGE]]) ctx.texParameteri(ctx.TEXTURE_2D, p, v);
    ctx.uniform1i(U.uDeep, 0);
    gl = ctx; glFresh = true;
  }
  function glColors(cs: CSSStyleDeclaration) {
    if (!gl) return;
    const v = (k: string) => parseColor(cs.getPropertyValue(k)).map((x) => x / 255);
    gl.uniform3fv(U.uBedHi, v("--g-bed-hi")); gl.uniform3fv(U.uBedLo, v("--g-bed-lo")); gl.uniform3fv(U.uDot, v("--g-bed-dot"));
    gl.uniform3fv(U.uTint, v("--g-glass-tint")); gl.uniform3fv(U.uEdgeTint, v("--g-edge-tint"));
    gl.uniform3fv(U.uRimC, theme.rim.map((x) => x / 255)); gl.uniform3fv(U.uRimT, theme.rimT.map((x) => x / 255));
  }

  function readTheme() {
    const dark = getComputedStyle(root).getPropertyValue("--g-is-dark").trim() === "1";
    const liquid = !dark && !!gl;
    if (liquid) root.dataset.glassMat = "liquid"; else delete root.dataset.glassMat;
    const cs = getComputedStyle(root);
    const tok = (k: string, d: RGB) => cs.getPropertyValue(k).trim() ? parseColor(cs.getPropertyValue(k)) : d;
    theme = {
      dark, liquid, flow: parseColor(cs.getPropertyValue("--g-flow")), flow2: parseColor(cs.getPropertyValue("--g-flow-2")),
      rim: tok("--g-rim", [50, 142, 184]), rimT: tok("--g-rim-tail", [89, 189, 208]),
    };
    if (liquid) glColors(cs);
  }

  // 玻璃厚度不均：一次性画好的云纹，固定种子
  function drawCloud() {
    const w = cloud.width = Math.max(1, Math.round(W / 4)), h = cloud.height = Math.max(1, Math.round(H / 4));
    const c = cloud.getContext("2d");
    if (!c) return;
    let s = 7;
    const r = () => (s = (s * 16807) % 2147483647) / 2147483647;
    c.clearRect(0, 0, w, h);
    for (let i = 0; i < 26; i++) {
      const x = r() * w, y = r() * h, rad = (.15 + r() * .35) * Math.max(w, h), light = r() > .5;
      const g = c.createRadialGradient(x, y, 0, x, y, rad);
      g.addColorStop(0, light ? "rgba(255,255,255,.24)" : "rgba(0,0,0,.2)"); g.addColorStop(1, "rgba(0,0,0,0)");
      c.fillStyle = g; c.fillRect(0, 0, w, h);
    }
  }
  function resize() {
    W = host.clientWidth || innerWidth; H = host.clientHeight || innerHeight;
    const dpr = window.devicePixelRatio || 1;
    L.deep.scale = theme.liquid ? .25 : .5;
    L.near.scale = theme.liquid ? .25 : Math.min(dpr, 2);
    if (gl) { const s = Math.min(dpr, 2); glc.width = Math.max(1, Math.round(W * s)); glc.height = Math.max(1, Math.round(H * s)); glFresh = true; }
    for (const l of [L.deep, L.near]) {
      l.el.width = Math.max(1, Math.round((W + PAD * 2) * l.scale));
      l.el.height = Math.max(1, Math.round((H + PAD * 2) * l.scale));
      l.ctx = l.el.getContext("2d");
    }
    if (!theme.liquid) drawCloud();
  }
  function begin(l: Layer) {
    const c = l.ctx;
    if (!c) return null;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.globalCompositeOperation = "source-over";
    c.clearRect(0, 0, l.el.width, l.el.height);
    c.setTransform(l.scale, 0, 0, l.scale, PAD * l.scale, PAD * l.scale);
    c.globalCompositeOperation = "lighter";
    c.lineCap = "round";
    return c;
  }

  // ---- 深处：从左往右的细颗粒缓流（床面的一部分；总量以后可绑定真实拉取速率） ----
  const lanes = Array.from({ length: 8 }, (_, i) => ({
    y: .1 + i * .115 + (rnd() - .5) * .05, amp: 18 + rnd() * 30, f: .0018 + rnd() * .0015, ph: rnd() * 6.28,
    c: i % 3 === 1 ? "flow2" as const : "flow" as const,
    dots: Array.from({ length: 36 }, () => ({ x: rnd(), v: 12 + rnd() * 28, o: (rnd() - .5) * 28, s: 1.3 + rnd() * 1.3, a: .25 + rnd() * .5 })),
  }));
  let T = 0, deepAcc = 0;
  function drawDeep(dt: number, moving: boolean) {
    deepAcc += dt;
    if (moving && deepAcc < 1 / 30) return false;
    const step = deepAcc; deepAcc = 0;
    const c = begin(L.deep);
    if (!c) return false;
    const span = W + 200, liquid = theme.liquid;
    lanes.forEach((ln, i) => {
      const col = theme[ln.c];
      const yAt = (x: number) => ln.y * H + ln.amp * Math.sin(x * ln.f + ln.ph + T * .05);
      c.beginPath();
      for (let x = -60; x <= W + 60; x += 40) { const y = yAt(x); if (x === -60) c.moveTo(x, y); else c.lineTo(x, y); }
      if (liquid) {
        const m = ((ln.ph / 6.28 + T * .012) % 1.6) - .3, gr = c.createLinearGradient((m - .3) * W, 0, (m + .3) * W, 0);
        gr.addColorStop(0, rgba(col, 0)); gr.addColorStop(.5, rgba(col, i % 2 ? .07 : .045)); gr.addColorStop(1, rgba(col, 0));
        c.strokeStyle = gr; c.lineWidth = 110; c.stroke(); c.lineWidth = 44; c.stroke();
      } else { c.strokeStyle = rgba(col, theme.dark ? .07 : .12); c.lineWidth = 40; c.stroke(); }
      for (const d of ln.dots) {
        if (moving) { d.x += d.v * step / span; if (d.x > 1) d.x -= 1; }
        const tail = liquid ? 40 + d.v * 2.4 : 14, x = d.x * span - 100, y = yAt(x) + d.o, y0 = yAt(x - tail) + d.o;
        if (liquid) { c.strokeStyle = rgba(col, d.a * .13); c.lineWidth = d.s * 2.6; }
        else { c.strokeStyle = rgba(lighten(col, theme.dark ? 0 : .4), d.a * (theme.dark ? .7 : 1)); c.lineWidth = d.s * (theme.dark ? 1 : 1.3); }
        c.beginPath(); c.moveTo(x - tail, y0); c.lineTo(x, y); c.stroke();
      }
    });
    return true;
  }

  // ---- 沙洲 ----
  let RV: Variant | null = null;
  let navHover: Element | null = null;
  const riv: { isl: Island[]; el: Element | null; hov: Element | null; parts: Glint[] | null; loose: Loose[]; first: boolean; railR: number; spr: HTMLCanvasElement | null; sprKey: string } =
    { isl: [], el: null, hov: null, parts: null, loose: [], first: true, railR: 232, spr: null, sprKey: "" };
  const V = () => RV as Variant;
  function islGoal(el: Element, peb: boolean): Goal | null {
    const ir = el.getBoundingClientRect();
    if (!ir.width) return null;
    range.selectNodeContents(el);
    const tr = range.getBoundingClientRect(), tw = tr.right - tr.left, narrow = narrowMQ.matches, rv = V();
    const l = tr.left - HR.left, r = tr.right - HR.left;
    return {
      cy: (ir.top + ir.bottom) / 2 - HR.top, xl: l, xr: r, xs: l - (peb ? 14 : narrow ? 14 : 15),
      xe: Math.min(r + (peb ? 30 : narrow ? 18 : Math.max(rv.tail[0], rv.tail[1] * tw)), riv.railR + 8),
      b: peb ? 6.5 : narrow ? Math.min(13, rv.b) : rv.b,
    };
  }
  // 水滴形：洲头圆、字底下平、背水的一端拖成长尾，尾巴收到 0 时斜率也是 0，绕开的线平顺地并回去
  function islShape(i: Goal, x: number) {
    if (x <= i.xs || x >= i.xe) return 0;
    const xn = i.xl + 4;
    return x < xn ? Math.pow(Math.sin(Math.PI / 2 * (x - i.xs) / (xn - i.xs)), .8) : x < i.xr + 2 ? 1 : Math.pow(1 - Math.pow((x - i.xr - 2) / (i.xe - i.xr - 2), 1.6), 1.25);
  }
  // 流线偏折的范围：上游 30px 渐入，下游带一段 70px 的尾流
  const islFx = (i: Goal, x: number) => sm((x - i.xs + 30) / 36) * (1 - sm((x - i.xe + 6) / 76));
  // 离洲心 r·lam 处偏折多少：洲心为 0（线不会跨到另一岸），lam 处最大，再远渐弱
  const bend = (r: number) => r * r * Math.exp(1 - r * r);
  const place = (i: Island) => {
    const g = i.g, o = i.o;
    i.cy = g.cy + o[0] + i.L; i.xl = g.xl + o[1]; i.xr = g.xr + o[2]; i.xs = g.xs + o[1]; i.xe = g.xe + o[2]; i.b = g.b + o[3];
  };
  // 近旁的水跟着洲一起落后：离洲心越近跟得越紧（洲心处整整一份），线就不会被洲心扫过；线格松开时不跟
  const drag = (i: Island, y0: number) => { if (!i.L) return 0; const q = (y0 - i.cy + i.L) / LAG.sig; return i.L * i.lock * Math.exp(-q * q); };
  function islEnv(i: Island, x: number) {
    if (i.peb || V().trans !== "wash") return i.amp;
    let e = i.t >= 9 ? 1 : sm((i.xs + GROW * i.t - x) / 90);
    if (i.dead) e *= sm((x - (i.xs - 110 + WASH * i.td)) / 110);
    return e;
  }
  // 字底下的单拱：鼓包只出现在字的正下方，中间最高，洲尾不跟着胀
  const islWin = (i: Island, x: number) => { const t = (x - (i.xl + i.xr) / 2) / ((i.xr - i.xl) / 2 + 14); return Math.abs(t) < 1 ? (1 - t * t) * (1 - t * t) : 0; };
  const islH = (i: Island, x: number, below: boolean) => {
    const s = islShape(i, x);
    if (s <= 0) return 0;
    const q = below ? i.qB : i.qT;
    return (i.b * s + (q > 0 ? q * islWin(i, x) : 0)) * islEnv(i, x);
  };
  function riverY(y0: number, x: number) {
    let y = y0 + 1.1 * Math.sin(x * .012 + y0 * .07 + T * .35);
    for (const i of riv.isl) {
      const dr = drag(i, y0);
      y += dr;
      // 先在没被推开的水里偏折，再绕洲分流：岸线（洲心那几根）不动，往外几根线跟着偏
      if (i.U) { const f = islFx(i, x); if (f > 0) y += i.U * f * bend((y - i.cy) / LAG.lam); }
      const below = y0 + dr >= i.cy, h = islH(i, x, below);
      if (h > 0) y = i.cy + (below ? 1 : -1) * part(Math.abs(y - i.cy), h);
    }
    return y;
  }
  function riverSpeed(y0: number, x: number) {
    let k = 1;
    for (const i of riv.isl) {
      const e = i.peb ? i.amp * .4 : i.pres;
      if (e < .02) continue;
      const d0 = y0 + drag(i, y0) - i.cy, h = islH(i, x, d0 >= 0), near = Math.exp(-(d0 * d0) / (i.b * i.b * 1.6)), n = (x - i.xs) / 16;
      if (h > 0) k *= Math.min(1.6, Math.sqrt(part(Math.abs(d0), h) / Math.max(Math.abs(d0), 4)));
      k *= 1 - .6 * e * near * Math.exp(-n * n);
      if (x > i.xe) k *= 1 - .5 * e * near * Math.exp(-(x - i.xe) / 100);
    }
    return Math.max(.2, k);
  }
  // 沙：一部分贴着两岸（字的上下方），其余落在字后面那一端的浅滩里，都不压字
  function sandSpot(i: Goal, narrow: boolean) {
    if (rnd() < (narrow ? .5 : V().flank)) {
      const x = i.xl - 10 + (i.xr - i.xl + 14) * rnd(), h = i.b * islShape(i, x);
      return { dx: x - i.xr, dy: (rnd() < .5 ? -1 : 1) * h * (.68 + .26 * rnd()), u: .3 * rnd() };
    }
    for (let t = 0; t < 6; t++) {
      const u = Math.pow(rnd(), 1.7), x = i.xr - 2 + (i.xe - i.xr - 2) * u, dy = (rnd() * 2 - 1) * i.b * islShape(i, x) * .9;
      if (x - i.xr > 13 - Math.abs(dy) * 1.1) return { dx: x - i.xr, dy, u };
    }
    return { dx: 16, dy: (rnd() * 2 - 1) * i.b * .8, u: .1 };
  }
  const blank = () => ({ o: [0, 0, 0, 0], ov: [0, 0, 0, 0], L: 0, U: 0, Uh: 0, qT: 0, qB: 0, lock: 1, rest: 1, sc: 0 });
  function newIsland(el: Element, formed: boolean): Island | null {
    const g = islGoal(el, false);
    if (!g) return null;
    const narrow = narrowMQ.matches, tr = V().trans;
    const i: Island = { ...g, g, ...blank(), cyLast: g.cy, el, peb: false, t: formed ? 9 : 0, amp: formed ? 1 : 0, dead: false, td: 0, pres: formed ? 1 : 0, target: 1, sand: [] };
    for (let k = 0, n = Math.round(V().sand * (narrow ? .4 : 1)); k < n; k++) {
      const sp = sandSpot(i, narrow);
      const s: Sand = { ...sp, k: 1, wait: 0, off: 0, dur: 1, dr: 0, tone: k % 5 === 0, s: 0, a: 0, dv: 0, d0: 0 };
      s.s = .7 + 1.3 * Math.pow(rnd(), 2.5) * (1 - .6 * s.u); s.a = (.95 - .45 * s.u) * (.6 + .4 * rnd());
      s.dv = 10 + rnd() * 20; s.d0 = (s.dy < 0 ? -1 : 1) * (.5 + rnd() * 5);
      if (!formed && tr === "settle") Object.assign(s, { k: 0, wait: .2 + s.u + rnd() * .4, off: 6 + rnd() * 12, dur: .8 + rnd() * .5 });
      if (!formed && tr === "wash") Object.assign(s, { k: 0, wait: Math.max(0, i.xr + s.dx - i.xs) / GROW + .15 + rnd() * .4, off: 24 + rnd() * 40, dur: .7 + rnd() * .5 });
      i.sand.push(s);
    }
    return i;
  }
  function sandAt(i: Island, s: Sand): [number, number, number] {
    const tx = i.xr + s.dx + s.dr, e = 1 - (1 - s.k) * (1 - s.k), x = tx - s.off * (1 - e);
    // 贴岸的粒随鼓包外移，洲面上的粒只随洲心走
    const q = s.dy < 0 ? i.qT : i.qB;
    const ty = i.cy + s.dy + (q > 0 && Math.abs(s.dy) > .6 * i.b * islShape(i, tx) ? Math.sign(s.dy) * q * islWin(i, tx) : 0);
    const wash = V().trans === "wash";
    const y = s.k < 1 && wash ? riverY(i.cy - i.L + s.d0, x) * (1 - sm(e * 1.3)) + ty * sm(e * 1.3) : ty;
    return [x, y, Math.min(1, s.k * 2.5) * (wash ? 1 : i.amp * (i.dead ? i.amp : 1))];
  }
  const current = () => rail.querySelector(`${ITEM}[aria-current="page"]`);
  const topIsland = () => { let top: Island | null = null; for (const i of riv.isl) if (!i.peb && !i.dead) top = i; return top; };
  // ---- 惯性：L 是洲落在字后面的量（px，正值 = 洲在字下方，字正在往上走）；u 是换选中项时洲边流线的偏折（正值 = 线往下偏）；
  // f 是滚动中的形变与折射（落后量占上限的几成，带符号，比 L 慢半拍） ----
  const lag = { L: 0, sf: NaN, sfPrev: NaN, u: 0, v: 0, gf: NaN, gfPrev: NaN, vPrev: 0, isl: null as Island | null, ex: 0, uh: 0, f: 0 };
  // 深海青蓝沿岸流动的相位（px）
  const rim = { ph: 0 };
  let moveT = -1e9;
  // st：0 静止，1 手指在推，2 弹回（松手或进入惯性）；s 是推算出的回弹位移（px，正值 = 内容往下）
  const rb = { s: 0, f: 0, pend: 0, st: 0, t: -1, v: 0, v1: 0, run: 0, s0: 0, v0: 0, t0: 0, pos: 0, root: false, notch: false, quiet: false };
  const rbReset = (quiet: boolean) => { rb.s = rb.f = rb.pend = 0; rb.st = 0; if (quiet) rb.quiet = true; };
  function stepRB(now: number) {
    const t = now / 1000;
    // 推完很久没动静：多半早松手了（没有惯性的松手看不见），悄悄归零，不给洲冲量
    if (rb.st === 1 && t - rb.t > RB.idle) rbReset(true);
    if (rb.st === 2) {
      const k = Math.max(0, t - rb.t0);
      rb.s = (rb.s0 + RB.amp * rb.v0 * k) * Math.exp(-RB.w * k);
      if ((Math.abs(rb.s) < .5 && k > .02) || rb.s * rb.s0 < 0) rbReset(false);
    }
  }
  function stepLag(dt: number, moving: boolean) {
    const top = topIsland();
    if (!moving || !top || dt <= 1e-4) {
      lag.L = lag.u = lag.v = lag.uh = lag.ex = lag.f = 0; lag.sf = lag.gf = NaN; rbReset(false); rb.quiet = false;
      for (const i of riv.isl) { i.L = i.U = i.Uh = i.qT = i.qB = i.sc = 0; place(i); }
      return;
    }
    const now = performance.now();
    stepRB(now);
    // 换了一片洲时从头来，不注入冲量
    const fresh = top !== lag.isl || lag.sf !== lag.sf;
    if (fresh) { lag.isl = top; lag.L = lag.u = lag.v = lag.vPrev = lag.f = 0; }
    // 只有真的在动（最近有 scroll 事件、回弹还没停，或洲正滑向新的选中项）才算运动；字体加载、换行这类跳动只重新对齐
    const glide = Math.abs(top.o[0]) > .3 || Math.abs(top.ov[0]) > 2, still = rb.quiet || (now - moveT > 150 && !rb.st);
    // 落后：驱动量是字在屏幕上的位置（实测 + 量不到的回弹），不含换选中项的滑移。速度越快落得越远，软饱和
    const s = top.g.cy + HR.top + rb.s;
    let want = 0;
    if (fresh || still || Math.abs(s - lag.sfPrev) > 120) lag.sf = lag.sfPrev = s;
    else {
      lag.sf += (s - lag.sf) * (1 - Math.exp(-dt / LAG.tau));
      const v = (lag.sf - lag.sfPrev) / dt;
      lag.sfPrev = lag.sf;
      want = -LAG.c * LAG.v0 * Math.tanh(v / LAG.v0);
    }
    // 加速、换向时跟得快（换向不会有一下跑到字前面），减速、停下时慢慢追回字上——跟不上的那一下就在这儿；一阶，不过冲。
    // 再软饱和一次，越快越接近上限、不越过
    const back = want * lag.L >= 0 && Math.abs(want) < Math.abs(lag.L);
    lag.L += (want - lag.L) * (1 - Math.exp(-dt / (back ? LAG.rel : LAG.att)));
    if (!want && Math.abs(lag.L) < .01) lag.L = 0;
    const capL = LAG.cap * top.g.b;
    top.L = capL * Math.tanh(lag.L / capL);
    // 形和折射跟着落后量走、比洲的位置慢半拍：换向时从 0 平顺地过到另一侧，停下后洲先追上字，形和光随后复原
    const fw = top.L / capL;
    lag.f += (fw - lag.f) * (1 - Math.exp(-dt / (fw * lag.f >= 0 && Math.abs(fw) > Math.abs(lag.f) ? FLEX.att : FLEX.rel)));
    if (!fw && Math.abs(lag.f) < .005) lag.f = 0;
    // 只在换选中项、洲滑过去时：洲相对床面变速 = 给周围的水一个反向冲量；阻尼作用在相对速度上，匀速时偏折归零。
    // 滚动（回弹、窄屏随页面滚、侧栏自己滚）不给这一层，只有落后，免得先行一岸鼓出来像洲跑到了字前面
    const gp = top.g.cy + top.o[0];
    if (fresh || !glide || Math.abs(gp - lag.gfPrev) > 120) { lag.gf = lag.gfPrev = gp; lag.vPrev = 0; }
    else {
      lag.gf += (gp - lag.gf) * (1 - Math.exp(-dt / LAG.tau));
      const v = (lag.gf - lag.gfPrev) / dt, vs = LAG.vg * Math.tanh(v / LAG.vg);
      lag.gfPrev = lag.gf;
      lag.v -= LAG.k * (vs - lag.vPrev); lag.vPrev = vs;
    }
    for (let k = 0, h = dt / 3; k < 3; k++) { lag.v += (-LAG.wu * LAG.wu * lag.u - 2 * LAG.wu * lag.v) * h; lag.u += lag.v * h; }
    if (Math.abs(lag.u) < .02 && Math.abs(lag.v) < .5) lag.u = lag.v = 0;
    rb.quiet = false;
    const U = LAG.capU * Math.tanh(lag.u / LAG.capU);
    // 岸上的光比线慢一点收拢
    lag.uh += (U - lag.uh) * (1 - Math.exp(-dt / LAG.hl));
    // 洲往哪边滑，先行那一岸就顶出一点弧度；滚动时落在后面的那一岸鼓出一点（往上走是下岸）
    const q = LAG.bump * sm(Math.abs(U) / LAG.capU) * top.pres, fb = FLEX.bulge * top.g.b * lag.f * top.pres;
    top.U = U; top.Uh = lag.uh; top.qT = (U > 0 ? q : 0) + Math.max(0, -fb); top.qB = (U < 0 ? q : 0) + Math.max(0, fb);
    top.sc = Math.abs(lag.f);
    // 深海青蓝的浓淡沿岸往下游流：滑向新选中项时流得快，滑完 0.25s 内慢下来；滚动时也快一点
    lag.ex += ((glide ? 1 : 0) - lag.ex) * (1 - Math.exp(-dt / (glide ? .04 : .25)));
    rim.ph = (rim.ph + dt * (RIM.v + (RIM.vx - RIM.v) * lag.ex + RIM.vs * top.sc)) % RIM.wl;
    // 正在消失的洲、悬停的小石慢慢回正
    const fade = Math.exp(-8 * dt);
    for (const i of riv.isl) { if (i !== top) { i.L *= fade; i.U *= fade; i.Uh *= fade; i.qT *= fade; i.qB *= fade; i.sc *= fade; } place(i); }
  }
  function stepRiver(dt: number, moving: boolean) {
    const rv = theme.dark ? VARIANTS.c : VARIANTS.a;
    if (rv !== RV) { RV = rv; riv.isl = []; riv.loose = []; riv.parts = null; riv.el = riv.hov = null; riv.first = true; }
    const el = current(), narrow = narrowMQ.matches, tr = rv.trans;
    const hb = host.getBoundingClientRect();
    HR.left = hb.left; HR.top = hb.top;
    riv.railR = narrow ? 1e5 : rail.getBoundingClientRect().right - HR.left;
    if (el !== riv.el) {
      const top = topIsland(), g = el && islGoal(el, false);
      if (el && g && top && moving && top.pres > .5) {
        // 主动换选中项：同一片洲滑过去。偏移接住当前画出的位置，速度也接着走，中途再点别处就直接改道
        top.o[0] = top.cy - top.L - g.cy; top.o[1] = top.xl - g.xl; top.o[2] = top.xr - g.xr; top.o[3] = top.b - g.b;
        top.el = el; top.g = g;
      } else {
        for (const i of riv.isl) if (!i.peb && !i.dead) { i.dead = true; i.td = 0; }
        const i = el && newIsland(el, riv.first || !moving);
        if (i) riv.isl.push(i);
      }
      riv.el = el; riv.first = false;
    }
    const hv = rv.peb && navHover && navHover !== el && !narrow ? navHover : null;
    if (hv !== riv.hov) {
      for (const i of riv.isl) if (i.peb) i.target = 0;
      const p = hv && riv.isl.find((i) => i.peb && i.el === hv), g = hv && !p ? islGoal(hv, true) : null;
      if (p) p.target = 1;
      else if (hv && g) riv.isl.unshift({ ...g, g, ...blank(), cyLast: g.cy, el: hv, peb: true, t: 9, amp: 0, dead: false, td: 0, pres: 0, target: 1, sand: [] });
      riv.hov = hv;
    }
    for (const i of riv.isl) {
      const g = islGoal(i.el, i.peb);
      if (g) i.g = g;
      const o = i.o, ov = i.ov;
      if (moving) {
        for (let n = 0, h = dt / 3; n < 3; n++) for (let k = 0; k < 4; k++) { ov[k] += (-GLIDE * GLIDE * o[k] - 2 * GLIDE * ov[k]) * h; o[k] += ov[k] * h; }
        for (let k = 0; k < 4; k++) if (Math.abs(o[k]) < .05 && Math.abs(ov[k]) < .5) o[k] = ov[k] = 0;
      } else { o.fill(0); ov.fill(0); }
      place(i);
      // 洲相对床面在动（滑向新的选中项、侧栏自己在滚）时松开线格相位锁，线留在水里；静止 0.12s 后再慢慢锁回。
      // 落后不算：近旁的水跟着洲一起落后，线格不松
      const c0 = i.g.cy + o[0], mv = moving && dt > 1e-4 ? Math.abs(c0 - i.cyLast) / dt : 0;
      i.cyLast = c0;
      i.rest = mv > 3 ? 0 : i.rest + dt;
      const lk = i.rest > .12 ? 1 : 0;
      i.lock = moving ? i.lock + (lk - i.lock) * (1 - Math.exp(-dt / (lk ? .16 : .05))) : 1;
      if (i.peb) { i.amp = moving ? i.amp + (i.target - i.amp) * Math.min(1, dt * 6) : i.target; continue; }
      if (moving) { i.t += dt; if (i.dead) i.td += dt; } else { i.t = 9; if (i.dead) i.td = 9; }
      const to = i.dead ? 0 : 1;
      i.amp = moving ? i.amp + (to - i.amp) * Math.min(1, dt * (tr === "none" ? 6 : to ? 2.2 : 2.6)) : to;
      i.pres = islEnv(i, (i.xl + i.xr) / 2);
      for (let n = i.sand.length - 1; n >= 0; n--) {
        const s = i.sand[n];
        if (!moving) { s.k = 1; s.wait = 0; continue; }
        if (i.dead) {
          if (tr === "settle") s.dr += s.dv * dt;
          else if (tr === "wash") {
            const q = sandAt(i, s);
            if (s.k > 0 && islEnv(i, q[0]) > .5) continue;
            if (s.k > .4) riv.loose.push({ x: q[0], y: q[1], v: 40 + rnd() * 50, life: 1, s: s.s, a: s.a });
            i.sand.splice(n, 1);
          }
        } else if (s.wait > 0) s.wait -= dt;
        else if (s.k < 1) s.k = Math.min(1, s.k + dt / s.dur);
      }
    }
    riv.isl = riv.isl.filter((i) => i.peb ? i.target > 0 || i.amp > .01 : !i.dead || (tr === "wash" ? i.td < (i.xe - i.xs + 110) / WASH + .05 : i.amp > .01));
    stepLag(dt, moving);
    if (moving) for (const p of riv.loose) { p.x += p.v * dt; p.life -= dt * 1.1; } else riv.loose.length = 0;
    riv.loose = riv.loose.filter((p) => p.life > 0);
    if (theme.liquid) return;
    // 2D：水面上的光点，烟熏下有一小部分贴着当前沙洲的岸走
    if (!riv.parts) riv.parts = Array.from({ length: 380 }, (_, n) => ({ u: rnd(), x: rnd() * 420 - 20, v: 34 + rnd() * 18, bank: n < 60 ? (n % 2 ? -1 : 1) * (.5 + rnd() * 2.5) : 0, isl: null, al: 0, y0: NaN }));
    const top = topIsland();
    const xb = narrow ? W + 20 : 380, ya = narrow && top ? top.cy - 70 : -12, yb = narrow && top ? top.cy + 70 : H + 12;
    for (const p of riv.parts) {
      if (p.bank) {
        // 认的是哪一片洲，就跟着那片洲走：洲滑向新的选中项时，岸上的光点一起滑过去
        if (top && p.isl === top) p.al = Math.min(1, p.al + (moving ? dt * 1.2 : 1));
        else if ((p.al -= moving ? dt * 3 : 1) <= 0) { p.al = 0; p.isl = top; p.x = rnd() * (xb + 20) - 20; }
        p.y0 = p.isl ? p.isl.cy - p.isl.L + p.bank : NaN;
      } else p.y0 = lineY(Math.round((ya + p.u * (yb - ya)) / SP));
      if (moving && p.y0 === p.y0) { p.x += p.v * riverSpeed(p.y0, p.x) * dt; if (p.x > xb + 10) p.x -= xb + 30; }
    }
  }
  function drawRiver(c: CanvasRenderingContext2D) {
    if (!riv.isl.length && !riv.loose.length) return;
    const narrow = narrowMQ.matches, col = theme.flow, dark = theme.dark, rv = V();
    const top = topIsland();
    const cyRef = top ? top.cy : riv.isl.length ? riv.isl[riv.isl.length - 1].cy : H / 2;
    const ya = narrow ? cyRef - 70 : -12, yb = narrow ? cyRef + 70 : H + 12, xb = narrow ? W + 20 : 380, fin = narrow ? 40 : 18, fout = narrow ? W * .35 : 170;
    const fade = (x: number) => Math.max(0, Math.min(1, x / fin, (xb - x) / fout));
    const P = dark ? { far: .16, near: .2, bank: 1, lw: 1.4, glint: .6, gw: 1.6, hi: .25 } : { far: .05, near: .08, bank: .7, lw: 1, glint: .5, gw: 1.2, hi: 0 };
    const gr = c.createLinearGradient(0, 0, xb, 0);
    gr.addColorStop(0, rgba(col, 0)); gr.addColorStop(fin / xb, rgba(col, 1)); gr.addColorStop(1 - fout / xb, rgba(col, 1)); gr.addColorStop(1, rgba(col, 0));
    const emOf = (y0: number) => { let e = 0; for (const i of riv.isl) { const q = (y0 - i.cy + i.L) / (i.peb ? 20 : 46); e = Math.max(e, (i.peb ? .4 * i.amp : i.pres) * Math.exp(-q * q)); } return e; };
    const fyOf = (y0: number) => narrow ? Math.exp(-Math.pow((y0 - cyRef) / 52, 2)) : 1;
    const colB = lighten(col, P.hi), bankA = P.bank * rv.bank * RIM.bank;
    // 深海青蓝：洲身取 rim，往洲尾渐变到 rimT；浓淡沿岸起伏、往下游流，滚动时略深
    const rimK = (i: Island, x: number) => (dark ? RIM.kd : RIM.k) * (1 + FLEX.deep * i.sc) * (1 + RIM.amp * Math.sin(6.2832 * (x - rim.ph) / RIM.wl));
    const rimC = (i: Island, x: number) => mixRGB(theme.rim, theme.rimT, sm((x - i.xr) / Math.max(1, i.xe - i.xr)));
    c.lineWidth = P.lw;
    for (let k = Math.floor(ya / SP); k <= Math.ceil(yb / SP); k++) {
      const y0 = lineY(k), w = lineW(k), fy = fyOf(y0), em = emOf(y0);
      if (P.far * w * fy < .004 && em < .03) continue;
      if (em < .03) { c.strokeStyle = gr; c.globalAlpha = P.far * w * fy; }
      else {
        // 岸线不是另画的：同一根流线，挤得越密就越亮
        const g = c.createLinearGradient(0, 0, xb, 0);
        for (let x = 0; x <= xb; x += 10) {
          let bank = 0, calm = 1, by: Island | null = null;
          for (const i of riv.isl) {
            const r = y0 + drag(i, y0) - i.cy, h = islH(i, x, r >= 0), d = Math.abs(r);
            if (h > .4) {
              const bk = Math.min(1, (Math.sqrt(part(d, h) / Math.max(d, .8)) - 1) / 1.6) * Math.min(1, h / 7) * (i.peb ? .5 : 1);
              if (bk > bank) { bank = bk; by = i.peb ? null : i; }
              // 洲在床面上移动时，正擦过洲心的那根线先淡出，不从一岸跳到另一岸
              if (i.lock < 1) calm *= 1 - (1 - i.lock) * (1 - sm((d - .3) / 1.2));
            } else if (!i.peb && x >= i.xe) calm *= 1 - .7 * i.pres * Math.exp(-(d * d) / 90) * Math.exp(-(x - i.xe) / 70);
          }
          const base = bank > .4 ? colB : col, sc = by && bank > .25 ? mixRGB(base, rimC(by, x), Math.min(1, rimK(by, x) * sm((bank - .25) / .35))) : base;
          // 滚动时岸线略亮一点：2D 没有色散，折射的那一份落在亮度上
          const ba = bankA * Math.sqrt(bank) * (1 + .25 * (by ? by.sc : 0));
          g.addColorStop(Math.min(1, x / xb), rgba(sc, (P.far * w + P.near * w * em * sm((x - 14) / 30) + ba) * calm * fade(x) * fy));
        }
        c.strokeStyle = g; c.globalAlpha = 1;
      }
      c.beginPath();
      for (let x = 0; x <= xb; x += 4) { const y = riverY(y0, x); if (x) c.lineTo(x, y); else c.moveTo(x, y); }
      c.stroke();
    }
    c.lineWidth = P.gw; c.strokeStyle = rgba(lighten(col, dark ? .35 : 0), 1);
    for (const p of riv.parts || []) {
      if (!(p.y0 >= ya && p.y0 <= yb) || p.x < 0 || (p.bank && !rv.glint)) continue;
      const len = 8 + 9 * riverSpeed(p.y0, p.x);
      // 岸上的光点只画洲头之后那一段：洲头前它们还挤在洲心，连起来就成了拴着洲的一根梗
      const x0 = p.bank && top ? Math.max(p.x - len, top.xs + 1) : p.x - len;
      if (x0 > p.x - 2) continue;
      const e = (p.bank ? rv.glint * p.al * (top ? top.pres * sm((p.x - top.xs) / 12) * sm((top.xe + 6 - p.x) / 60) : 0) : .14 + .3 * emOf(p.y0)) * fade(p.x) * fyOf(p.y0);
      if (e < .02) continue;
      c.globalAlpha = P.glint * e;
      c.beginPath();
      for (let s = 0; s <= 3; s++) { const x = x0 + s * (p.x - x0) / 3, y = riverY(p.y0, x); if (s) c.lineTo(x, y); else c.moveTo(x, y); }
      c.stroke();
    }
    // 别的标签底下把水擦淡，边缘羽化，免得读成下划线
    const sc = c.getTransform().a;
    c.globalCompositeOperation = "destination-out"; c.fillStyle = "#000"; c.shadowColor = "#000"; c.shadowBlur = 5 * sc; c.globalAlpha = dark ? .4 : .5;
    rail.querySelectorAll(ETCH).forEach((it) => {
      if (it === riv.el) return;
      range.selectNodeContents(it);
      const r = range.getBoundingClientRect();
      if (r.width) c.fillRect(r.left - HR.left - 1, r.top - HR.top + 2, r.width + 2, r.height - 4);
    });
    c.shadowBlur = 0; c.shadowColor = "transparent";
    c.globalCompositeOperation = "lighter";
    // 沙：每一粒是一个小点；每隔几粒带一团很淡的晕，晕叠起来就是洲面
    const key = col.join() + dark;
    if (riv.sprKey !== key || !riv.spr) {
      const s = riv.spr = document.createElement("canvas");
      s.width = s.height = 64;
      const g = s.getContext("2d");
      if (g) {
        const rg = g.createRadialGradient(32, 32, 0, 32, 32, 32);
        rg.addColorStop(0, rgba(col, 1)); rg.addColorStop(.45, rgba(col, .38)); rg.addColorStop(1, rgba(col, 0));
        g.fillStyle = rg; g.fillRect(0, 0, 64, 64);
      }
      riv.sprKey = key;
    }
    const S = dark ? { r: .8, a: .8, R: 20, ta: .2, hi: .35 } : { r: .5, a: .62, R: 11, ta: .04, hi: 0 };
    c.fillStyle = c.strokeStyle = rgba(lighten(col, S.hi), 1); c.lineWidth = dark ? 1.4 : 1;
    for (const i of riv.isl) for (const s of i.sand) {
      if (s.wait > 0) continue;
      const q = sandAt(i, s), f = q[2] * fyOf(q[1]) * fade(q[0] + fin);
      if (f < .02) continue;
      if (s.tone) { c.globalAlpha = S.ta * rv.tone * s.a * f; c.drawImage(riv.spr, q[0] - S.R, q[1] - S.R, S.R * 2, S.R * 2); }
      c.globalAlpha = S.a * s.a * f; c.beginPath(); c.arc(q[0], q[1], s.s * S.r, 0, 6.2832); c.fill();
    }
    for (const p of riv.loose) {
      c.globalAlpha = S.a * p.a * p.life * .7 * fade(p.x) * fyOf(p.y);
      c.beginPath(); c.moveTo(p.x - 5, p.y); c.lineTo(p.x, p.y); c.stroke();
    }
    c.globalAlpha = 1;
  }

  const isX = new Float32Array(16), isK = new Float32Array(16), isF = new Float32Array(8), isB = new Float32Array(16), isL = new Float32Array(16);
  function riverUniforms(g: WebGLRenderingContext) {
    const rv = RV;
    if (!rv) { g.uniform4f(U.uRiv, 0, 0, 1, 1); return; }
    const narrow = narrowMQ.matches, wash = rv.trans === "wash";
    const top = topIsland();
    isK.fill(0); isB.fill(0); isL.fill(0);
    // 着色器是反推，顺序要倒过来
    riv.isl.slice(-4).reverse().forEach((i, n) => {
      isX.set([i.xs, i.xl, i.xr, i.xe], n * 4);
      isK.set([i.cy, i.b, i.peb || !wash ? i.amp : 1, i.peb ? 1 : 0], n * 4);
      isB.set([i.qT, i.qB, i.U, i.Uh], n * 4);
      isL.set([i.lock, i.L, 1 + FLEX.disp * i.sc, 1 + FLEX.deep * i.sc], n * 4);
      isF.set(i.peb || !wash ? [1e5, -1e5] : [i.t >= 9 ? 1e5 : i.xs + GROW * i.t, i.dead ? i.xs - 110 + WASH * i.td : -1e5], n * 2);
    });
    g.uniform4fv(U.uIsX, isX); g.uniform4fv(U.uIsK, isK); g.uniform2fv(U.uIsF, isF); g.uniform4fv(U.uIsB, isB); g.uniform4fv(U.uIsL, isL);
    g.uniform4f(U.uRim, rim.ph, RIM.k, RIM.amp, RIM.wl);
    g.uniform4f(U.uRiv, 1, narrow ? W + 20 : 380, narrow ? 40 : 18, narrow ? W * .35 : 170);
    g.uniform4f(U.uRivK, rv.bank * RIM.bank, rv.sand / 340 + .35 * rv.tone, rv.glint, T % 4000);
    g.uniform2f(U.uRivY, top ? top.cy : H / 2, narrow ? 1 : 0);
  }
  function drawGlass(deepDirty: boolean) {
    const g = gl;
    if (!g) return;
    g.activeTexture(g.TEXTURE0); g.bindTexture(g.TEXTURE_2D, deepTex);
    if (deepDirty || glFresh) g.texImage2D(g.TEXTURE_2D, 0, g.RGBA, g.RGBA, g.UNSIGNED_BYTE, L.deep.el);
    glFresh = false;
    g.viewport(0, 0, glc.width, glc.height);
    g.uniform2f(U.uView, W, H); g.uniform1f(U.uDpr, glc.width / W); g.uniform1f(U.uBufH, glc.height); g.uniform1f(U.uPad, PAD);
    g.uniform2f(U.uOffDeep, mxS * 14, myS * 10); g.uniform2f(U.uOffMid, mxS * 4, myS * 3);
    g.uniform1f(U.uBevel, narrowMQ.matches ? 0 : 20);
    g.uniform2f(U.uPtr, mxS, myS);
    riverUniforms(g);
    g.drawArrays(g.TRIANGLES, 0, 3);
  }

  // ---- 帧循环：减少动态效果时只在有变化时画；页面隐藏时停下 ----
  let mx = 0, my = 0, mxS = 0, myS = 0, raf = 0, last = performance.now(), drawUntil = 0, alive = true;
  function frame(now: number) {
    raf = 0;
    if (!alive) return;
    const dt = Math.min(.05, (now - last) / 1000); last = now;
    const moving = !reduce.matches;
    if (!moving && now >= drawUntil) return;
    if (moving) { T += dt; mxS += (mx - mxS) * Math.min(1, dt * 3); myS += (my - myS) * Math.min(1, dt * 3); } else { mxS = myS = 0; }
    if (!theme.liquid) {
      L.deep.el.style.transform = `translate3d(${(-mxS * 14).toFixed(2)}px,${(-myS * 10).toFixed(2)}px,0)`;
      L.near.el.style.transform = `translate3d(${(-mxS * 4).toFixed(2)}px,${(-myS * 3).toFixed(2)}px,0)`;
      sheen.style.transform = `translate3d(${(mxS * 60).toFixed(1)}px,0,0)`;
    }
    const deepDrawn = drawDeep(dt, moving);
    stepRiver(dt, moving);
    if (theme.liquid) drawGlass(deepDrawn);
    else { const cn = begin(L.near); if (cn) drawRiver(cn); }
    if (!document.hidden) raf = requestAnimationFrame(frame);
  }
  function start() { if (!raf && alive && !document.hidden) { last = performance.now(); raf = requestAnimationFrame(frame); } }
  function wake(ms = 700) { drawUntil = Math.max(drawUntil, performance.now() + ms); start(); }

  const glSwap = () => { readTheme(); resize(); wake(300); };
  on(glc, "webglcontextlost", (e) => { e.preventDefault(); gl = null; glSwap(); });
  on(glc, "webglcontextrestored", () => { initGL(); glSwap(); });
  on(document, "visibilitychange", () => { if (document.hidden) { cancelAnimationFrame(raf); raf = 0; } else wake(); });
  on(window, "pointermove", (e) => { const p = e as PointerEvent; mx = p.clientX / W * 2 - 1; my = p.clientY / H * 2 - 1; }, { passive: true });
  on(window, "resize", () => { resize(); wake(300); });
  on(window, "scroll", () => { moveT = performance.now(); wake(200); }, { passive: true });
  // mac 上 Chromium 的回弹是合成器变换：scrollY 和 rect 都不变，只能照它的规则从触控板滚动推算。
  const ua = navigator.userAgent, bounce = /Macintosh/.test(ua) && /Chrome\//.test(ua);
  // 滚动链在哪一层断：内层还能往这边滚，或者内层写了 overscroll-behavior，根就不会回弹
  const blocked = (from: EventTarget | null, dy: number) => {
    for (let el = from instanceof Element ? from : null; el && el !== document.body && el !== root; el = el.parentElement) {
      const cs = getComputedStyle(el);
      if (cs.overflowY !== "auto" && cs.overflowY !== "scroll") continue;
      if (cs.overscrollBehaviorY !== "auto") return true;
      if (el.scrollHeight > el.clientHeight + 1 && (dy < 0 ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1)) return true;
    }
    return false;
  };
  on(window, "wheel", (e) => {
    const w = e as WheelEvent & { wheelDeltaY?: number };
    if (!bounce || reduce.matches || w.ctrlKey || w.deltaMode !== 0 || !w.deltaY || Math.abs(w.deltaY) <= Math.abs(w.deltaX)) return;
    const t = w.timeStamp / 1000, gap = t - rb.t, d = -w.deltaY; // d > 0：内容往下走
    // 鼠标滚轮不回弹。整格（wheelDeltaY 是 120 的倍数）只在一次手势的第一下判断：触控板的 |deltaY| 恰好 40 时也是 120，不能中途丢
    const notch = w.wheelDeltaY !== undefined && w.wheelDeltaY % 120 === 0;
    if (gap > .1) rb.notch = notch; else if (!notch) rb.notch = false;
    if (rb.notch) { rb.t = t; return; }
    const max = Math.max(0, root.scrollHeight - innerHeight), scrollable = max > 1;
    if (gap > .1) {
      // 新的一次手势：归属只认一次（和 Chromium 的 latching 一致）；滚动位置从真实值起算，之后按增量自己推，主线程的 scrollY 会落后合成器
      rb.root = !blocked(w.target, w.deltaY); rb.pos = scrollY;
      // 上一推多半已经松手弹回了（没有惯性的松手看不见）：沿弹回曲线悄悄补到现在，不给洲冲量
      if (rb.st === 1) {
        const k = gap - .016, s = (rb.s + RB.amp * (scrollable ? rb.v : 0) * k) * Math.exp(-RB.w * k);
        if (Math.abs(s) < .5 || s * rb.s < 0) rbReset(true); else { rb.s = s; rb.f = s * RB.k; rb.quiet = true; }
      }
    }
    const v = gap > 0 && gap < .1 ? d / Math.max(gap, .004) : 0;
    // 惯性是同向、一帧比一帧慢的平滑序列；手指在板上的速度是抖的
    rb.run = v && Math.sign(v) === Math.sign(rb.v) && Math.abs(v) < Math.abs(rb.v) ? rb.run + 1 : 0;
    if (!rb.run) rb.v1 = v;
    rb.v = v; rb.t = t;
    if (!rb.root) return;
    const coasting = rb.run >= RB.coast && Math.abs(rb.v1) > RB.vmin && Math.abs(v) < .9 * Math.abs(rb.v1);
    // 弹回途中：惯性不再拉长；反向或再加速是新的一推，接着弹回的位置继续
    if (rb.st === 2) { if (rb.run) return; rb.st = 1; rb.f = rb.s * RB.k; }
    let a = d;
    // 可滚动的文档往回收：先 1:1 抵消拉开的量
    if (scrollable && rb.s && Math.sign(a) !== Math.sign(rb.s)) {
      const c = Math.min(Math.abs(rb.s), Math.abs(a));
      rb.s -= Math.sign(rb.s) * c; rb.f = rb.s * RB.k; a -= Math.sign(a) * c;
    }
    // 剩下的先滚页面，滚不动的部分才拉伸
    const p = rb.pos - a;
    rb.pos = Math.min(max, Math.max(0, p)); a = rb.pos - p;
    // 惯性撞到边：Chromium 按当时的速度弹一下，惯性本身不再拉长
    if (coasting) { if (rb.s || a) { rb.st = 2; rb.s0 = rb.s; rb.v0 = scrollable ? v : 0; rb.t0 = t; wake(600); } return; }
    if (!a) { rb.pend = 0; if (!rb.s) rb.st = 0; return; }
    a += rb.pend; rb.pend = 0;
    if (!rb.s && Math.abs(a) < RB.dead) { rb.pend = a; return; }
    rb.f += a; rb.s = rb.f / RB.k; rb.st = 1;
    wake(600);
  }, { passive: true });
  on(rail, "scroll", () => { moveT = performance.now(); wake(200); }, { capture: true, passive: true });
  const setHover = (el: Element | null) => { if (el !== navHover) { navHover = el; wake(); } };
  on(rail, "pointerover", (e) => setHover((e.target as Element).closest(ITEM)));
  on(rail, "pointerleave", () => setHover(null));
  on(rail, "focusin", (e) => setHover((e.target as Element).closest(ITEM)));
  on(rail, "focusout", (e) => { const to = (e as FocusEvent).relatedTarget as Element | null; setHover(to && rail.contains(to) ? to.closest(ITEM) : null); });
  const onTheme = () => { const was = theme.liquid; readTheme(); if (was !== theme.liquid) resize(); wake(300); };
  on(darkMQ, "change", onTheme);
  on(narrowMQ, "change", () => wake(300));
  on(reduce, "change", () => wake());
  const themeObs = new MutationObserver(onTheme);
  themeObs.observe(root, { attributes: true, attributeFilter: ["data-glass-theme"] });
  // aria-current 移动时沙洲迁移
  const railObs = new MutationObserver(() => wake(2500));
  railObs.observe(rail, { attributes: true, subtree: true, childList: true, attributeFilter: ["aria-current"] });
  // 侧栏自己能滚时不回弹：它的回弹只拉侧栏里的内容、不拉背景，洲会和字脱开
  const railFit = () => rail.toggleAttribute("data-glass-scrolls", !narrowMQ.matches && rail.scrollHeight > rail.clientHeight + 1);
  const ro = new ResizeObserver(() => { railFit(); wake(300); });
  ro.observe(rail);
  for (const c of Array.from(rail.children)) ro.observe(c);
  const hro = new ResizeObserver(() => { resize(); wake(300); });
  hro.observe(host);
  if (document.fonts) document.fonts.ready.then(() => wake(300)).catch(() => undefined);

  initGL();
  readTheme(); resize(); wake(1200);

  return () => {
    alive = false;
    cancelAnimationFrame(raf);
    cleanups.forEach((fn) => fn());
    themeObs.disconnect(); railObs.disconnect(); ro.disconnect(); hro.disconnect();
    rail.removeAttribute("data-glass-scrolls");
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    gl = null;
    delete root.dataset.glassMat;
    host.replaceChildren();
  };
}
