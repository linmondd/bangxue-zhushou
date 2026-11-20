"""班级级操作：读课程表、判断整班完成、报名。"""
import json, time

from . import flow


def read_class_table(driver, wid, reuse=False):
    """读班级课程表。reuse=True 时复用当前标签顺序导航，避免多标签选错；否则新开临时标签。"""
    if reuse:
        tab = None
        driver.open(flow.workshop_url(wid), new_tab=False)
    else:
        tab = driver.open(flow.workshop_url(wid), new_tab=True)
        driver.use(tab)
    rows = []
    for i in range(25):
        time.sleep(0.7)
        href = driver.current_url()
        if isinstance(href, str) and "myworkshop/detail" in href and wid in href:
            try:
                rows = json.loads(driver.eval(flow.READ_TABLE))
            except Exception:
                rows = []
            if rows:
                break
        elif isinstance(href, str) and "workshop/#/detail" in href and wid in href and i >= 2:
            # 停在公开详情页 = 未报名，别空等 25 轮
            break
    if tab is not None:
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
    tab = driver.open(f"https://learning-platform.local/workshop/#/detail?id={wid}", new_tab=True)
    if not driver.use(tab):
        return False
    for _ in range(20):
        time.sleep(0.7)
        href = driver.current_url()
        if isinstance(href, str) and "workshop" in href and wid in href:
            break
    time.sleep(1)
    enrolled = True
    r = driver.eval('(function(){var a=[...document.querySelectorAll("button")].filter(function(e){return e.textContent.trim().indexOf("立即报名")>=0&&e.getBoundingClientRect().width>0;});if(!a.length)return "none";var el=a[0];el.scrollIntoView({block:"center"});var b=el.getBoundingClientRect();return JSON.stringify({x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)});})()')
    if r and r != "none":
        try:
            d = json.loads(r)
            driver.hover(d["x"], d["y"])
            time.sleep(0.3)
            driver.click(d["x"], d["y"])
            time.sleep(4)
            driver.use(tab)
            href = driver.current_url()
            enrolled = isinstance(href, str) and "myworkshop/detail" in href
            if not enrolled:
                txt = driver.eval('(function(){return JSON.stringify([...document.querySelectorAll("button")].map(function(e){return e.textContent.trim();}).filter(Boolean));})()')
                vals = json.loads(txt) if txt else []
                enrolled = "立即报名" not in vals
        except Exception:
            enrolled = False
    # 临时报名页用完就关，避免标签堆积
    try:
        driver.close(tab)
    except Exception:
        pass
    return enrolled
