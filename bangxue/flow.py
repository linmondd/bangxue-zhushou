"""流程层：建课表 / 进入学习 / 起播 / 检查 / 完成回验 / 关页。与驱动无关。"""
import json, re, time
from collections import Counter
from urllib.parse import parse_qs, urlsplit
from contextlib import contextmanager

# ---------- 页面脚本 ----------
FIND_PLAYER = r"""
(function(){
  if(window.__player) return "cached";
  var seen={}, target=null, all=document.querySelectorAll("*");
  function sc(c){
    if(!c||seen[c._uid])return; seen[c._uid]=1;
    try{ var ps=Object.keys(c);
      for(var i=0;i<ps.length;i++){ try{ var val=c[ps[i]];
        if(val&&typeof val==="object"&&typeof val.play==="function"&&typeof val.getCurrentTime==="function"){ target=val; return; }
      }catch(e){} } }catch(e){}
    var ch=c.$children||[]; for(var j=0;j<ch.length;j++) sc(ch[j]);
  }
  for(var i=0;i<all.length&&!target;i++){ var v=all[i].__vue__; if(v) sc(v); }
  if(target){ window.__player=target; return "ok"; } return "noplayer";
})()
"""

STATE = r"""
(function(){
  var href=location.href;
  var cid=(href.match(/\/play\/([a-f0-9-]+)/)||[])[1]||"";
  var wid=(href.match(/workshopId=([a-f0-9-]+)/)||[])[1]||"";
  var out={play:href.indexOf("/play/")>=0, cid:cid, wid:wid, ct:-1,dur:-1,rs:-1,paused:"?",rate:0};
  var p=window.__player;
  if(p){
    try{ out.paused=p.paused(); }catch(e){}
    try{ out.ct=Math.round(p.getCurrentTime()*10)/10; }catch(e){}
    try{ out.dur=Math.round(p.getDuration()); }catch(e){}
  }
  var v=document.querySelector("video");
  if(v){ out.rs=v.readyState; out.rate=v.playbackRate; }
  var lab=document.querySelector(".current-rate");
  out.label=(lab?lab.textContent.trim():"");
  var pe=document.querySelector(".el-progress__text");
  if(pe){ out.prog=pe.textContent.trim(); }
  else {
    var prog=[...document.querySelectorAll("*")].filter(e=>e.children.length===0 && /%$/.test(e.textContent.trim()) && e.getBoundingClientRect().width>0).map(e=>e.textContent.trim());
    out.prog=(prog[0]||"");
  }
  return JSON.stringify(out);
})()
"""

SETUP = r"""
(function(){
  var p=window.__player; if(!p) return "noplayer";
  try{ if(!p.muted()) p.mute(); }catch(e){}
  try{ if(p.paused()) p.play(); }catch(e){}
  var v=document.querySelector("video");
  var lab=document.querySelector(".current-rate");
  return JSON.stringify({paused:p.paused(),ct:Math.round(p.getCurrentTime()*10)/10,dur:Math.round(p.getDuration()),rate:(v?v.playbackRate:0),label:(lab?lab.textContent.trim():"")});
})()
"""

# 用播放器自己的倍速菜单（可见控件）设置 2x，保证界面显示与内部状态同步
OPEN_RATE_MENU = r"""
(function(){ var cur=document.querySelector(".current-rate"); if(!cur) return "nocur"; cur.click(); return "ok"; })()
"""
PICK_2X = r"""
(function(){
  var li=[...document.querySelectorAll("li")].find(function(x){return x.textContent.trim()==="2.0x";});
  if(!li) return "no2x";
  li.click(); return "ok";
})()
"""

ENTER_JS = r"""
(function(){
  var els=[...document.querySelectorAll("*")].filter(function(e){
    return e.children.length===0 && /^(我要学习|继续学习|立即学习|立即报名)$/.test(e.textContent.trim())
      && e.getBoundingClientRect().width>0;
  });
  if(!els.length) return "nobtn";
  var el=els[0];
  el.scrollIntoView({block:"center"});
  var b=el.getBoundingClientRect();
  return JSON.stringify({x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)});
})()
"""

