"""流程层：建课表 / 进入学习 / 起播 / 检查 / 完成回验 / 关页。与驱动无关。"""
import json, re, time

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

READ_TABLE = r"""
(function(){
  var rows=[...document.querySelectorAll('table tbody tr')];
  return JSON.stringify(rows.map(function(r){var t=[...r.querySelectorAll('td')];
    return {title:(t[1]?t[1].textContent:'').trim(), prog:(t[4]?t[4].textContent:'').trim(), act:(t[5]?t[5].textContent:'').trim()};}));
})()
"""

DETECT_BLOCK = r"""
(function(){
  var t=document.body?document.body.innerText:"";
  if(/密码登录|短信登录|获取验证码|统一手机号登录/.test(t)) return "login";
  if(/验证码/.test(t)) return "captcha";
  if(/4008|缓冲数据超时/.test(t)) return "4008";
  if(/已下架/.test(t)) return "removed";
  if(/需要访问互联网/.test(t)) return "network";
  return "";
})()
"""

DISMISS_OVERLAYS = r"""
(function(){
  var closed=0;
  var sels=[".el-dialog__headerbtn",".el-message-box__headerbtn",".el-message__closeBtn",".el-notification__closeBtn"];
  sels.forEach(function(s){var e=document.querySelector(s); if(e){try{e.click();closed++;}catch(x){}}});
  var texts=["知道了","我知道了","关闭"];
  var btns=[...document.querySelectorAll("button,.el-button,span,div")].filter(function(e){
    if(e.children.length>0) return false;
    if(texts.indexOf(e.textContent.trim())<0) return false;
    var b=e.getBoundingClientRect();
    if(!b.width||!b.height) return false;
    return !!e.closest(".el-dialog,.el-message-box,.el-message,.el-notification");
  });
  btns.forEach(function(e){try{e.click();closed++;}catch(x){}});
  return closed;
})()
"""

def dismiss_overlays(driver):
    """操作前关闭会顶动布局的弹窗/提示（知道了/关闭/×），返回关闭数量。"""
    try:
        return driver.eval(DISMISS_OVERLAYS) or 0
    except Exception:
        return 0

def detect_block(driver):
    """识别登录失效/验证码/4008/下架等系统级阻断，返回原因或空串。"""
    try:
        return driver.eval(DETECT_BLOCK) or ""
    except Exception:
        return ""

def read_table_rows(driver, max_pages=10):
    """读课程表；若存在可用“下一页”则逐页累积（最多 10 页）。"""
    rows = []
    seen = set()
    for _ in range(max_pages):
        try:
            cur = json.loads(driver.eval(READ_TABLE))
        except Exception:
            cur = []
        for r in cur:
            k = (r.get("title"), r.get("prog"), r.get("act"))
            if k not in seen:
                seen.add(k)
                rows.append(r)
        nxt = driver.eval('(function(){var b=document.querySelector(".el-pagination .btn-next, button.btn-next");if(!b)return "none";if(b.disabled||String(b.className).indexOf("disabled")>=0)return "disabled";b.click();return "ok";})()')
        if nxt != "ok":
            break
        time.sleep(1.2)
    return rows


# ---------- 工具 ----------
def play_url(cid, wid):
    return f"https://learning-platform.local/course/#/play/{cid}?workshopId={wid}"

def detail_url(cid, wid):
    return f"https://learning-platform.local/course/#/detail/{cid}?refresh=1&workshopId={wid}&enrefresh=1"

def workshop_url(wid):
    return f"https://learning-platform.local/workshop/#/myworkshop/detail?id={wid}"

def _norm(s):
    s = str(s)
    for a, b in [("（", "("), ("）", ")"), ("：", ":"), ("，", ","), ("—", "-"), ("－", "-")]:
        s = s.replace(a, b)
    return "".join(s.split())

def _part(s):
    m = re.search(r"[\(（]([上中下])[\)）]", str(s))
    return m.group(1) if m else ""

def _find(driver, cid, wid, route):
    tabs = driver.list_tabs()
    if not tabs:
        return None
    for t in tabs:
        if f"/{route}/{cid}" in t.url and f"workshopId={wid}" in t.url:
            return t
    return None

def _on(driver, cid, wid, route):
    u = driver.current_url()
    return isinstance(u, str) and f"/{route}/{cid}" in u and f"workshopId={wid}" in u

def find_tab(driver, cid, wid, route="play"):
    t = _find(driver, cid, wid, route)
    if not t:
        return None
    if driver.use(t) and _on(driver, cid, wid, route):
        return t
    return None

