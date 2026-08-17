from unittest.mock import AsyncMock, MagicMock

import pytest

from app.douyin import DouyinChat, PageOperationError, _search_candidates
from app.selectors import CHAT_PANEL_MARKERS, MESSAGE_INPUTS


@pytest.mark.asyncio
async def test_search_result_accepts_visible_partial_text() -> None:
    page = MagicMock()
    rows = MagicMock()
    page.locator.return_value.filter.return_value = rows
    rows.count = AsyncMock(return_value=0)
    exact = MagicMock()
    partial = MagicMock()
    page.get_by_text.side_effect = [exact, partial]
    exact.count = AsyncMock(return_value=0)
    partial.count = AsyncMock(return_value=1)
    candidate = MagicMock()
    candidate.is_visible = AsyncMock(return_value=True)
    partial.nth.return_value = candidate

    result = await DouyinChat(page)._search_result(("好友",))

    assert result is candidate


@pytest.mark.asyncio
async def test_search_result_ignores_hidden_exact_match() -> None:
    page = MagicMock()
    rows = MagicMock()
    page.locator.return_value.filter.return_value = rows
    rows.count = AsyncMock(return_value=0)
    exact = MagicMock()
    partial = MagicMock()
    page.get_by_text.side_effect = [exact, partial]
    exact.count = AsyncMock(return_value=1)
    hidden = MagicMock()
    hidden.is_visible = AsyncMock(return_value=False)
    exact.nth.return_value = hidden
    partial.count = AsyncMock(return_value=1)
    visible = MagicMock()
    visible.is_visible = AsyncMock(return_value=True)
    partial.nth.return_value = visible

    result = await DouyinChat(page)._search_result(("好友",))

    assert result is visible


@pytest.mark.asyncio
async def test_open_target_retries_after_failed_first_attempt() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page)
    calls = {"n": 0}

    async def flaky(name: str, remark: str | None = None) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PageOperationError("首次失败")

    chat._open_target_once = flaky

    await chat.open_target("好友A", retries=1)

    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_open_target_raises_after_retries_exhausted() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page)

    async def fail(name: str, remark: str | None = None) -> None:
        raise PageOperationError("始终失败")

    chat._open_target_once = fail

    with pytest.raises(PageOperationError, match="始终失败"):
        await chat.open_target("好友A", retries=1)

    assert page.wait_for_timeout.await_count == 1


@pytest.mark.asyncio
async def test_open_target_succeeds_without_retry() -> None:
    page = MagicMock()
    chat = DouyinChat(page)

    async def ok(name: str, remark: str | None = None) -> None:
        return None

    chat._open_target_once = ok

    await chat.open_target("好友A", retries=1)

    page.wait_for_timeout.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_opened_polls_until_confirmed() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page, confirm_timeout_ms=5_000)
    results = iter([PageOperationError("未就绪"), None])

    async def checker(names, primary):
        return next(results, None)

    chat._chat_open_error = checker

    await chat._confirm_opened(("好友A",), "好友A")

    assert page.wait_for_timeout.await_count == 1


@pytest.mark.asyncio
async def test_confirm_opened_raises_on_timeout() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page, confirm_timeout_ms=100)

    async def checker(names, primary):
        return PageOperationError("一直失败")

    chat._chat_open_error = checker

    with pytest.raises(PageOperationError, match="一直失败"):
        await chat._confirm_opened(("好友A",), "好友A")


@pytest.mark.asyncio
async def test_chat_open_error_accepts_panel_marker_with_name() -> None:
    page = MagicMock()
    marker = MagicMock()
    marker.count = AsyncMock(return_value=1)
    filtered = MagicMock()
    filtered.first = marker
    chain = MagicMock()
    chain.filter = MagicMock(return_value=filtered)
    page.locator.return_value = chain

    chat = DouyinChat(page)

    assert await chat._chat_open_error(("好友A",), "好友A") is None


def _routed_page(*, name_in_body: str, input_count: int) -> MagicMock:
    page = MagicMock()
    body = MagicMock()
    body.inner_text = AsyncMock(return_value=name_in_body)
    first_target = MagicMock()
    first_target.count = AsyncMock(return_value=input_count)
    first_target.is_visible = AsyncMock(return_value=True)
    composer = MagicMock()
    composer.first = first_target
    filtered_first = MagicMock()
    filtered_first.count = AsyncMock(return_value=0)
    filtered = MagicMock()
    filtered.first = filtered_first
    chain = MagicMock()
    chain.filter = MagicMock(return_value=filtered)
    get_by_text = MagicMock()
    get_by_text.count = AsyncMock(return_value=0)
    page.get_by_text.return_value = get_by_text

    def locator_router(selector: str):
        if selector == "body":
            return body
        if selector in MESSAGE_INPUTS:
            return composer
        return chain

    page.locator.side_effect = locator_router
    return page


@pytest.mark.asyncio
async def test_chat_open_error_accepts_composer_and_page_name() -> None:
    assert CHAT_PANEL_MARKERS
    page = _routed_page(name_in_body="页面内容 好友A 你好", input_count=1)

    chat = DouyinChat(page)

    assert await chat._chat_open_error(("好友A",), "好友A") is None


@pytest.mark.asyncio
async def test_chat_open_error_rejects_when_name_absent() -> None:
    page = _routed_page(name_in_body="页面没有目标好友", input_count=0)

    chat = DouyinChat(page)

    error = await chat._chat_open_error(("好友A",), "好友A")

    assert isinstance(error, PageOperationError)
    assert "无法确认聊天已打开" in str(error)


def test_search_candidates_prefers_remark() -> None:
    assert _search_candidates("昵称", "备注") == ("备注", "昵称")


def test_search_candidates_drops_remark_equal_to_name() -> None:
    assert _search_candidates("好友A", "好友A") == ("好友A",)


def test_search_candidates_without_remark() -> None:
    assert _search_candidates("好友A", None) == ("好友A",)


@pytest.mark.asyncio
async def test_open_target_uses_remark_for_search() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    search = MagicMock()
    search.count = AsyncMock(return_value=1)
    search.is_visible = AsyncMock(return_value=True)
    search.click = AsyncMock()
    search.fill = AsyncMock()

    result_button = MagicMock()
    result_button.click = AsyncMock()

    chat = DouyinChat(page)
    chat._search_result = AsyncMock(return_value=result_button)
    chat._confirm_opened = AsyncMock()

    captured: dict[str, object] = {}

    async def fake_first_visible(_page, selectors, timeout_ms):  # noqa: ANN001
        captured["selectors"] = selectors
        captured["timeout_ms"] = timeout_ms
        return search

    import app.douyin as douyin_module

    original = douyin_module.first_visible
    douyin_module.first_visible = fake_first_visible
    try:
        await chat._open_target_once("昵称", "备注")
    finally:
        douyin_module.first_visible = original

    # 备注优先填入搜索框
    assert search.fill.await_args_list[-1].args == ("备注",)
    chat._search_result.assert_awaited_once_with(("备注", "昵称"))
    chat._confirm_opened.assert_awaited_once()
    assert chat._confirm_opened.await_args.args[0] == ("备注", "昵称")
    assert chat._confirm_opened.await_args.args[1] == "昵称"