# Element UI keeps hidden tab panels and fixed-column copies in the DOM.
_PAGE_JS = r"""
const visible = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== "hidden";
const text = e => e ? e.textContent.trim() : "";
function pager(root) {
  const p = [...root.querySelectorAll(".el-pagination")].filter(visible);
  if (p.length > 1) return {error:"页面含多个分页栏"};
  if (!p.length) return {page:null,next:false,total:null};
  const next = p[0].querySelector(".btn-next");
  const active = p[0].querySelector(".el-pager .active,.el-pager .is-active,[aria-current=page]");
  const total = text(p[0].querySelector(".el-pagination__total")).replaceAll(",","").match(/\d+/);
  if (!next) return {error:"分页栏缺少下一页控件"};
  return {page:active ? Number(text(active)) : null, next:!(next.disabled ||
    next.getAttribute("aria-disabled")==="true" || next.classList.contains("disabled")),
    total:total ? Number(total[0]) : null};
}
"""
_TABLE_JS = _PAGE_JS + r"""
const tables = [...document.querySelectorAll("table")].filter(t =>
  visible(t) && t.tBodies.length && !t.closest(".el-table__fixed,.el-table__fixed-right"));
if (tables.length !== 1) return {waiting:true};
const table = tables[0];
const rows = [...table.tBodies].flatMap(b => [...b.rows]).filter(visible);
const items = rows.map(row => {
  const c = row.cells;
  return {type:text(c[0]), title:text(c[1]), prog:text(c[4]), act:text(c[5])};
});
const controls = pager(document);
const busy = [...document.querySelectorAll(".el-loading-mask,[aria-busy=true]")].some(visible);
const empty = [...document.querySelectorAll(".el-table__empty-text,[data-empty]")]
  .some(e=>visible(e) && /暂无数据|暂无课程|没有课程/.test(text(e)));
"""
READ_TABLE = "(() => {" + _TABLE_JS + """
return JSON.stringify({...controls, rows:items, waiting:busy || (!items.length && !empty)
  || items.some(r=>!r.type || !r.title || !(r.prog || r.act))});
})()
"""
NEXT_PAGE = r"""(() => {
const bs=[...document.querySelectorAll(".el-pagination .btn-next")].filter(b=>b.getClientRects().length);
if(bs.length!==1 || bs[0].disabled || bs[0].getAttribute("aria-disabled")==="true") return false;
bs[0].click(); return true;
})()"""

DETECT_BLOCK = r"""
(function(){
  const visible=e=>!!e && e.getClientRects().length>0 && getComputedStyle(e).visibility!=="hidden";
  const text=document.body ? document.body.innerText : "";
  const panels=[...document.querySelectorAll('[role=dialog],.el-dialog,form,.login-panel,.captcha')]
    .filter(visible).map(e=>e.innerText).join("\n");
  if (/验证码|安全验证|滑动.*验证/.test(panels) ||
      [...document.querySelectorAll('input[placeholder*=验证码],iframe[src*=captcha]')].some(visible)) return "captcha";
  if (/密码登录|短信登录|统一手机号登录|请先登录|请重新登录|登录已失效|登录已过期/.test(text) ||
      [...document.querySelectorAll('input[type=password]')].some(visible) ||
      /\/(?:login|signin)(?:[/?#]|$)/i.test(location.href)) return "login";
  if (/^(?:请输入)?验证码$|请完成.{0,5}验证|请.{0,3}输入验证码/m.test(text)) return "captcha";
  if (/操作过于频繁|访问过于频繁|同时学习.{0,12}限制|学习并发.{0,12}限制|已达.{0,10}并发上限|访问受限|禁止多开|不能同时学习/.test(text)) return "restriction";
  if (/4008|缓冲数据超时/.test(text)) return "4008";
  if (/已下架/.test(text)) return "removed";
  if (/需要访问互联网/.test(text)) return "network";
  return "";
})()
"""

def detect_block(driver):
    """识别登录失效/验证码/4008/下架等系统级阻断，返回原因或空串。"""
    try:
        return driver.eval(DETECT_BLOCK) or ""
    except Exception:
        return ""

class TableReadError(RuntimeError):
    """无法证明页面或课程表完整，调用方应保留已有状态。"""


