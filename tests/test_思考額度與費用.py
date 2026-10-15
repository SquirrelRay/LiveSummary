"""回覆上限 8000（延伸思考也佔這個額度）；每小時費用估算有把延伸思考的 token 算進去。不呼叫 API。"""
import pytest

import config
import cost_estimate as ce
import llm


def test_摘要類與查證的回覆上限是8000_翻譯類維持原樣():
    assert llm.MAX_TOKENS == 8000 and llm.查證_MAX_TOKENS == 8000
    assert llm._最多token("摘要") == 8000
    assert (llm.翻譯_MAX_TOKENS, llm.聊天翻譯_MAX_TOKENS) == (600, 1500)      # 這兩類關掉思考，不需要放寬


def 設定(思考, **k):
    return dict(config.出廠預設(), summary_thinking=思考, **k)


def test_出廠預設思考是開的_估算用思考開的算法():
    assert config.出廠預設()["summary_thinking"] is True
    開 = ce.估算(設定(True), "balanced", False)["合計"]
    關 = ce.估算(設定(False), "balanced", False)["合計"]
    assert 開 > 關 * 2                                  # 思考開：輸出變 3.7 倍，摘要類費用明顯變多


@pytest.mark.parametrize("鍵", ["判斷", "分鐘", "話題"])
def test_思考的輸出_token倍數進了摘要用量(鍵):
    開 = ce.摘要用量(設定(True), 60)[鍵]
    關 = ce.摘要用量(設定(False), 60)[鍵]
    assert 開[0] == 關[0]                                                 # 輸入不變
    assert 開[1] == pytest.approx(關[1] * ce.思考輸出倍數)                    # 輸出多出思考


def test_翻譯與聊天翻譯不受思考影響_因為關閉思考():
    開 = {x["鍵"]: x["每小時"] for x in ce.估算(設定(True, language="ja", chat_translate=True), "balanced", True, True)["項目們"]}
    關 = {x["鍵"]: x["每小時"] for x in ce.估算(設定(False, language="ja", chat_translate=True), "balanced", True, True)["項目們"]}
    assert 開["翻譯"] == 關["翻譯"] and 開["聊天"] == 關["聊天"]
