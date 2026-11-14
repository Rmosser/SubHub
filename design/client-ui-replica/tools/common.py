import json, os, pathlib
# Hand-kept inputs (e.g. _notes/) always come from the committed inventory folder.
NOTES=str(pathlib.Path(__file__).resolve().parent.parent / "inventory") + "/"
# UI_REPLICA_INVENTORY_OUT lets tests regenerate into a temp dir and diff against the committed JSON.
OUT=os.environ.get("UI_REPLICA_INVENTORY_OUT", str(pathlib.Path(__file__).resolve().parent.parent / "inventory")).rstrip("/") + "/"
# relation vocabulary (SubHub 与这一行的关系)
REL={"writes":"写入","partial":"只写一部分","none":"不写","device":"只在手机本机","unverified":"还没核对","na":"不适用（动作/导航）"}
def row(label, control, value=None, to=None, maps_to=None, layer="profile", subhub="unverified", note=None, candidate=None):
    r={"label":label,"control":control}
    if value is not None: r["value"]=value
    if to: r["to"]=to
    r["maps_to"]=maps_to
    if candidate: r["maps_to_candidate"]=candidate
    r["layer"]=layer
    r["subhub"]=subhub; r["subhub_zh"]=REL[subhub]
    if note: r["note"]=note
    return r
def group(header=None, rows=(), footer=None):
    g={"header":header,"rows":[]}
    for i,r in enumerate(rows,1):
        r=dict(r); r["order"]=i; g["rows"].append(r)
    g["footer"]=footer
    return g
def screen(id, path, title, nav=None, groups=(), shots=(), not_entered=(), kind="settings", note=None):
    s={"id":id,"kind":kind,"path":path,"title":title,"nav":nav or {},"groups":list(groups),"screenshots":list(shots)}
    if not_entered: s["not_entered"]=[{"entry":e,"reason":r} for e,r in not_entered]
    if note: s["note"]=note
    return s
def dump(app, meta, screens):
    d={"app":app,**meta,"screens":screens}
    ids={s["id"] for s in screens}
    for s in screens:
        for g in s["groups"]:
            for r in g["rows"]:
                if r.get("to") and r["to"] not in ids and not r["to"].startswith("#"):
                    r.setdefault("to_status","目标页未收录")
    json.dump(d,open(OUT+app+".json","w"),ensure_ascii=False,indent=1)
    n=sum(len(g["rows"]) for s in screens for g in s["groups"])
    print(app, len(screens),"screens", n,"rows")
