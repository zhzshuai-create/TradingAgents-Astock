"""巨潮公告层回归测试：列表解析 / 北京时间口径 / 日期过滤 / PDF 全文降级与护栏."""

import pytest
import requests

from tradingagents.dataflows.a_stock import announcements as ann


# ---------------------------------------------------------------------------
# 夹具：2026-10-06 对 601208 实测的巨潮响应形状（字段名逐一核对过）
# ---------------------------------------------------------------------------

def _item(anno_id, title, ts, adjunct="finalpage/2026-10-01/1225589737.PDF", size_kb=120, typ="PDF"):
    return {
        "announcementId": anno_id,
        "announcementTitle": title,
        "announcementTime": ts,
        "adjunctUrl": adjunct,
        "adjunctSize": size_kb,
        "adjunctType": typ,
        "announcementTypeName": "其他公告",
    }


_TOPSEARCH_601208 = [{"code": "601208", "orgId": "9900019705", "type": "shj"}]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _patch_post(monkeypatch, query_payload, topsearch_payload=None):
    """按 URL 分流：topSearch 返回 orgId 查询结果，hisAnnouncement 返回公告列表。"""
    top = topsearch_payload if topsearch_payload is not None else _TOPSEARCH_601208

    def fake_post(url, *args, **kwargs):
        if "topSearch" in url:
            return _FakeResponse(top)
        return _FakeResponse(query_payload)

    monkeypatch.setattr(ann._requests, "post", fake_post)


_TWO_ROWS = [
    _item("111", "2026年半年度业绩说明会召开情况的公告", 1790784000000),  # 2026-10-01 00:00 +08
    _item("222", "2026年半年度权益分派实施公告", 1790006400000),  # 2026-09-22 00:00 +08
]


# ---------------------------------------------------------------------------
# 时间戳 → 日期（北京时间口径，CI UTC 容器也不许差一天）
# ---------------------------------------------------------------------------

def test_cninfo_ts_to_date_is_beijing_time():
    # 1790784000000 = 2026-09-30T16:00Z = 北京时间 2026-10-01 00:00
    assert ann._cninfo_ts_to_date(1790784000000) == "2026-10-01"


def test_cninfo_ts_to_date_garbage():
    assert ann._cninfo_ts_to_date(None) == ""
    assert ann._cninfo_ts_to_date("not-a-number") == ""


def test_normalize_date_lenient():
    assert ann._normalize_date("2026-10-06") == "2026-10-06"
    assert ann._normalize_date("截至2026-10-06收盘") == "2026-10-06"
    assert ann._normalize_date("2026/10/06") == ""  # 非标准格式视为不过滤
    assert ann._normalize_date("") == ""
    assert ann._normalize_date("2026-13-99") == ""


# ---------------------------------------------------------------------------
# 列表解析与降级路径
# ---------------------------------------------------------------------------

def test_bad_ticker_rejected_without_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("不应发起网络请求")

    monkeypatch.setattr(ann._requests, "post", _boom)
    # 中文名（贵州茅台）会被 resolve_ticker 正常解析，属平台既定能力；
    # 这里验证解析结果非 6 位数字时干净拒绝
    monkeypatch.setattr(ann._common, "_normalize_ticker", lambda s: "12AB")
    out = ann.get_announcements("12AB")
    assert "6 位数字" in out