class CourseListChanged(TableReadError):
    """平台课程清单与状态中的清单不同，需要重新建表。"""


class _WaitTimeout(TableReadError):
    pass


class BlockedPage(TableReadError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"平台阻断：{reason}")


def _guard(driver):
    result = driver.eval(DETECT_BLOCK)
    if not isinstance(result, str):
        raise TableReadError("无法读取当前页面")
    if result:
        raise BlockedPage(result)


WAIT_SECONDS = 15
POLL_SECONDS = 0.2


def _wait(probe, message):
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        value = probe()
        if value is not None:
            return value
        if time.monotonic() >= deadline:
            raise _WaitTimeout(message)
        time.sleep(POLL_SECONDS)


def _json(driver, js):
    raw = driver.eval(js)
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        raise TableReadError("页面数据无法解析")
    if not isinstance(data, dict) or data.get("error"):
        raise TableReadError("页面读取失败：" + str(data)[:120])
    return data


def _rows_key(snapshot):
    return tuple(tuple(sorted(row.items())) for row in snapshot["rows"])


def _pages(driver, read, max_pages=1000):
    previous = None
    seen = set()
    count = 0
    total = None
    for page_number in range(1, max_pages + 1):
        last = None

        def loaded():
            nonlocal last
            _guard(driver)
            snap = read()
            if snap.get("waiting"):
                last = None
                return None
            key = _rows_key(snap)
            if (snap.get("page") not in (None, page_number) or
                    (previous is not None and key == previous)):
                last = None
                return None
            # A paginator can change its selection before the AJAX rows arrive.
            if snap != last:
                last = snap
                return None
            return snap

        snapshot = _wait(loaded, f"第 {page_number} 页课程数据未完整加载或仍是上一页")
        key = _rows_key(snapshot)
        if key in seen:
            raise TableReadError("检测到重复分页，已停止读取")
        seen.add(key)
        if page_number == 1:
            total = snapshot.get("total")
        if total != snapshot.get("total"):
            raise TableReadError("读取期间课程总数发生变化")
        count += len(snapshot["rows"])
        if total is not None and (count > total or (not snapshot["next"] and count != total)):
            raise TableReadError(f"课程数不一致，已读 {count} 行，页面显示 {total} 行")
        yield snapshot
        if not snapshot["next"]:
            return
        if page_number == max_pages or driver.eval(NEXT_PAGE) is not True:
            raise TableReadError("未能读取全部分页")
        previous = key


def read_table_rows(driver, max_pages=1000):
    expected = driver.current_url()
    def read():
        if driver.current_url() != expected:
            raise TableReadError("读表时页面已改变")
        return _json(driver, READ_TABLE)
    return [r for page in _pages(driver, read, max_pages) for r in page["rows"]]


# ---------- 工具 ----------
def play_url(cid, wid):
    return f"https://u.ccb.com/course/#/play/{cid}?workshopId={wid}"

def detail_url(cid, wid):
    return f"https://u.ccb.com/course/#/detail/{cid}?refresh=1&workshopId={wid}&enrefresh=1"

def workshop_url(wid):
    return f"https://u.ccb.com/workshop/#/myworkshop/detail?id={wid}"

def _norm(s):
    s = str(s)
    for a, b in [("（", "("), ("）", ")"), ("：", ":"), ("，", ","), ("—", "-"), ("－", "-")]:
        s = s.replace(a, b)
    return "".join(s.split())

def _route(url):
    outer = urlsplit(url or "")
    if outer.scheme != "https" or outer.netloc.lower() != "u.ccb.com":
        return "", "", {}
    fragment = urlsplit(outer.fragment)
    return outer.path.rstrip("/"), fragment.path, parse_qs(fragment.query)


def _course(url, wid, route):
    app, path, query = _route(url)
    match = re.fullmatch("/" + route + r"/([A-Za-z0-9_-]+)", path)
    if app == "/course" and query.get("workshopId") == [wid] and match:
        return match.group(1)
    return None


def _workshop(url, wid, path="/myworkshop/detail"):
    app, fragment, params = _route(url)
    return app == "/workshop" and fragment == path and params.get("id") == [wid]


