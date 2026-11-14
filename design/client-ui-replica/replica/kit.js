/* Renderer: reads window.REPLICA (data built from inventory/<app>.json) and draws an iOS list screen.
   No UI text lives here; everything comes from the data file. */
(function(){
const ICON={
  chevron:'<svg class="chev" viewBox="0 0 8 14"><path d="M1.2 1.2 6.6 7l-5.4 5.8" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  back:'<svg width="13" height="22" viewBox="0 0 13 22"><path d="M11 1.5 1.8 11 11 20.5" fill="none" stroke="var(--glyph)" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  plus:'<svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 1.5v21M1.5 12h21" stroke="var(--glyph)" stroke-width="1.8" stroke-linecap="round"/></svg>',
  close:'<svg width="19" height="19" viewBox="0 0 19 19"><path d="M1.2 1.2l16.6 16.6M17.8 1.2 1.2 17.8" stroke="var(--glyph)" stroke-width="2.1" stroke-linecap="round"/></svg>',
  check:'<svg width="21" height="21" viewBox="0 0 21 21"><path d="M1.5 11.5 7.5 18.5 19.5 1.8" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  home:'<svg viewBox="0 0 28 26"><path d="M3.5 12.5 14 3l10.5 9.5M6.5 10v13h5.5v-7h4v7h5.5V10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>',
  folder:'<svg viewBox="0 0 28 26"><path d="M2.5 6.5V21a1.5 1.5 0 0 0 1.5 1.5h19.5a1.5 1.5 0 0 0 1.5-1.4l1-9.6H7L4.5 22M2.5 6.5V5A1.5 1.5 0 0 1 4 3.5h6l2.5 3h10a1.5 1.5 0 0 1 1.5 1.5v3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>',
  activity:'<svg viewBox="0 0 28 26"><path d="M1.5 13h6l2.5-6 3.5 13 3-10 2 3h8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" stroke-dasharray="none"/></svg>',
  search:'<svg width="20" height="20" viewBox="0 0 20 20"><circle cx="8.3" cy="8.3" r="6.6" fill="none" stroke="#111" stroke-width="2.1"/><path d="M13.2 13.2 18.6 18.6" stroke="#111" stroke-width="2.3" stroke-linecap="round"/></svg>',
  info:'<svg class="info" viewBox="0 0 22 22"><circle cx="11" cy="11" r="9.6" fill="none" stroke="#1E1E1E" stroke-width="1.7"/><rect x="9.9" y="9.4" width="2.2" height="7" rx="1.1" fill="#1E1E1E"/><circle cx="11" cy="6.6" r="1.35" fill="#1E1E1E"/></svg>',
  caret:'<svg class="caret" viewBox="0 0 8 5"><path d="M0 0h8L4 5z" fill="currentColor"/></svg>',
  flatback:'<svg width="12.6" height="22" viewBox="0 0 12.6 22"><path d="M11 1.5 1.8 11 11 20.5" fill="none" stroke="var(--glyph)" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  doc:'<svg width="17.3" height="22" viewBox="0 0 17.3 22"><path d="M2.6 1h9.2l4.5 4.6V19a2 2 0 0 1-2 2H2.6a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2z" fill="none" stroke="var(--glyph)" stroke-width="1.9"/><path d="M10.4 7.6v6.6a2 2 0 0 1-4 0V6.4a1.3 1.3 0 0 1 2.6 0v7" fill="none" stroke="var(--glyph)" stroke-width="1.7" stroke-linecap="round"/></svg>',
  updown:'<svg class="updown" viewBox="0 0 10 16"><path d="M1.5 6 5 2.3 8.5 6M1.5 10 5 13.7 8.5 10" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  gear:'<svg viewBox="0 0 28 26"><g fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="14" cy="13" r="4"/><path d="M14 2.5l2 2.6 3.2-.6.9 3.1 3 1.3-.9 3.1 1.8 2.6-2.6 1.9.1 3.3-3.2.4-1.4 2.9-3-1.4-3 1.4-1.4-2.9-3.2-.4.1-3.3L2.6 13l1.8-2.6-.9-3.1 3-1.3.9-3.1 3.2.6z" stroke-linejoin="round"/></g></svg>',
};
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function statusbar(d){
  return `<div class="statusbar ${d.crumb?'has-crumb':''}"><div class="time">${esc(d.time)}</div>${d.crumb?`<div class="crumb">◀ ${esc(d.crumb)}</div>`:''}<div class="island"></div>
   <div class="right">
    <svg width="20" height="12" viewBox="0 0 20 12"><g fill="#000"><rect x="0" y="8" width="3.2" height="4" rx=".8"/><rect x="5.4" y="5.5" width="3.2" height="6.5" rx=".8"/><rect x="10.8" y="3" width="3.2" height="9" rx=".8"/><rect x="16.2" y="0" width="3.2" height="12" rx=".8"/></g></svg>
    <svg width="17" height="12" viewBox="0 0 17 12"><path d="M8.5 11.5 5.8 8.4a3.8 3.8 0 0 1 5.4 0zM3.4 6.1a7.2 7.2 0 0 1 10.2 0l1.6-1.7a9.6 9.6 0 0 0-13.4 0zM.1 2.6a12 12 0 0 1 16.8 0" fill="#000"/></svg>
    <svg width="28" height="13" viewBox="0 0 28 13"><rect x=".5" y=".5" width="24" height="12" rx="3.8" fill="#6BC56B" stroke="#6BC56B"/><text x="12.5" y="10" font-size="9.5" font-weight="700" text-anchor="middle" fill="#fff" font-family="-apple-system">${esc(d.battery||'80')}</text><rect x="25.6" y="4.3" width="1.6" height="4.4" rx=".8" fill="#6BC56B"/></svg>
   </div></div>`;
}
function navbtn(kind,side){
  const cls=kind==='check'?'navbtn primary '+side:'navbtn '+side;
  return `<div class="${cls}">${ICON[kind]||''}</div>`;
}
function row(r){
  let right='';
  if(r.field!=null) right+=`<span class="field ${r.placeholder?'ph':''}" style="${r.field_x?`left:${r.field_x[0]-D_.gm}px;width:${r.field_x[1]-r.field_x[0]}px`:''}">${esc(r.field)}</span>`;
  if(r.detail!=null) right+=`<span class="detail ${r.accessory==='updown'?'popup':''} ${r.small?'small':''}">${esc(r.detail)}</span>`;
  if(r.accessory==='caret') right+=ICON.caret;
  if(r.accessory==='chevron') right+=ICON.chevron;
  if(r.accessory==='updown') right+=ICON.updown.replace('class="updown"','class="updown popup"');
  if(r.accessory==='switch') right+=`<span class="switch ${r.on?'on':''}"></span>`;
  const sub=r.sub?`<span class="sub">${esc(r.sub)}</span>`:'';
  const ann=r.subhub?`<span class="ann" title="${esc(r.maps_to||'')}">${esc(r.subhub)}</span>`:'';
  return `<div class="row${r.sub?' has-sub':''}" style="${r.h?`height:${r.h}px`:''}">${r.info?ICON.info:''}<span class="label ${r.style||''}">${esc(r.label)}${sub}</span>${right}${ann}</div>`;
}
let D_={gm:0};
window.renderReplica=function(root,D){
  D_.gm=D.group_margin_pt||0;
  root.className='ios-screen theme-'+D.theme;
  const cy=D.nav.center_y||84;
  let y=D.content_top;
  let body='';
  D.groups.forEach((g,i)=>{
    if(i>0) y+=(g.gap_before!=null?g.gap_before:D.group_gap);
    if(g.header){ body+=`<div class="gheader" style="top:${y-(D.header_offset||16)-9}px">${esc(g.header)}</div>`; }
    body+=`<div class="group" style="top:${y}px">${g.rows.map(row).join('')}</div>`;
    y+=g.rows.reduce((s,r)=>s+(r.h||D.row_h),0);
    if(g.footer){ body+=`<div class="gfooter" style="top:${y+(D.footer_offset||17)}px">${esc(g.footer)}</div>`; }
  });
  const m=D.nav.material;
  const navStyle=`--nav-cy:${cy}px`+(m?`;height:${m.bottom_pt}px;background:${m.bg};border-bottom:1.3px solid ${m.hairline}`:'');
  const flat=(k,b)=>k?`<div class="navflat" style="left:${b[0]}px;top:${b[1]}px">${ICON[k]}</div>`:'';
  const nav=D.nav.flat
    ? `<div class="navbar" style="${navStyle};height:${D.content_top-1}px">${flat(D.nav.left,D.nav.left_box)}<div class="navtitle">${esc(D.nav.title)}</div>${flat(D.nav.right,D.nav.right_box)}</div>`
    : `<div class="navbar ${D.sheet?'in-sheet':''}" style="${navStyle}">${D.nav.left?navbtn(D.nav.left,'left'):''}<div class="navtitle">${esc(D.nav.title)}</div>${D.nav.right?navbtn(D.nav.right,'right'):''}</div>`;
  let html='';
  if(D.sheet){
    const b=D.sheet.back;
    html+=`<div class="dim"></div>`+(b?`<div class="backsheet" style="top:${b.top}px;left:${b.x[0]}px;width:${b.x[1]-b.x[0]}px;border-radius:${b.radius}px ${b.radius}px 0 0;background:${b.color}"></div>`:'')+`<div class="sheet" style="top:${D.sheet.top}px;border-radius:${D.sheet.radius}px ${D.sheet.radius}px 0 0"><div class="sheet-body" style="top:${-D.sheet.top}px">${body}${nav}</div></div>`;
  } else {
    html+=`<div class="scroll ${D.scroll_bottom?'clip':''}" style="${D.scroll_bottom?`height:${D.scroll_bottom}px`:''}">${body}</div>`+nav;
  }
  if(D.floating){ D.floating.forEach(f=>{ if(f.control==='searchfield'){ const g=f.geom;
    html+=`<div class="floatsearch" style="left:${g.x[0]}px;top:${g.y[0]}px;width:${g.x[1]-g.x[0]}px;height:${g.y[1]-g.y[0]}px;padding-left:${g.icon_x-g.x[0]}px">${ICON.search}<span style="margin-left:${g.text_left-g.icon_x-20}px">${esc(f.label)}</span></div>`; } }); }
  html+=statusbar(D.status);
  (D.redactions||[]).forEach(b=>{ html+=`<div class="redact" style="left:${b[0]}px;top:${b[1]}px;width:${b[2]-b[0]}px;height:${b[3]-b[1]}px"></div>`; });
  if(D.tabbar){
    const t=D.tabbar;
    html+=`<div class="tabbar" style="left:${t.x[0]}px;width:${t.x[1]-t.x[0]}px">${t.items.map((it,i)=>`<div class="tab ${i===t.selected?'on':''}">${ICON[it.icon]||''}<span>${esc(it.label)}</span></div>`).join('')}</div>`;
  }
  root.innerHTML=html;
};
})();
