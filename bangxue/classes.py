"""班级级操作：读课程表、判断整班完成、报名。"""
import json

from . import flow


_ENROLL = r"""
(() => {
  const buttons = [...document.querySelectorAll("button,a,.el-button,span")].filter(
    e => e.getClientRects().length && /^(立即报名|解锁并立即学习|立即学习|继续学习|已报名)$/.test(e.textContent.trim()));
  const joined = buttons.some(e => e.textContent.trim() !== "立即报名");
  const signup = buttons.find(e => e.textContent.trim() === "立即报名");
  if (joined && !signup) return JSON.stringify({joined:true});
  if (!signup || joined) return "{}";
  signup.scrollIntoView({block:"center"});
  const r = signup.getBoundingClientRect();
  return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2});
})()
"""


def read_class_table(driver, wid):
    """读取全部分页。明确的报名页或空表可返回空列表，读表错误抛出异常。"""
    accepts = lambda u: flow._workshop(u, wid) or flow._workshop(u, wid, "/detail")
    with flow._temporary(driver, flow.workshop_url(wid), accepts):
        if flow._workshop(driver.current_url(), wid, "/detail"):
            if "x" in json.loads(driver.eval(_ENROLL)):
                return []
            raise flow.TableReadError("班级公开详情没有可核实的报名入口")
        return flow.read_table_rows(driver)


def progress(rows):
    return sum(flow.row_completed(r) for r in rows), len(rows)


def is_complete(rows):
    return bool(rows) and all(flow.row_completed(r) for r in rows)


def ensure_enrolled(driver, wid):
    url = f"https://u.ccb.com/workshop/#/detail?id={wid}"
    accepts = lambda u: flow._workshop(u, wid, "/detail") or flow._workshop(u, wid)
    with flow._temporary(driver, url, accepts):
        def status():
            flow._guard(driver)
            if not accepts(driver.current_url()):
                raise flow.TableReadError("报名过程中离开了目标班级")
            if flow._workshop(driver.current_url(), wid):
                return {"joined": True} if flow.read_table_rows(driver) else None
            return flow._json(driver, _ENROLL) or None
        first = flow._wait(status, "无法核对报名状态")
        if first.get("joined"):
            return True
        driver.hover(first["x"], first["y"])
        driver.click(first["x"], first["y"])
        return flow._wait(lambda: True if (status() or {}).get("joined") else None,
                          "平台未确认报名成功")
