"""社区情绪层回归测试：股吧列表解析 / 时间口径 / 窗口过滤 / crawl4ai 兜底引擎链."""

from datetime import datetime, timedelta

import pytest

from tradingagents.dataflows.a_stock import community as comm


# ---------------------------------------------------------------------------
# 夹具：2026-10-06 对 guba.eastmoney.com/list,601208.html 实测的行结构
# ---------------------------------------------------------------------------

def _row_html(post_id, title, reads, replies, time_str, author="股友001"):
    return (
        f'<tr class="listitem"><td><div class="read">{reads}</div></td>'
        f'<td><div class="reply">{replies}</div></td>'
        f'<td><div class="title"><a data-postid="{post_id}" data-posttype="20" '
        f'href="//caifuhao.eastmoney.com/news/{post_id}">{title}</a></div></td>'
        f'<td><div class="author"><a href="//i.eastmoney.com/1">{author}</a></div></td>'
        f'<td><div class="update">{time_str}</div></td></tr>'
    )


def _page(rows_html):
    return (
        '<table><thead class="listhead"></thead><tbody class="listbody">'
        + "".join(rows_html)
        + "</tbody></table>"
    )


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


# ---------------------------------------------------------------------------
# 解析层
# ---------------------------------------------------------------------------

def test_parse_guba_rows_fields():
    html = _page(
        [
            _row_html("1779711394", "假期最后阶段，大线索越来越清楚", 539, 2, "10-06 09:10"),
            _row_html("1779705", "标题带&gt;符号&amp;转义", 10, 0, "10-05 22:00"),
        ]
    )
    rows = comm._parse_guba_rows(html)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["post_id"] == "1779711394"
    assert r0["title"] == "假期最后阶段，大线索越来越清楚"
    assert r0["url"].startswith("https://caifuhao.eastmoney.com/")  # 协议相对链接补全
    assert r0["reads"] == 539 and r0["replies"] == 2
    assert r0["time_str"] == "10-06 09:10"
    assert rows[1]["title"] == "标题带>符号&转义"  # html unescape


def test_parse_guba_rows_skips_malformed():
    html = _page([_row_html("1", "正常帖", 1, 1, "10-06 09:10")]) + '<tr class="listitem"><td>残缺行无标题</td></tr>'
    rows = comm._parse_guba_rows(html)
    assert len(rows) == 1


def test_parse_rendered_shape_trailing_space_and_no_postid():
    """crawl4ai 渲染版实测形状（2026-10-06）：class 带尾随空格、无 data-postid、
    update 带 mod_time 类、属性顺序不同——解析器必须两形态通吃。"""
    chunk = (
        '<tr class="listitem "><td><div class="read">579</div></td>'
        '<td><div class="reply">2</div></td>'
        '<td><div class="title"><a href="//caifuhao.eastmoney.com/news/20261006211009757135710?from=guba" '
        'class="PO" data-cntitle="假期最后阶段，大线索越来越清楚" '
        'title="假期最后阶段，大线索越来越清楚">假期最后阶段，大线索越来越清楚</a></div></td>'
        '<td><div class="author cl"><a class="nametext fl " href="//i.eastmoney.com/4832067854769490">事事早知道</a></div></td>'
        '<td><div class="update mod_time">10-06 22:22</div></td></tr>'
    )
    rows = comm._parse_guba_rows(f'<tbody class="listbody">{chunk}</tbody>')
    assert len(rows) == 1
    r = rows[0]
    assert r["post_id"] == "20261006211009757135710"  # href 末段兜底作去重键
    assert r["title"] == "假期最后阶段，大线索越来越清楚"
    assert r["reads"] == 579 and r["replies"] == 2
    assert r["time_str"] == "10-06 22:22"
    assert r["author"] == "事事早知道"


def test_parse_guba_time_year_rollover_guard():
    now = datetime(2026, 1, 10, 12, 0)
    # "12-31 23:59" 按当年解释落在 1 天以上未来 → 回退上一年
    assert comm._parse_guba_time("12-31 23:59", now) == datetime(2025, 12, 31, 23, 59)
    assert comm._parse_guba_time("01-05 08:00", now) == datetime(2026, 1, 5, 8, 0)
    # 全格式与垃圾输入
    assert comm._parse_guba_time("2025-12-30 10:00", now) == datetime(2025, 12, 30, 10, 0)
    assert comm._parse_guba_time("2025-12-30", now) == datetime(2025, 12, 30)
    assert comm._parse_guba_time("昨天", now) is None
    assert comm._parse_guba_time("", now) is None


# ---------------------------------------------------------------------------
# 引擎链：直连为主，crawl4ai 仅在直连无列表时接管
# ---------------------------------------------------------------------------

def _patch_direct(monkeypatch, html_or_exc):
    calls = []

    def fake_em_get(url, **kwargs):
        calls.append(url)
        if isinstance(html_or_exc, Exception):
            raise html_or_exc
        return _FakeResponse(html_or_exc)

    monkeypatch.setattr(comm, "_em_get", fake_em_get)
    return calls


