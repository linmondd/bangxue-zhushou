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

    def close(self, tab):
        """关闭指定 tab（调用方负责关前回验）。"""
        raise NotImplementedError

    def bring_to_front(self):
        """激活/焦点模拟，让后台媒体能加载。"""
        raise NotImplementedError

    def close_all(self):
        """关闭本会话/本上下文的所有页面（用于停止）。"""
        raise NotImplementedError