# ---------- 建课表 ----------
LIBRARY_SCOPE_JS = r"""
(function(){
  var out=null, seen={}, all=document.querySelectorAll("*");
  function walk(el){
    var v=el.__vue__; if(!v) return;
    var c=v;
    while(c){
      if(!seen[c._uid]){
        seen[c._uid]=1;
        var d=c.$data;
        if(d&&d.tableList&&d.tableList.length&&c.$el&&c.$el.offsetWidth){
          out=d.tableList.map(function(x){return {id:x.knowledgeId,title:x.title};});
        }
      }
      c=c.$parent;
    }
  }
  for(var i=0;i<all.length;i++) walk(all[i]);
  return JSON.stringify(out||[]);
})()
"""

WORKSHOP_COURSES_JS = r"""
(function(){
  var el=document.querySelector('.workshop-content'), v=el&&el.__vue__;
  if(!v||!v.$data||!v.$data.myWorkshopDetail) return '[]';
  var d=v.$data.myWorkshopDetail;
  var list=d.contentList||d.courseList||[];
  return JSON.stringify(list.map(function(x){
    var t=x.filetype||x.showType||'';
    return {cid:x.knowledgeId||'', title:x.knowledgeName||x.title||'',
            prog:(x.progress===null||x.progress===undefined)?'':String(x.progress)+'%',
            type:t, kngType:x.kngType||'', url:x.kngDetailUrl||''};
  }));
})()
"""

def read_library_classes(driver, tab_name=None):
    """从资源库页面读取某个 tab 下的班级列表（wid+title）。"""
    tab = driver.open("https://learning-platform.local/portal/#/centralizedResource", new_tab=True)
    time.sleep(9)
    if tab_name:
        try:
            driver.eval('(function(){var e=[...document.querySelectorAll("[role=tab],.el-tabs__item")].find(function(x){return x.textContent.trim().indexOf(%s)>=0;});if(e){e.click();return true;}return false;})()' % json.dumps(tab_name))
            time.sleep(2)
        except Exception:
            pass
    try:
        raw = driver.eval(LIBRARY_SCOPE_JS)
        items = json.loads(raw) if raw else []
    except Exception:
        items = []
    try:
        driver.close(tab)
    except Exception:
        pass
    return [{"wid": x.get("id"), "title": x.get("title", "")} for x in items if x.get("id")]

def capture(driver, wid, log=print):
    driver.open(workshop_url(wid), new_tab=False)
    time.sleep(10)
    href = driver.current_url()
    if not (isinstance(href, str) and "myworkshop/detail" in href and wid in href):
        log("ERROR: 未进入专题班课程表页，放弃建表")
        return None
    # 首选：直接读页面 Vue 数据里的 contentList（只读，不点按钮，不调接口）
    try:
        raw = driver.eval(WORKSHOP_COURSES_JS)
        items = json.loads(raw) if raw else []
    except Exception:
        items = []
    if items and any(x.get("cid") for x in items):
        courses = []
        for i, x in enumerate(items):
            t = (x.get("type") or "").strip()
            if "Video" in t:
                typ = "视频"
            elif "CoursePackage" in t:
                typ = "课程包"
            elif "Scorm" in t:
                typ = "scorm"
            elif "Exam" in t:
                typ = "考试"
            else:
                typ = t
            prog = x.get("prog", "")
            courses.append({"i": i, "cid": x.get("cid", ""), "title": x.get("title", ""),
                            "prog": prog, "act": ("立即回看" if prog == "100%" else "立即学习"),
                            "type": typ, "manual": not typ.startswith("视频")})
        ok = sum(1 for c in courses if c["cid"])
        log(f"从页面数据读取 {ok}/{len(courses)} 门课程（无需逐行点击）")
        return {"workshop": wid, "courses": courses}
    n = driver.eval("[...document.querySelectorAll('table tbody tr')].length") or 0
    try:
        n = int(n)
    except Exception:
        n = 0
    courses, missing = [], 0
    for i in range(n):
        r = driver.eval("""(function(){var rows=[...document.querySelectorAll('table tbody tr')];if(%d>=rows.length)return 'END';
        var sp=rows[%d].querySelector('td:last-child .edit-block')||rows[%d].querySelector('td:last-child');if(!sp)return 'NOSP';
        sp.scrollIntoView({block:'center'});var r=sp.getBoundingClientRect();
        var tds=rows[%d].querySelectorAll('td');
        return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),
          type:(tds[0]?tds[0].textContent:'').trim(),
          title:(tds[1]?tds[1].textContent:'').trim(), prog:(tds[4]?tds[4].textContent:'').trim(),
          act:(tds[5]?tds[5].textContent:'').trim()});})()""" % (i, i, i, i))
        try:
            d = json.loads(r)
        except Exception:
            continue
        before = set(t.url for t in (driver.list_tabs() or []))
        driver.click(d["x"], d["y"])
        cid = ""
        for _ in range(12):
            time.sleep(0.5)
            now = set(t.url for t in (driver.list_tabs() or []))
            for u in (now - before):
                m = re.search(r"/course/#/(?:detail|play)/([a-f0-9-]+)", u)
                if m:
                    cid = m.group(1)
                    break
            if cid:
                break
        if cid:
            t = _find(driver, cid, wid, "detail") or _find(driver, cid, wid, "play")
            if t:
                driver.close(t)
        else:
            missing += 1
        rtype = (d.get("type") or "").strip()
        manual = not rtype.startswith("视频")
        courses.append({"i": i, "cid": cid, "title": d.get("title", ""), "prog": d.get("prog", ""),
                        "act": d.get("act", ""), "type": rtype, "manual": manual})
        log(f"[{i}] {'OK' if cid else 'MISS'} {cid[:8]} {d.get('prog','')} {d.get('title','')[:24]}")
        time.sleep(0.3)
    ok = sum(1 for c in courses if c["cid"])
    log(f"mapped {ok}/{n}")
    if missing:
        log(f"⚠ 有 {missing} 门未捕获 courseId（监控会告警并计入未映射）")
    return {"workshop": wid, "courses": courses}