def _tabs(driver):
    tabs = driver.list_tabs()
    if tabs is None:
        raise TableReadError("无法核实浏览器标签列表")
    return tabs


def _find(driver, cid, wid, route):
    return next((t for t in _tabs(driver) if _course(t.url, wid, route) == cid), None)


def _on(driver, cid, wid, route):
    return _course(driver.current_url(), wid, route) == cid


def find_tab(driver, cid, wid, route="play"):
    t = _find(driver, cid, wid, route)
    if t and driver.use(t) and _on(driver, cid, wid, route):
        return t
    return None


def _owned(driver, tab):
    make_record = getattr(driver, "owned_record", None)
    return make_record(tab) if make_record else {"id": tab.id, "url": tab.url}


def close_owned(driver, record):
    if not isinstance(record, dict) or record.get("id") is None or not record.get("url"):
        return "unverified"
    try:
        tabs = _tabs(driver)
        tab = next((t for t in tabs if t.id == record["id"]), None)
        if tab is None:
            return "missing"
        verify_record = getattr(driver, "verify_record", None)
        if tab.url != record["url"] or (verify_record and not verify_record(tab, record)):
            return "unverified"
        return "closed" if driver.close(tab) else "unverified"
    except Exception:
        return "unverified"


@contextmanager
def _temporary(driver, url, accepts):
    tab = driver.open(url, new_tab=True)
    blocked = False
    try:
        def ready():
            live = next((t for t in _tabs(driver) if t.id == tab.id), None)
            if live is None or not driver.use(live):
                raise TableReadError("无法核对刚打开的标签页")
            _guard(driver)
            return live if accepts(driver.current_url()) else None
        yield _wait(ready, "未进入指定的平台页面，请核对当前登录与页面范围")
    except BlockedPage:
        blocked = True
        raise
    finally:
        live = next((t for t in _tabs(driver) if t.id == tab.id), None)
        if not blocked and live and accepts(live.url):
            driver.close(live)


def workshop_rows(driver, wid):
    with _temporary(driver, workshop_url(wid), lambda u: _workshop(u, wid)):
        return read_table_rows(driver)


# ---------- 资源库范围 ----------
_LIBRARY_URL = "https://u.ccb.com/portal/#/centralizedResource"
_LIBRARY_TABS = _PAGE_JS + r"""
const tabs = [...document.querySelectorAll('[role=tab],.el-tabs__item')].filter(visible);
const selected = t=>t.getAttribute('aria-selected')==="true" || t.classList.contains("is-active");
"""
_LIBRARY_JS = _LIBRARY_TABS + r"""
const names = tabs.map(text);
const active = tabs.filter(selected);
const activeName = active.length === 1 ? text(active[0]) : "";
const panelId = active.length === 1 ? active[0].getAttribute('aria-controls') : "";
const panel = panelId ? document.getElementById(panelId) : null;
const scope = panel || document;
const base = {names, active:activeName, panel:panel ? panel.id : ""};
if (!activeName || (panel && !visible(panel)) ||
    [...scope.querySelectorAll(".el-loading-mask,[aria-busy=true]")].some(visible))
  return {...base, waiting:true};
const lists = new Set();
for (const el of scope.querySelectorAll("*")) {
  let c = el.__vue__;
  while(c) {
    if (Array.isArray(c.$data?.tableList) && visible(c.$el) &&
        (scope === document || scope.contains(c.$el))) lists.add(c.$data.tableList);
    c = c.$parent;
  }
}
if(lists.size !== 1) return {...base,waiting:true};
const rows = [...lists][0].map(x=>({wid:x.knowledgeId,title:x.title}));
const empty = [...scope.querySelectorAll(".el-table__empty-text,[data-empty]")].some(
  e=>visible(e) && /暂无数据|暂无班级/.test(text(e)));
return {...base,...pager(document),rows,waiting:rows.some(r=>!r.wid || !r.title) || (!rows.length && !empty)};
"""


def _library(url):
    return _route(url)[:2] == ("/portal", "/centralizedResource")