_NOW_FMT = (datetime.now() - timedelta(days=1)).strftime("%m-%d %H:%M")
_OLD_FMT = (datetime.now() - timedelta(days=10)).strftime("%m-%d %H:%M")
_TWO_ROW_PAGE = _page(
    [
        _row_html("2", "新帖有人讨论", 300, 5, _NOW_FMT),
        _row_html("1", "旧帖早已沉底", 100, 1, _OLD_FMT),
    ]
)


def test_direct_success_no_render_call(monkeypatch):
    _patch_direct(monkeypatch, _TWO_ROW_PAGE)
    monkeypatch.setattr(
        comm, "_crawl_render_html",
        lambda url: (_ for _ in ()).throw(AssertionError("直连成功不应触发渲染兜底")),
    )
    out = comm.get_community_sentiment("601208", look_back_days=5)
    assert "股吧社区讨论（601208）" in out
    assert "东方财富股吧 (guba.eastmoney.com)" in out  # 来源可引用
    assert "样本 1 帖" in out  # 10 天前的旧帖被窗口过滤
    assert "累计阅读 300 次 / 评论 5 条" in out
    assert "新帖有人讨论" in out
    assert "旧帖早已沉底" not in out


def test_anti_bot_shell_escalates_to_render(monkeypatch):
    calls = _patch_direct(monkeypatch, "<html>请完成验证</html>")  # 反爬壳：无列表
    monkeypatch.setattr(comm, "_crawl_render_html", lambda url: _TWO_ROW_PAGE)
    out = comm.get_community_sentiment("601208", look_back_days=5)
    assert len(calls) == 2  # page1 + page2（page1 触发渲染后继续抓 page2）
    assert "样本 1 帖" in out


def test_anti_bot_shell_without_render_returns_error(monkeypatch):
    _patch_direct(monkeypatch, "<html>请完成验证</html>")
    monkeypatch.setattr(comm, "_crawl_render_html", lambda url: None)  # 未安装/渲染失败
    out = comm.get_community_sentiment("601208")
    assert out.startswith("[股吧数据获取失败")
    assert "crawl4ai" in out


def test_direct_fetch_exception_returns_error_string(monkeypatch):
    _patch_direct(monkeypatch, __import__("requests").exceptions.ConnectionError("boom"))
    monkeypatch.setattr(comm, "_crawl_render_html", lambda url: None)
    out = comm.get_community_sentiment("601208")
    assert out.startswith("[股吧数据获取失败")


def test_empty_window_is_honest_not_error(monkeypatch):
    # 唯一一帖落在 10 天前，3 天窗口内 0 帖 → 诚实报告"冷清"而非报错
    _patch_direct(monkeypatch, _page([_row_html("1", "太老的帖子", 5, 0, _OLD_FMT)]))
    out = comm.get_community_sentiment("601208", look_back_days=3)
    assert "窗口内样本 0 帖" in out
    assert "可能讨论极冷清" in out


def test_realtime_disclaimer_for_past_date(monkeypatch):
    _patch_direct(monkeypatch, _TWO_ROW_PAGE)
    past = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    out = comm.get_community_sentiment("601208", curr_date=past)
    assert "数据时效性警告" in out


def test_bad_ticker_rejected_without_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("不应发起网络请求")

    monkeypatch.setattr(comm, "_em_get", _boom)
    monkeypatch.setattr(comm._common, "_normalize_ticker", lambda s: "12AB")
    out = comm.get_community_sentiment("12AB")
    assert "6 位数字" in out


def test_ticker_resolution_error_returns_string_not_raise(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("不应发起网络请求")

    monkeypatch.setattr(comm, "_em_get", _boom)

    def _raise(s):
        raise ValueError("invalid ticker")

    monkeypatch.setattr(comm._common, "_normalize_ticker", _raise)
    out = comm.get_community_sentiment("!!!")
    assert out.startswith("[股吧查询需要 6 位数字股票代码")


def test_window_boundary_and_cap(monkeypatch):
    rows = []
    # 70 帖都在 1 天前 → 窗口内，但 max_posts 默认 60 截断
    for i in range(70):
        rows.append(_row_html(str(i), f"帖子{i}", 1, 0, _NOW_FMT))
    _patch_direct(monkeypatch, _page(rows))
    out = comm.get_community_sentiment("601208", look_back_days=5)
    assert "样本 60 帖" in out  # max_posts 默认 60
    out2 = comm.get_community_sentiment("601208", look_back_days=5, max_posts=100)
    assert "样本 70 帖" in out2


def test_crawl4ai_render_function_available():
    """crawl4ai 已安装时渲染函数应能构造（不实际启浏览器，只验 import 路径）。"""
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        pytest.skip("crawl4ai 未安装（可选依赖 community extra）")
    assert comm._crawl_render_html.__doc__ is not None