# ---------- 进入学习 / 起播 ----------
def enter_play(driver, cid, wid, log=print):
    """可靠进入学习：详情页 → 可信点击「我要学习」→ 接管 /play/。
    注意：播放页可能开在【新标签】，不能只看当前标签是否跳转。"""
    if _find(driver, cid, wid, "play") and find_tab(driver, cid, wid, "play"):
        return True
    detail_tab = driver.open(detail_url(cid, wid), new_tab=True)
    time.sleep(8)
    if not find_tab(driver, cid, wid, "detail"):
        # 可能已自动跳到播放页
        pt = _find(driver, cid, wid, "play")
        return bool(pt and driver.use(pt))
    for _ in range(3):
        dismiss_overlays(driver)
        time.sleep(0.3)
        r = driver.eval(ENTER_JS)
        try:
            d = json.loads(r)
        except Exception:
            time.sleep(2)
            continue
        driver.hover(d["x"], d["y"])
        time.sleep(0.3)
        driver.click(d["x"], d["y"])
        for _ in range(20):
            time.sleep(0.8)
            pt = _find(driver, cid, wid, "play")
            if pt and driver.use(pt):
                # 播放页开在新标签：关掉详情页，保持页面最少
                try:
                    if detail_tab:
                        driver.close(detail_tab)
                except Exception:
                    pass
                return True
        find_tab(driver, cid, wid, "detail")
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
        dismiss_overlays(driver)
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
    # 兜底：直接设播放器速度（界面 label 可能不同步，返回 False）
    driver.eval('(function(){var p=window.__player;if(p){try{p.setSpeed(2);}catch(e){}}return "fallback";})()')
    return False

def sync_done(driver, wid, courses):
    """刷新课程表，把已 100%/立即回看 的课标为 done（防止重复学习已完成课程）。"""
    tab = driver.open(workshop_url(wid), new_tab=True)
    rows = []
    for _ in range(25):
        time.sleep(0.7)
        href = driver.current_url()
        if isinstance(href, str) and "myworkshop/detail" in href and wid in href:
            try:
                rows = json.loads(driver.eval(READ_TABLE))
            except Exception:
                rows = []
            if rows:
                break
    href2 = driver.current_url()
    if isinstance(href2, str) and "myworkshop/detail" in href2 and wid in href2:
        driver.close(tab)
    done = set()
    for c in courses:
        cid = c.get("cid")
        if not cid:
            continue
        nt = _norm(c.get("title", ""))
        suf = _part(c.get("title", ""))
        for r in rows:
            if _norm(r.get("title", "")) == nt and _part(r.get("title", "")) == suf:
                if r.get("prog") == "100%" or "回看" in (r.get("act") or "") or "已完成" in (r.get("act") or ""):
                    done.add(cid)
                break
    return done