def _tab_names(driver):
    def read():
        _guard(driver)
        raw = driver.eval("(() => {" + _LIBRARY_TABS + "return JSON.stringify(tabs.map(text));})()")
        names = json.loads(raw) if isinstance(raw, str) else []
        return names or None
    return _wait(read, "资源库未显示可选择的标签")


def read_library_tabs(driver):
    with _temporary(driver, _LIBRARY_URL, _library):
        return _tab_names(driver)


def read_library_classes(driver, tab_name=None):
    with _temporary(driver, _LIBRARY_URL, _library):
        names = _tab_names(driver)
        def state():
            if not _library(driver.current_url()):
                raise TableReadError("资源库页面已改变")
            return _json(driver, "(() => {" + _LIBRARY_JS + "})()")
        def baseline():
            _guard(driver)
            snap = state()
            return None if snap.get("waiting") else snap
        before = _wait(baseline, "资源库初始标签未提供可核实的班级列表")
        chosen = tab_name if tab_name is not None else before["active"]
        if not chosen or names.count(chosen) != 1:
            raise TableReadError(f"无法唯一定位资源库标签「{chosen}」，可选标签有 {'、'.join(names)}")
        switched = before["active"] != chosen
        if switched:
            js = "const tab=tabs.find(t=>text(t)===" + json.dumps(chosen) + ");tab.click();return true;"
            driver.eval("(() => {" + _LIBRARY_TABS + js + "})()")
        def read():
            snap = state()
            if snap.get("active") != chosen:
                return {"waiting": True}
            if (switched and snap.get("panel") == before.get("panel") and
                    snap.get("rows") == before["rows"]):
                # Shared component still showing old items, or no trustworthy pre-switch baseline.
                return {"waiting": True}
            return snap
        items = [row for page in _pages(driver, read) for row in page["rows"]]
        if len({r["wid"] for r in items}) != len(items):
            raise TableReadError("资源列表含重复班级，无法确认分页完整")
        return items


# ---------- 建课表 ----------
def _read_capture_page(driver, table, wid):
    if not driver.use(table) or not _workshop(driver.current_url(), wid):
        raise TableReadError("无法返回原课程表标签")
    return _json(driver, READ_TABLE)


def _restore_table(driver, table, wid, expected, page_number):
    driver.eval("history.back()")
    def returned():
        # history.back() can destroy the outgoing execution context before the
        # next document is ready. Read only after the expected route returns.
        if not _workshop(driver.current_url(), wid):
            return None
        try:
            _guard(driver)
            snap = _read_capture_page(driver, table, wid)
        except BlockedPage:
            raise
        except TableReadError:
            return None
        return None if snap.get("waiting") else snap
    snap = _wait(returned, "课程详情无法返回原班级课程表")
    if snap == expected:
        return
    for number, restored in enumerate(_pages(driver, lambda: _read_capture_page(driver, table, wid)), 1):
        if number == page_number and restored == expected:
            return
        if number >= page_number:
            break
    raise TableReadError("详情返回后无法恢复原分页，已停止建表")