def test_ticker_resolution_error_returns_string_not_raise(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("不应发起网络请求")

    monkeypatch.setattr(ann._requests, "post", _boom)

    def _raise(s):
        raise ValueError("invalid ticker")

    monkeypatch.setattr(ann._common, "_normalize_ticker", _raise)
    out = ann.get_announcements("!!!")
    assert out.startswith("[公告查询需要 6 位数字股票代码")


def test_fetch_failure_returns_error_string_not_raise(monkeypatch):
    def fake_post(*a, **k):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(ann._requests, "post", fake_post)
    out = ann.get_announcements("601208")
    assert out.startswith("[公告数据获取失败")
    assert "boom" in out


def test_orgid_not_found_reports_empty(monkeypatch):
    _patch_post(
        monkeypatch,
        {"totalRecordNum": 0, "announcements": []},
        topsearch_payload=[{"code": "000001", "orgId": "x"}],
    )
    out = ann.get_announcements("601208")
    assert "未查询到公告" in out


def test_list_parse_and_table(monkeypatch):
    _patch_post(monkeypatch, {"totalRecordNum": 2, "announcements": _TWO_ROWS})
    out = ann.get_announcements("601208", with_content=False)
    assert "## 公司公告（601208）" in out
    assert "巨潮资讯网 (cninfo.com.cn)" in out  # 来源可引用
    assert "2026-10-01" in out and "2026-09-22" in out
    assert "业绩说明会召开情况" in out
    assert "全文摘录" not in out


def test_date_filter_inclusive(monkeypatch):
    _patch_post(monkeypatch, {"totalRecordNum": 2, "announcements": _TWO_ROWS})
    out = ann.get_announcements("601208", start_date="2026-09-22", end_date="2026-09-30", with_content=False)
    assert "权益分派" in out
    assert "业绩说明会" not in out  # 10-01 在区间外
    assert "命中 1 条" in out


# ---------------------------------------------------------------------------
# PDF 全文护栏（markitdown 存在与否都必须行为一致 → 显式打桩引擎探测）
# ---------------------------------------------------------------------------

def test_fulltext_success_with_truncation(monkeypatch, tmp_path):
    _patch_post(monkeypatch, {"totalRecordNum": 1, "announcements": _TWO_ROWS[:1]})
    monkeypatch.setattr(ann, "_get_markitdown", lambda: object())  # 模拟已安装
    monkeypatch.setattr(ann, "_download_pdf", lambda url, anno_id: str(tmp_path / f"{anno_id}.pdf"))
    long_text = "董事会公告内容。" * 30  # 240 字
    monkeypatch.setattr(ann, "_convert_pdf_to_markdown", lambda path: long_text)

    out = ann.get_announcements("601208", max_chars_per_doc=100)
    assert "## 公告全文摘录" in out
    assert "finalpage/2026-10-01/1225589737.PDF" in out  # PDF 直链可溯源
    assert "[已截断: 原文 240 字]" in out
    assert "董事会公告内容。" in out


def test_fulltext_scan_pdf_placeholder(monkeypatch, tmp_path):
    _patch_post(monkeypatch, {"totalRecordNum": 1, "announcements": _TWO_ROWS[:1]})
    monkeypatch.setattr(ann, "_get_markitdown", lambda: object())
    monkeypatch.setattr(ann, "_download_pdf", lambda url, anno_id: str(tmp_path / "x.pdf"))
    monkeypatch.setattr(ann, "_convert_pdf_to_markdown", lambda path: "  ")
    out = ann.get_announcements("601208")
    assert "疑似扫描件或无文本层" in out


def test_fulltext_per_doc_failure_isolated(monkeypatch, tmp_path):
    _patch_post(monkeypatch, {"totalRecordNum": 2, "announcements": _TWO_ROWS})

    monkeypatch.setattr(ann, "_get_markitdown", lambda: object())

    def fake_convert(path):
        if "222" in path:
            raise RuntimeError("corrupted pdf")
        return "第一份公告全文，内容充分。" * 10

    monkeypatch.setattr(ann, "_download_pdf", lambda url, anno_id: str(tmp_path / f"{anno_id}.pdf"))
    monkeypatch.setattr(ann, "_convert_pdf_to_markdown", fake_convert)

    out = ann.get_announcements("601208")
    assert "[公告全文提取失败: corrupted pdf]" in out  # 第一份失败
    assert "第一份公告全文" in out  # 第二份照常成功


def test_fulltext_non_pdf_adjunct(monkeypatch):
    doc_row = _item("333", "某文档公告", 1790784000000, typ="DOC")
    _patch_post(monkeypatch, {"totalRecordNum": 1, "announcements": [doc_row]})
    monkeypatch.setattr(ann, "_get_markitdown", lambda: object())
    out = ann.get_announcements("601208")
    assert "非 PDF 附件(DOC)" in out


def test_fulltext_download_failure_placeholder(monkeypatch):
    _patch_post(monkeypatch, {"totalRecordNum": 1, "announcements": _TWO_ROWS[:1]})
    monkeypatch.setattr(ann, "_get_markitdown", lambda: object())
    monkeypatch.setattr(ann, "_download_pdf", lambda url, anno_id: None)
    out = ann.get_announcements("601208")
    assert "[公告 PDF 下载失败或超过体积上限]" in out


def test_degrade_when_markitdown_missing(monkeypatch):
    _patch_post(monkeypatch, {"totalRecordNum": 2, "announcements": _TWO_ROWS})
    monkeypatch.setattr(ann, "_get_markitdown", lambda: None)
    out = ann.get_announcements("601208", with_content=True)
    assert "| # | 日期 | 类型 | 标题 |" in out  # 列表仍在
    assert "未安装 markitdown" in out
    assert "pip install 'markitdown[pdf]'" in out
    assert "## 公告全文摘录" not in out  # 不再逐份尝试转换


# ---------------------------------------------------------------------------
# 真实 markitdown 转换（离线：用最小 PDF 字节流验证引擎路径可达）
# ---------------------------------------------------------------------------

def test_convert_engine_on_garbage_never_yields_long_text(tmp_path):
    """真实 markitdown 引擎路径可达；坏 PDF 抛异常或返回短文本都安全
    （get_announcements 对两者都有 per-doc 捕获/扫描件占位）。"""
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 broken")
    if ann._get_markitdown() is None:
        pytest.skip("markitdown 未安装（可选依赖 announcements extra）")
    try:
        text = ann._convert_pdf_to_markdown(str(bad))
    except Exception:
        return  # 抛异常路径：由 get_announcements 捕获为占位符
    assert isinstance(text, str)
    assert len(text.strip()) < ann._MIN_PDF_TEXT_CHARS  # 短文本会落入扫描件占位
