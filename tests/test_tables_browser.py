"""Isolated Chromium fixtures intercept all requests and require no platform account."""
import json
import tempfile
import unittest
from unittest.mock import patch

from bangxue import classes, flow
from bangxue.drivers.playwright_driver import PlaywrightDriver
from bangxue.drivers.webbridge import WebBridgeDriver


def table_html(rows, stale=False, total=None):
    items = json.dumps(rows, ensure_ascii=False)
    return """
    <table><tbody></tbody></table>
    <div class="el-pagination"><span class="el-pagination__total"></span>
    <span class="el-pager"><b class="active"></b></span><button class="btn-next">下一页</button></div>
    <script>
    const pages=ITEMS; let page=0;
    function pager(){
      document.querySelector(".active").textContent=page+1;
      document.querySelector(".btn-next").disabled=page===pages.length-1;
    }
    function show(){
      const body=document.querySelector("tbody");body.replaceChildren();
      for(const [title,cid,prog] of pages[page]){
        const row=body.insertRow();
        for(const value of ["视频",title,"","",prog])row.insertCell().textContent=value;
        const button=document.createElement("button");
        button.textContent=prog==="100%"?"立即回看":"立即学习";
        button.onclick=()=>window.open("/course/#/detail/"+cid+"?workshopId=class1","_blank");
        row.insertCell().append(button);
      }
    }
    document.querySelector(".el-pagination__total").textContent="共 COUNT 条";
    document.querySelector(".btn-next").onclick=()=>{page++;pager();if(!STALE)setTimeout(show,80)};
    pager();show();
    </script>""".replace("ITEMS", items).replace("COUNT", str(total if total is not None else
             sum(map(len, rows)))).replace("STALE", json.dumps(stale))


LIBRARY = """
<div role="tablist"><button role="tab" aria-selected="true">全部</button>
<button role="tab" aria-selected="false">华南</button><button role="tab">华南二区</button></div>
<div id="list">资源表</div>
<script>
const el=document.querySelector("#list"), tabs=[...document.querySelectorAll("[role=tab]")];
const data={tableList:[{knowledgeId:"default",title:"默认班"}]};
el.__vue__={$data:data,$el:el};
tabs[1].onclick=()=>{tabs[0].setAttribute("aria-selected","false");
tabs[1].setAttribute("aria-selected","true");
setTimeout(()=>data.tableList=[{knowledgeId:"south",title:"华南班"}],100);};
</script>
"""


class TableBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("需要安装 Playwright 与 Chromium")
        cls.profile = tempfile.TemporaryDirectory()
        cls.driver = PlaywrightDriver(profile_dir=cls.profile.name, headless=True)
        cls.driver._ensure()

    @classmethod
    def tearDownClass(cls):
        cls.driver.shutdown()
        cls.profile.cleanup()

    def setUp(self):
        self.table = table_html([[["第一门","a1","100%"],["第二门","b2","100%"]],
                                  [["第三门","c3","80%"]]])
        self.library = LIBRARY
        self.detail = "<p>课程详情</p>"
        self.requests = []
        def route(req):
            url = req.request.url
            self.requests.append(url)
            if "/workshop/" in url:
                body = self.table
            elif "/portal/" in url:
                body = self.library
            elif "/course/" in url:
                body = self.detail
            else:
                return req.abort()
            req.fulfill(content_type="text/html; charset=utf-8", body=body)
        self.route = route
        self.driver._context.route("**/*", route)
        self.timeout = patch.object(flow, "WAIT_SECONDS", 1.5)
        self.poll = patch.object(flow, "POLL_SECONDS", .025)
        self.timeout.start()
        self.poll.start()

    def tearDown(self):
        self.driver._context.unroute("**/*", self.route)
        self.driver.close_all()
        self.timeout.stop()
        self.poll.stop()

    def test_capture_all_pages_restores_original_tab_and_preserves_duplicate_urls(self):
        existing = self.driver.open(flow.workshop_url("class1"))
        duplicate = self.driver.open(flow.detail_url("a1","class1"))
        result = flow.capture(self.driver, "class1", log=lambda _: None)
        self.assertEqual(["a1","b2","c3"], [r["cid"] for r in result["courses"]])
        ids = {t.id for t in self.driver.list_tabs()}
        self.assertTrue({existing.id, duplicate.id} <= ids)
        self.assertFalse(any(t.id not in {existing.id, duplicate.id} and
                             t.url != "about:blank" for t in self.driver.list_tabs()))
        rows = classes.read_class_table(self.driver, "class1")
        self.assertEqual((2,3), classes.progress(rows))
        self.assertFalse(classes.is_complete(rows))
        self.assertEqual({"a1","b2"}, flow.sync_done(self.driver, "class1", result["courses"]))
        self.assertEqual("80%", flow.verify(self.driver, "class1", "第三门")["prog"])

    def test_capture_same_tab_restores_pagination(self):
        self.table = self.table.replace(
            'window.open("/course/#/detail/"+cid+"?workshopId=class1","_blank")',
            'location.assign("/course/#/detail/"+cid+"?workshopId=class1")')
        rows = flow.capture(self.driver, "class1", log=lambda _: None)["courses"]
        self.assertEqual(["a1", "b2", "c3"], [r["cid"] for r in rows])

    def test_empty_table_and_enrollment_require_explicit_evidence(self):
        self.table = '<table><tbody></tbody></table><p class="el-table__empty-text">暂无课程</p>'
        self.assertEqual([], classes.read_class_table(self.driver, "class1"))
        self.assertFalse(classes.is_complete([]))
        self.table = '<button onclick="this.innerText=&quot;立即学习&quot;">立即报名</button>'
        self.assertTrue(classes.ensure_enrolled(self.driver, "class1"))
        self.table = '<p>加载失败</p>'
        with self.assertRaises(flow.TableReadError):
            classes.ensure_enrolled(self.driver, "class1")

    def test_capture_stops_and_keeps_blocked_popup(self):
        self.detail = '<div role="dialog">请输入验证码</div>'
        with self.assertRaises(flow.BlockedPage) as blocked:
            flow.capture(self.driver, "class1", log=lambda _: None)
        self.assertEqual("captcha", blocked.exception.reason)
        self.assertIn("/detail/a1", self.driver.current_url())
        self.assertTrue(any("/myworkshop/detail" in t.url for t in self.driver.list_tabs()))

    def test_changed_url_never_closes_even_with_matching_target_id(self):
        tab = self.driver.open(flow.detail_url("abc","class1"))
        self.driver.eval("location.hash = '/other'")
        self.assertEqual("unverified", flow.close_owned(self.driver, {"id":tab.id,"url":tab.url}))
        self.assertIn(tab.id, [t.id for t in self.driver.list_tabs()])

    def test_duplicate_titles_never_confirm_either_id(self):
        self.table = table_html([[["同名","a","100%"]],[["同名","b","20%"]]])
        self.assertEqual("ambiguous_title", flow.verify(self.driver,"class1","同名")["reason"])
        self.assertEqual(set(), flow.sync_done(self.driver,"class1",
                            [{"cid":"a","title":"同名"},{"cid":"b","title":"同名"}]))

    def test_stale_and_partial_pages_fail_closed(self):
        rows = [[["甲","a","100%"]],[["乙","b","100%"]]]
        self.table = table_html(rows, stale=True)
        with self.assertRaises(flow.TableReadError):
            classes.read_class_table(self.driver,"class1")
        self.table = table_html(rows, total=5)
        self.assertFalse(flow.verify(self.driver,"class1","甲")["confirmed"])
        with self.assertRaises(flow.TableReadError):
            flow.sync_done(self.driver,"class1",[])

    def test_tab_scope_requires_exact_selected_name_and_fresh_rows(self):
        self.assertEqual(["全部","华南","华南二区"], flow.read_library_tabs(self.driver))
        self.assertEqual([{"wid":"south","title":"华南班"}],
                         flow.read_library_classes(self.driver,"华南"))
        with self.assertRaisesRegex(flow.TableReadError, "华南二区"):
            flow.read_library_classes(self.driver,"华")
        with self.assertRaises(flow.TableReadError):
            flow.read_library_classes(self.driver,"华南二区")
        self.library = LIBRARY.replace('setTimeout(()=>data.tableList=', 'if(false)setTimeout(()=>data.tableList=')
        with self.assertRaises(flow.TableReadError):
            flow.read_library_classes(self.driver,"华南")

    def test_auth_block_and_official_entry_failure_do_not_open_play(self):
        self.detail = '<div role="dialog">请输入验证码<button>关闭</button></div>'
        user_tab = self.driver.open(flow.detail_url("a","class1"))
        r = flow.start(self.driver,"a","class1",confirm=False)
        self.assertEqual(("blocked","captcha"), (r["stage"],r["reason"]))
        self.assertEqual(1, len(r["owned_tabs"]))
        self.assertNotEqual(user_tab.id, r["owned_tabs"][0]["id"])
        self.assertEqual("closed", flow.close_owned(self.driver,r["owned_tabs"][0]))
        self.assertEqual("missing", flow.close_owned(self.driver,r["owned_tabs"][0]))
        self.detail = "<p>尚无可用学习入口</p>"
        result = flow.start(self.driver,"b","class1",confirm=False)
        self.assertEqual("entry_failed", result["stage"])
        self.assertFalse(any("/play/" in t.url for t in self.driver.list_tabs()))

    def test_official_entry_redirect_or_popup_preserves_playing_target(self):
        for action in ["location.href = url", "window.open(url,'_blank')"]:
            with self.subTest(action=action):
                self.detail = '<button onclick="go()">立即学习</button><script>function go(){' + (
                    "const url='/course/#/play/abc?workshopId=class1';" + action + "}</script>")
                ids = set()
                tab = flow._entry(self.driver,"abc","class1",ids)
                self.assertEqual(self.driver.current_url(), flow.play_url("abc","class1"))
                self.assertIn(tab.id,ids)
                self.assertEqual("closed",flow.close_owned(self.driver,{"id":tab.id,"url":tab.url}))

    def test_bridge_duplicate_url_fails_without_selecting_or_closing(self):
        from bangxue.drivers.base import Tab
        bridge = WebBridgeDriver()
        a,b=Tab(1,"https://same"),Tab(2,"https://same")
        with patch.object(bridge,"list_tabs",return_value=[a,b]), patch.object(bridge,"_cmd") as command:
            self.assertFalse(bridge.close(b))
            command.assert_not_called()
