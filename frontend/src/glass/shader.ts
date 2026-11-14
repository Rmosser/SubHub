// 清透（浅色）玻璃的全屏片元着色器。移植自定稿原型 var/glass-workbench/final.html，
// 只保留外壳需要的部分：床面、点阵、深处缓流（纹理）、导航下的沙洲细流、左侧切边与窗光。
// 页面里有含义的数据流和纸的阴影属于页面内容，不在这里。

export const VERTEX_SHADER = "attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}";

export const FRAGMENT_SHADER = `precision highp float;
uniform vec2 uView, uOffDeep, uOffMid, uPtr;
uniform float uDpr, uBufH, uPad, uBevel;
uniform sampler2D uDeep;
uniform vec3 uBedHi, uBedLo, uDot, uTint, uEdgeTint;
uniform vec4 uIsX[4];
uniform vec4 uIsK[4];
uniform vec2 uIsF[4];
uniform vec4 uIsB[4];
uniform vec4 uIsL[4];
uniform vec4 uRiv, uRivK;
uniform vec4 uRim;
uniform vec3 uRimC, uRimT;
uniform vec2 uRivY;
vec2 uvOf(vec2 p){ return (p + uPad) / (uView + 2.0 * uPad); }
vec3 lit(vec3 c, vec4 s, float lift){ float k = smoothstep(0.05, 0.5, s.a); return c * (1.0 - s.a * (0.5 + 0.5 * k)) + s.rgb * (1.0 + lift * (1.0 - k)); }
// 沙洲：床面上一组解析的耙痕。像素先被反推回没有沙洲时的位置，再看它落在哪根流线上；
// 线宽恒为一根发丝，挤得越密越亮，密到分不开就并成岸线。三个色通道用略不同的洲高各推一遍，只有被推开处出现色散。
float rHash(float n){ return fract(sin(n * 127.1 + 311.7) * 43758.5453); }
float isShape(vec4 X, float x){
  if (x <= X.x || x >= X.w) return 0.0;
  float xn = X.y + 4.0, xt = X.z + 2.0;
  if (x < xn) return pow(sin(1.5708 * (x - X.x) / (xn - X.x)), 0.8);
  if (x < xt) return 1.0;
  return pow(1.0 - pow((x - xt) / (X.w - xt), 1.6), 1.25);
}
// 字底下的单拱：惯性只在字的正下方顶出一点弧度
float isWin(vec4 X, float x){ float t = (x - 0.5 * (X.y + X.z)) / (0.5 * (X.z - X.y) + 14.0); float w = 1.0 - t * t; return abs(t) < 1.0 ? w * w : 0.0; }
float isEnv(float a, vec2 F, float x){ return a * smoothstep(0.0, 1.0, (F.x - x) / 90.0) * smoothstep(0.0, 1.0, (x - F.y) / 110.0); }
// 流线偏折的范围：上游 30px 渐入，下游带一段 70px 的尾流
float isFx(vec4 X, float x){ return smoothstep(0.0, 1.0, (x - X.x + 30.0) / 36.0) * (1.0 - smoothstep(0.0, 1.0, (x - X.w + 6.0) / 76.0)); }
vec2 rivLine(vec2 p, float hk){
  float y = p.y, g = 1.0, gb = 0.0, edge = 1.0, calm = 1.0, em = 0.0, dl = 0.0, cr = 0.0, cw = 0.0;
  // 偏折量按通道略有差异，差的那一份跟着慢半拍的光走：动起来岸上才有一点色散的闪动
  float ch = (hk - 1.0) * 3.0;
  for (int i = 0; i < 4; i++) {
    vec4 X = uIsX[i], K = uIsK[i], Q = uIsB[i], S = uIsL[i];
    if (K.z < 0.003) continue;
    float e = isEnv(K.z, uIsF[i], p.x), peb = K.w, d = abs(y - K.x);
    float sg = clamp(0.9 * (d - K.y), 0.0, 34.0);
    float qb = y < K.x ? Q.x : Q.y;
    // 滚动时三个通道的洲高差得更多（S.z）：色散略微拉开
    float h = (K.y * (0.5 * isShape(X, p.x) + 0.25 * (isShape(X, p.x - sg) + isShape(X, p.x + sg))) + qb * isWin(X, p.x) * step(0.001, isShape(X, p.x))) * e * (1.0 + (hk - 1.0) * S.z);
    float inside = step(0.02, h);
    if (h > 0.02) {
      float d0 = pow(max(pow(d, 1.5) - pow(h, 1.5), 0.0), 0.66667);
      edge *= smoothstep(-0.7, 0.5, d - h);
      float gi = sqrt(max(d, h) / max(d0, 0.05));
      g *= gi; gb += (min(gi, 3.5) - 1.0) * smoothstep(0.5, 6.0, h) * mix(1.0, 0.5, peb);
      y = K.x + (y < K.x ? -d0 : d0);
    }
    // 换选中项时的惯性：在没被推开的水里往反方向偏折，洲心为 0、离洲心 10px 处最大；反推两步，线距的变化记进亮度
    float U = Q.z + ch * Q.w, fx = isFx(X, p.x) * e;
    if (abs(U) * fx > 0.005) {
      float y1 = y;
      for (int k = 0; k < 2; k++) { float r = (y1 - K.x) / 10.0; y1 = y - U * fx * r * r * exp(1.0 - r * r); }
      float r = (y1 - K.x) / 10.0, gd = 1.0 / max(0.3, 1.0 + U * fx * (2.0 * r - 2.0 * r * r * r) * exp(1.0 - r * r) / 10.0);
      g *= gd; gb += max(gd - 1.0, 0.0) * 0.9;
      y = y1;
    }
    if (S.x < 0.999 && inside > 0.5) { cr = y - K.x; cw = 1.0 - S.x; }
    if (peb < 0.5 && p.x >= X.w) {
      calm *= 1.0 - 0.45 * e * exp(-d * d / 90.0) * exp(-(p.x - X.w) / 70.0);
    }
    float q = (y - K.x) / mix(46.0, 20.0, peb), wq = e * mix(1.0, 0.4, peb) * exp(-q * q);
    em = max(em, wq);
    // 线格相位锁在洲心上，静止时两岸对称；洲相对床面移动时松开，线留在水里、洲从线中穿过。
    // 洲落在字后面（S.y）时，相位按没落后的洲心算、再整体挪 S.y：近旁的水跟着一起落后，相位不会绕回去跳一格
    dl = mix(dl, -(fract((K.x - S.y) / 4.0 + 0.5) - 0.5) * 4.0 - S.y, wq * S.x);
  }
  y -= 1.1 * sin(p.x * 0.012 + y * 0.07 + uRivK.w * 0.35);
  float f = (y + dl) / 4.0, id = floor(f), t = (fract(f) - 0.5) * 4.0;
  float ds = t / g, dens = g / 4.0, w = 0.5;
  float li = exp(-ds * ds / (w * w)), z = ds - 0.9, sh = exp(-z * z / (w * w * 1.6));
  float k = smoothstep(0.5, 0.9, dens), mean = min(1.0, 1.772 * w * dens);
  li = mix(li, mean, k); sh = mix(sh, mean * 0.6, k);
  float pu = fract((p.x - uRivK.w * (30.0 + 26.0 * rHash(id + 7.0))) / 250.0 + rHash(id)) - 0.5;
  float glint = exp(-pu * pu * 250.0);
  float A = (0.11 + 0.45 * em) * (0.72 + 0.28 * sin(p.x * 0.006 + y * 0.021 + uRivK.w * 0.06)) * (0.8 + 0.2 * rHash(id + 71.3)) * (1.0 + (0.5 + 0.9 * em) * glint);
  float B = 1.0 + uRivK.x * 2.2 * gb;
  // 洲在床面上移动时，正擦过洲心的那根线先淡出，不从一岸跳到另一岸
  float fade = mix(1.0, smoothstep(0.35, 1.5, abs(cr - t)), cw), m = edge * calm;
  return vec2(li * A * B, sh * A * (0.6 + 0.4 * B)) * m * fade;
}
vec3 river(vec3 c, vec2 p){
  float fx = clamp(min(p.x / uRiv.z, (uRiv.y - p.x) / uRiv.w), 0.0, 1.0);
  if (fx <= 0.0) return c;
  float qy = (p.y - uRivY.x) / 52.0;
  if (uRivY.y > 0.5) fx *= exp(-qy * qy);
  float shoal = 0.0, ring = 0.0, tl = 0.0;
  for (int i = 0; i < 4; i++) {
    vec4 X = uIsX[i], K = uIsK[i];
    if (K.z < 0.003 || K.w > 0.5) continue;
    float sh = isShape(X, p.x), e = isEnv(K.z, uIsF[i], p.x), d = abs(p.y - K.x);
    float h = sh > 0.0 ? (K.y * sh + (p.y < K.x ? uIsB[i].x : uIsB[i].y) * isWin(X, p.x)) * e : 0.0;
    if (h > 0.5) { float r = min(d / h, 1.0); shoal = max(shoal, e * (1.0 - r * r) * (1.0 - r * r) * smoothstep(X.z - 2.0, X.z + 18.0, p.x) * min(1.0, h / 5.0)); }
    // 玻璃切边的厚度：紧贴最里一道色散（红通道的岸）往里一圈深海青蓝，约 1.5px，往里渐隐；洲头、洲尾变薄处跟着收掉。
    // 滚动时色散拉开，这一圈也跟着往里让、略深
    vec4 S = uIsL[i];
    float hr = h * (1.0 - 0.045 * S.z), rg = smoothstep(hr - 2.2, hr - 0.2, d) * (1.0 - smoothstep(hr - 0.2, hr + 0.3, d)) * smoothstep(2.0, 6.0, h) * S.w;
    if (rg > ring) { ring = rg; tl = smoothstep(X.z, X.w, p.x); }
  }
  c = mix(c, vec3(1.0, 0.988, 0.955), 0.5 * uRivK.y * shoal * fx);
  // 浓淡沿岸起伏、往下游流；从字尾到洲尾渐浅
  float k = ring * fx * uRim.y * (1.0 + uRim.z * sin(6.2832 * (p.x - uRim.x) / uRim.w));
  c = mix(c, mix(uRimC, uRimT, tl), min(k, 0.7));
  vec2 r = rivLine(p, 0.955), g = rivLine(p, 1.0), b = rivLine(p, 1.062);
  vec3 li = vec3(r.x, g.x, b.x) * fx, sh = vec3(r.y, g.y, b.y) * fx;
  c *= 1.0 - min(sh, 1.0) * vec3(0.3, 0.15, 0.03);
  return c + (1.0 - c) * min(li, 1.0) * vec3(0.94, 0.98, 1.0);
}
// 玻璃底下：床面、点阵、深处的缓流、导航下的细流
vec3 scene(vec2 p){
  vec2 q = (p / uView - vec2(0.6, 0.38)) / vec2(1.2, 0.9);
  vec3 c = mix(uBedHi, uBedLo, smoothstep(0.0, 0.8, length(q)));
  vec2 b = p + uOffDeep * 1.3;
  float d = length(fract(b / 22.0) - 0.5) * 22.0;
  c = mix(c, uDot, (1.0 - smoothstep(0.5, 1.3, d)) * 0.1);
  vec2 pd = uvOf(p + uOffDeep), o = vec2(7.0, 4.0) / (uView + 2.0 * uPad), r = vec2(o.y, -o.x);
  vec4 dp = texture2D(uDeep, pd) * 0.3 + (texture2D(uDeep, pd + o) + texture2D(uDeep, pd - o)) * 0.2 + (texture2D(uDeep, pd + r) + texture2D(uDeep, pd - r)) * 0.15;
  c = lit(c, dp, 0.8);
  if (uRiv.x > 0.5) c = river(c, p + uOffMid);
  return c;
}
// 表面的反光：一扇窗，左沿利落，往右散开
float refl(vec2 p){
  float t = (p.x + (p.y - uView.y * 0.5) * 0.32) / uView.x - uPtr.x * 0.05 - 0.47;
  float a = smoothstep(-0.0015, 0.0, t) * (1.0 - smoothstep(0.0, 0.2, t));
  float m = smoothstep(-0.052, -0.0505, t) * (1.0 - smoothstep(-0.022, -0.0205, t));
  return (a * 0.06 + m * 0.03) * (1.0 - 0.45 * p.y / uView.y);
}
// 玻璃本体：左侧一条切边露出厚度（折射 + RGB 色散），其余只有极淡的体色和反光
vec3 slab(vec2 p){
  float x = p.x, e = x - uBevel, rf;
  vec3 c;
  if (uBevel > 0.0 && e < 0.0) {
    float u = -e / uBevel, k = uBevel * 1.15 * u * u;
    c = vec3(scene(p + vec2(k, 0.0)).r, scene(p + vec2(k * 1.09, 0.0)).g, scene(p + vec2(k * 1.18, 0.0)).b);
    c *= mix(vec3(1.0), uEdgeTint, 0.3 + 0.7 * pow(u, 0.8));
    c += 0.07 * u * u;
    float z = (u - 0.52) / 0.05;
    c += 0.05 * exp(-z * z);
    z = (e + 2.4) / 1.3;
    c *= 1.0 - 0.12 * exp(-z * z);
    c += 0.2 * exp(-x * x / 1.5);
    rf = refl(p + vec2(70.0, 0.0)) * 0.6;
  } else {
    c = scene(p);
    if (uBevel > 0.0) { c = mix(c, c * uEdgeTint, 0.22 * exp(-e / 46.0)); c *= 1.0 - 0.05 * exp(-e / 9.0); }
    rf = refl(p);
  }
  c = mix(c, uTint, 0.05) + rf;
  if (uBevel > 0.0) { float gy = (p.y - (uPtr.y * 0.5 + 0.5) * uView.y) / 240.0; c += (0.26 + 0.55 * exp(-gy * gy)) * exp(-e * e / 0.8); }
  return c;
}
void main(){
  vec2 p = vec2(gl_FragCoord.x, uBufH - gl_FragCoord.y) / uDpr;
  gl_FragColor = vec4(clamp(slab(p), 0.0, 1.0), 1.0);
}`;

export const UNIFORMS = [
  "uView", "uOffDeep", "uOffMid", "uPtr", "uDpr", "uBufH", "uPad", "uBevel", "uDeep",
  "uBedHi", "uBedLo", "uDot", "uTint", "uEdgeTint", "uIsX", "uIsK", "uIsF", "uIsB", "uIsL", "uRiv", "uRivK", "uRim", "uRimC", "uRimT", "uRivY",
] as const;
