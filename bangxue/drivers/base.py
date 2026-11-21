"""驱动抽象：所有浏览器驱动实现同一接口，流程层不关心底层是 WebBridge / Playwright / 其它。"""

class Tab:
    def __init__(self, id, url):
        self.id = id
        self.url = url
    def __repr__(self):
        return f"Tab({self.id}, {self.url[-40:]})"

class Driver:
    """浏览器驱动接口。"""
    name = "base"

    def available(self):
        """当前环境是否可用（依赖是否装好、服务是否在线）。"""
        raise NotImplementedError

    def list_tabs(self):
        """返回 [Tab]；查询失败返回 None（区别于空列表）。"""
        raise NotImplementedError

    def open(self, url, new_tab=True):
        """打开 URL，返回 Tab。"""
        raise NotImplementedError

    def use(self, tab):
        """把 tab 设为当前操作目标，返回是否成功（失败不猜）。"""
        raise NotImplementedError

    def current_url(self):
        raise NotImplementedError

    def eval(self, js):
        raise NotImplementedError

    def click(self, x, y):
        """可信鼠标点击。"""
        raise NotImplementedError

    def hover(self, x, y):
        """移动鼠标（唤出播放器控制栏），不点击。"""
        raise NotImplementedError

    def owns(self, tab):
        return tab.id in self._owned_urls

    def owned_record(self, tab):
        if not self.owns(tab):
            raise RuntimeError("没有此标签的创建凭据")
        self._owned_urls[tab.id] = tab.url
        return {"driver": self.name, "id": tab.id, "url": tab.url}

    def claim_popup(self, tab, parent):
        if not self.owns(parent) or not self.opened_by(tab, parent):
            return False
        self._owned_urls[tab.id] = tab.url
        return True

    def close(self, tab):
        """关闭指定 tab（调用方负责关前回验）。"""
        raise NotImplementedError

    def bring_to_front(self):
        """激活/焦点模拟，让后台媒体能加载。"""
        raise NotImplementedError

    def _select_current(self, url):
        tab = next((t for t in self.list_tabs() or [] if t.url == url), None)
        if tab is None or not self.use(tab) or self.current_url() != url:
            raise RuntimeError("未能核对当前操作标签")

    def current_matches(self):
        return self.current_url() == self._active_url

    def close_all(self):
        """只关闭本实例记录的页；保留地址已变或来源未知的页。"""
        tabs = self.list_tabs()
        if tabs is None:
            return False
        live = {tab.id: tab for tab in tabs}
        ok = True
        for key, url in list(self._owned_urls.items()):
            if key not in live:
                self._owned_urls.pop(key, None)
            elif live[key].url != url or not self.close(live[key]):
                ok = False
        return ok