def _capture_id(driver, table, wid, page, index, page_number):
    if _read_capture_page(driver, table, wid) != page:
        raise TableReadError("课程表内容已改变，无法确认当前行")
    js = (_TABLE_JS + "const row=rows[" + str(index) + "];" + r"""
const action = row.querySelector("td:last-child .edit-block") ||
               row.querySelector("td:last-child a,td:last-child button") || row.cells[5];
action.scrollIntoView({block:"center"});
const r=action.getBoundingClientRect();
return {x:r.x+r.width/2,y:r.y+r.height/2,row:items[rows.indexOf(row)]};
""")
    target = _json(driver, "(() => {" + js + "})()")
    if target.get("row") != page["rows"][index]:
        raise TableReadError("点击前课程行发生变化")
    before = {t.id for t in _tabs(driver)}
    if hasattr(driver, "mark_opener"):
        driver.mark_opener(table)
    driver.click(target["x"], target["y"])

    def opened():
        live = _tabs(driver)
        current = next((t for t in live if t.id == table.id), None)
        if current is None:
            raise TableReadError("课程表标签已关闭")
        if not _workshop(current.url, wid):
            if not driver.use(current):
                raise TableReadError("无法核对课程表跳转")
            _guard(driver)
            cid = _course(current.url, wid, "detail") or _course(current.url, wid, "play")
            if cid:
                return current, cid
            raise TableReadError("课程操作离开了原表，未保存不完整的课表")
        candidates = []
        for tab in live:
            if tab.id in before:
                continue
            cid = _course(tab.url, wid, "detail") or _course(tab.url, wid, "play")
            if cid:
                candidates.append((tab, cid))
            elif getattr(driver, "opened_by", lambda *_: False)(tab, table) and driver.use(tab):
                _guard(driver)
        if len(candidates) > 1:
            raise TableReadError("课程点击后出现多个详情页，无法确认课程编号")
        return candidates[0] if candidates else None

    try:
        child, cid = _wait(opened, "未打开课程详情页")
    except BlockedPage:
        raise
    except _WaitTimeout:
        if not driver.use(table) or not _workshop(driver.current_url(), wid):
            raise TableReadError("无法返回原课程表")
        _guard(driver)
        return ""
    if child.id == table.id:
        _restore_table(driver, table, wid, page, page_number)
        return cid
    if not driver.opened_by(child, table) or not driver.use(child):
        raise TableReadError("课程页来源不明，请重新读取")
    _guard(driver)
    if not driver.close(child):
        raise TableReadError("课程详情未能安全关闭，已停止建表")
    if not driver.use(table):
        raise TableReadError("关闭课程详情后无法返回原表")
    return cid


def capture(driver, wid, log=print):
    with _temporary(driver, workshop_url(wid), lambda url: _workshop(url, wid)) as table:
        courses = []
        pages = _pages(driver, lambda: _read_capture_page(driver, table, wid))
        for page_number, page in enumerate(pages, 1):
            for index, row in enumerate(page["rows"]):
                cid = _capture_id(driver, table, wid, page, index, page_number)
                courses.append({**row, "i":len(courses), "cid":cid,
                                "manual":not row["type"].startswith("视频")})
                log(f"[{len(courses)-1}] {'OK' if cid else 'MISS'} {row['title'][:24]}")
        ids = [row["cid"] for row in courses if row["cid"]]
        if len(ids) != len(set(ids)):
            raise TableReadError("不同课程行返回了相同的课程编号，请重新核对课程表")
        log(f"已映射 {len(ids)}/{len(courses)} 门课程")
        return {"workshop":wid, "courses":courses}

# ---------- 进入学习 / 起播 ----------
def _entry(driver, cid, wid, owned):
    existing = find_tab(driver, cid, wid, "play")
    if existing:
        _guard(driver)
        return existing
    detail = driver.open(detail_url(cid, wid), new_tab=True)
    owned.add(detail.id)
    before = {t.id for t in _tabs(driver)}

    def locate(check_button=True):
        for tab in _tabs(driver):
            is_detail = tab.id == detail.id
            if not is_detail and (tab.id in before or not driver.opened_by(tab, detail)):
                continue
            if not driver.use(tab):
                continue
            if not is_detail:
                owned.add(tab.id)
            _guard(driver)
            if _on(driver, cid, wid, "play"):
                return ("play", tab)
            if check_button and is_detail and _on(driver, cid, wid, "detail"):
                raw = driver.eval(ENTER_JS)
                if isinstance(raw, str) and raw.startswith("{"):
                    return ("detail", (tab, json.loads(raw)))
        return None

    result, value = _wait(locate, "详情页未显示可用的学习入口")
    if result == "play":
        return value
    detail, coords = value
    _guard(driver)
    if hasattr(driver, "mark_opener"):
        driver.mark_opener(detail)
    driver.hover(coords["x"], coords["y"])
    driver.click(coords["x"], coords["y"])

    def playing():
        # A same-tab redirect keeps the original target; a popup has its own target.
        result = locate(check_button=False)
        return result[1] if result and result[0] == "play" else None

    play = _wait(playing, "点击学习入口后未进入指定课程")
    if play.id != detail.id:
        current_detail = next((t for t in _tabs(driver) if t.id == detail.id), None)
        if current_detail and _course(current_detail.url, wid, "detail") == cid:
            driver.close(current_detail)
    if not driver.use(play) or not _on(driver, cid, wid, "play"):
        raise TableReadError("无法核对刚打开的播放页面")
    return play