def start(driver, cid, wid, confirm=True, log=print):
    if not enter_play(driver, cid, wid, log=log):
        driver.open(play_url(cid, wid), new_tab=True)
        time.sleep(8)
    t = find_tab(driver, cid, wid, "play")
    if not t:
        return {"ok": False, "stage": "notab"}
    dismiss_overlays(driver)
    time.sleep(0.3)
    if driver.eval(FIND_PLAYER) not in ("ok", "cached"):
        time.sleep(3)
        if driver.eval(FIND_PLAYER) not in ("ok", "cached"):
            return {"ok": False, "stage": "noplayer"}
    # 先起播（静音+播放），控制栏才可操作；再设倍速并读回
    try:
        driver.eval(SETUP)
    except Exception:
        pass
    time.sleep(1.5)
    ok_speed = set_speed(driver)
    if not ok_speed:
        log("⚠ 倍速未确认到 2.0x（界面可能仍显示 1.0x），继续确认起播")
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
        if not find_tab(driver, cid, wid, "play"):
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

def start_pending(driver, st, concurrency, log=print):
    """按状态文件逐门起播（供 CLI start 和班级队列共用）。返回 (started, failed)。"""
    wid = st["workshop"]
    courses = st["courses"]
    try:
        actual = sync_done(driver, wid, courses)
        log(f"课程表核对：发现已完成 {len(actual)} 门，将跳过")
    except Exception as e:
        log(f"课程表核对失败，保守停止：{e}")
        return [], None
    done = set(st.get("done", [])) | actual
    st["done"] = list(done)
    active = set(st.get("active", []))
    slots = max(0, int(concurrency) - len(active))
    pending = [c for c in courses
               if c.get("cid") and c["cid"] not in done and c["cid"] not in active
               and not c.get("manual")
               and c.get("prog") != "100%" and "回看" not in (c.get("act") or "")]
    manual_left = len([c for c in courses if c.get("manual") and c["cid"] not in done])
    if manual_left:
        log(f"另有 {manual_left} 门需人工学习（scorm/课程包/考试），已跳过")
    started, failed = [], None
    log(f"逐门起播：总上限 {concurrency} 门，当前在播 {len(active)}，本次最多补 {slots} 门")
    for c in pending:
        if len(started) >= slots:
            break
        r = start(driver, c["cid"], wid, log=log)
        if r.get("ok"):
            started.append(c["cid"])
            log(f"▶ 已确认在播 {c['title'][:24]} ct={r.get('ct')} growth={r.get('growth')} rate={r.get('rate')} label={r.get('label')}")
        else:
            failed = c
            log(f"✖ 起播未确认 {c['title'][:24]} stage={r.get('stage')}，按规则停止，不再开新页")
            break
        time.sleep(2)
    st["active"] = list(active | set(started))
    return started, failed

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
    driver.open(workshop_url(wid), new_tab=True)
    on = False
    for _ in range(25):
        time.sleep(0.7)
        href = driver.current_url()
        if isinstance(href, str) and "myworkshop/detail" in href and wid in href:
            on = True
            break
    if not on:
        return {"confirmed": False, "reason": "wrong_page_keep"}
    time.sleep(3)
    try:
        rows = json.loads(driver.eval(READ_TABLE))
    except Exception:
        return {"confirmed": False, "reason": "table_read_fail_keep"}
    href2 = driver.current_url()
    if isinstance(href2, str) and "myworkshop/detail" in href2 and wid in href2:
        tabs = driver.list_tabs() or []
        cur = next((t for t in tabs if t.url == href2), None)
        if cur:
            driver.close(cur)
    nt = _norm(title)
    suffix = _part(title)
    for row in rows:
        rt = _norm(row.get("title", ""))
        if rt and rt == nt and _part(row.get("title", "")) == suffix:
            prog, act = row.get("prog", ""), row.get("act", "")
            ok = (prog == "100%") or ("回看" in act) or ("已完成" in act)
            return {"confirmed": bool(ok), "prog": prog, "act": act}
    return {"confirmed": False, "reason": "course_row_not_found", "rows": len(rows)}

def list_play_cids(driver, wid):
    tabs = driver.list_tabs() or []
    out = []
    for t in tabs:
        if "/play/" in t.url and f"workshopId={wid}" in t.url:
            m = re.search(r"/play/([a-f0-9-]+)", t.url)
            if m:
                out.append(m.group(1))
    return out
