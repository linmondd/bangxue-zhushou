"""班级级操作：读课程表、判断整班完成、报名。"""
import json, time

from . import flow


def read_class_table(driver, wid):
    """打开班级课程表读行，读完关掉临时标签。读不到返回 []。"""
    tab = driver.open(flow.workshop_url(wid), new_tab=True)
    rows = []
    for _ in range(25):
        time.sleep(0.7)
        href = driver.current_url()
        if isinstance(href, str) and "myworkshop/detail" in href and wid in href:
            try:
                rows = json.loads(driver.eval(flow.READ_TABLE))
            except Exception:
                rows = []
            if rows:
                break
    href2 = driver.current_url()
    if isinstance(href2, str) and "myworkshop/detail" in href2 and wid in href2:
        try:
            driver.close(tab)
        except Exception:
            pass
    return rows


def progress(rows):
    total = len(rows)
    done = sum(1 for r in rows
               if r.get("prog", "").strip() == "100%" or "回看" in (r.get("act") or "") or "已完成" in (r.get("act") or ""))
    return done, total


def is_complete(rows):
    if not rows:
        return False
    done, total = progress(rows)
    return total > 0 and done == total


def ensure_enrolled(driver, wid):
    """打开班级公开详情页；若有「立即报名」则可信点击报名。返回是否已报名。"""
    tab = driver.open(f"https://u.ccb.com/workshop/#/detail?id={wid}", new_tab=True)
    time.sleep(8)
    enrolled = True
    r = driver.eval('(function(){var els=[...document.querySelectorAll("*")].filter(function(e){return e.children.length===0&&/^立即报名$/.test(e.textContent.trim())&&e.getBoundingClientRect().width>0;});if(!els.length)return "none";var el=els[0];el.scrollIntoView({block:"center"});var b=el.getBoundingClientRect();return JSON.stringify({x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)});})()')
    if r and r != "none":
        try:
            d = json.loads(r)
            driver.hover(d["x"], d["y"])
            time.sleep(0.3)
            driver.click(d["x"], d["y"])
            time.sleep(5)
            txt = driver.eval('(function(){return JSON.stringify([...document.querySelectorAll("*")].filter(function(e){return e.children.length===0&&/^(立即报名|解锁并立即学习|立即学习|继续学习)$/.test(e.textContent.trim());}).map(function(e){return e.textContent.trim();}));})()')
            vals = json.loads(txt) if txt else []
            enrolled = "立即报名" not in vals
        except Exception:
            enrolled = False
    # 关掉公开详情页（回验 URL）
    try:
        href = driver.current_url()
        if isinstance(href, str) and "/workshop/#/detail" in href:
            t = next((x for x in (driver.list_tabs() or []) if x.url == href), None)
            if t:
                driver.close(t)
    except Exception:
        pass
    return enrolled