def enter_play(driver, cid, wid, log=print):
    try:
        return bool(_entry(driver, cid, wid, set()))
    except TableReadError as exc:
        log(str(exc))
        return False


def set_speed(driver):
    """用播放器自己的倍速菜单设 2x：悬停唤出控制栏 → 点当前倍速 → 点 2.0x → 读回 label=2.0x。"""
    geo = driver.eval('(function(){var v=document.querySelector("video");if(!v)return null;var r=v.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()')
    try:
        g = json.loads(geo)
        cx, cy = g["x"], g["y"]
    except Exception:
        cx, cy = 700, 400
    for _ in range(3):
        _guard(driver)
        driver.hover(cx, cy)
        time.sleep(0.8)
        try:
            driver.eval(OPEN_RATE_MENU)   # 点播放器自己的“当前倍速”控件
            time.sleep(1.2)
            driver.eval(PICK_2X)          # 选 2.0x
            time.sleep(1.0)
        except Exception:
            pass
        try:
            d = json.loads(driver.eval(STATE))
            if d.get("rate") == 2 and "2.0x" in (d.get("label") or ""):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def row_completed(row):
    return (row.get("prog", "").strip() == "100%"
            or (row.get("act") or "").strip() in ("立即回看", "回看", "已完成"))


def sync_done(driver, wid, courses):
    rows = workshop_rows(driver, wid)
    count = Counter(_norm(r.get("title", "")) for r in rows)
    saved_count = Counter(_norm(c.get("title", "")) for c in courses)
    if count != saved_count:
        raise CourseListChanged("当前课程表与已保存的课程清单不一致，请重新读取课程表")
    completed = {_norm(r["title"]) for r in rows if row_completed(r)}
    return {c["cid"] for c in courses if c.get("cid") and _norm(c["title"]) in completed
            and count[_norm(c["title"])] == 1}


def start(driver, cid, wid, confirm=True, log=print):
    ids = set()
    try:
        play = _entry(driver, cid, wid, ids)
        result = _start_player(driver, play, cid, wid, confirm, log)
    except BlockedPage as exc:
        result = {"ok": False, "stage": "blocked", "reason": exc.reason}
    except TableReadError as exc:
        log(str(exc))
        result = {"ok": False, "stage": "entry_failed", "reason": str(exc)}
    tabs = driver.list_tabs() or []
    if result.get("stage") == "blocked":
        # Preserve the verification page and its focus for the user.
        result["owned_tabs"] = [{"id": t.id, "url": t.url} for t in tabs if t.id in ids]
    else:
        result["owned_tabs"] = [_owned(driver, t) for t in tabs if t.id in ids]
    return result


def _start_player(driver, play, cid, wid, confirm, log):
    _guard(driver)
    time.sleep(0.3)
    if driver.eval(FIND_PLAYER) not in ("ok", "cached"):
        time.sleep(3)
        _guard(driver)
        if driver.eval(FIND_PLAYER) not in ("ok", "cached"):
            return {"ok": False, "stage": "noplayer"}
    # 先起播（静音+播放），控制栏才可操作；再设倍速并读回
    _guard(driver)
    try:
        driver.eval(SETUP)
    except Exception:
        pass
    time.sleep(1.5)
    ok_speed = set_speed(driver)
    if not ok_speed:
        log("⚠ 倍速未确认到 2.0x（界面可能仍显示 1.0x），继续确认起播")
    _guard(driver)
    try:
        s1 = json.loads(driver.eval(SETUP))
    except Exception:
        s1 = {}
    if not confirm:
        return {"ok": True, "stage": "unconfirmed", "s1": s1}
    s2 = {}
    growth = -1
    for _ in range(3):   # 起播可能慢：最多采样 3 次，每次 14 秒
        time.sleep(14)
        if not driver.use(play):
            return {"ok": False, "stage": "notab2"}
        _guard(driver)
        if not _on(driver, cid, wid, "play"):
            return {"ok": False, "stage": "notab2"}
        try:
            s2 = json.loads(driver.eval(STATE))
        except Exception:
            return {"ok": False, "stage": "stateparse"}
        growth = (s2.get("ct", -1) - s1.get("ct", -1)) if s1.get("ct", -1) >= 0 else -1
        if growth > 3:
            break
    s2["growth"] = round(growth, 1)
    s2["ok"] = bool(growth > 3)
    return s2

def start_pending(driver, st, concurrency, log=print, should_stop=None):
    """Fill available slots one by one; keep state recoverable between starts."""
    if concurrency < 1:
        raise ValueError("并发门数须大于零")
    if st.get("paused_reason") or (should_stop and should_stop()):
        log("任务已暂停")
        return [], None
    wid = st["workshop"]
    courses = st["courses"]
    # An incomplete live table must never be interpreted as zero completed.
    try:
        actual = sync_done(driver, wid, courses)
    except TableReadError as exc:
        reason = getattr(exc, "reason", None)
        if reason in ("login", "captcha", "restriction"):
            st["paused_reason"] = reason
        else:
            st["attention_reason"] = str(exc)
        raise
    st["verified_table_version"] = 1
    st["last_sync"] = time.time()
    done = set(actual)
    st["done"] = sorted(done)
    active = set(st.get("active", []))
    excluded = done | active | set(st.get("failed", {})) | set(st.get("done_open", []))
    started = []
    for course in courses:
        if len(active) >= concurrency or (should_stop and should_stop()):
            break
        cid = course.get("cid")
        if not cid or cid in excluded or course.get("manual"):
            continue
        result = start(driver, cid, wid, log=log)
        owned = st.setdefault("owned_tabs", [])
        for record in result.get("owned_tabs", []):
            if record not in owned:
                owned.append(record)
        if not result.get("ok"):
            why = result.get("reason") or result.get("stage") or "未确认"
            if why in ("login", "captcha", "restriction"):
                st["paused_reason"] = why
            else:
                st["attention_reason"] = why
                st.setdefault("failed", {})[cid] = why
            log(f"未能确认起播 {course['title']}（{why}），已停止补课")
            return started, course
        active.add(cid)
        excluded.add(cid)
        st["active"] = sorted(active)
        started.append(cid)
        log(f"已确认在播 {course['title']}")
    return started, None


def check(driver, cid, wid):
    if not find_tab(driver, cid, wid, "play"):
        return {"ok": False, "stage": "notab"}
    blk = detect_block(driver)
    if blk:
        return {"ok": False, "stage": "blocked", "reason": blk}
    s = None
    for _ in range(2):
        try:
            s = json.loads(driver.eval(STATE))
        except Exception:
            s = None
        if s and s.get("ct", -1) >= 0:
            break
        # 页面重载后 __player 缓存失效：重新定位播放器再读
        driver.eval(FIND_PLAYER)
        time.sleep(1)
    if s is None:
        return {"ok": False, "stage": "stateparse"}
    return s

def resume(driver, cid, wid):
    if not find_tab(driver, cid, wid, "play"):
        return {"ok": False, "stage": "notab"}
    blk = detect_block(driver)
    if blk:
        return {"ok": False, "stage": "blocked", "reason": blk}
    driver.eval(FIND_PLAYER)
    return driver.eval(SETUP)

def close(driver, cid, wid):
    t = find_tab(driver, cid, wid, "play")
    if not t:
        return False
    if not _on(driver, cid, wid, "play"):
        return False
    return driver.close(t)

def verify(driver, wid, title):
    try:
        rows = workshop_rows(driver, wid)
    except BlockedPage as exc:
        return {"confirmed": False, "reason": exc.reason}
    except TableReadError as exc:
        return {"confirmed": False, "reason": str(exc)}
    matches = [r for r in rows if _norm(r["title"]) == _norm(title)]
    if len(matches) != 1:
        return {"confirmed": False, "reason": "ambiguous_title" if matches else "course_row_not_found",
                "rows": len(rows)}
    row = matches[0]
    return {"confirmed": row_completed(row), "prog": row["prog"], "act": row["act"]}


def list_play_cids(driver, wid):
    return [cid for t in _tabs(driver) if (cid := _course(t.url, wid, "play"))]
