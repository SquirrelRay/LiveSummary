"""模型回傳壞掉的 JSON 時，解析函式的行為。全部用假字串，不呼叫 API、不連網。

兩個解析函式的約定：
- live_topics.取最後JSON：讀不出來 → 丟出 ValueError("讀不出 JSON")（明確的中文錯誤訊息，屬於 b 類）
- subtitle.讀譯文：讀不出來 → 回傳 None（不丟例外，屬於 a 類）
"""
import pytest

import live_topics
import subtitle

壞回答們 = {
    "空字串": "",
    "只有空白": "   \n ",
    "截斷": '{"decision": "same", "topic": "打王',
    "純說明文字": "抱歉，我無法判斷。",
}


# ---- b 類：丟出明確中文錯誤訊息 ----
@pytest.mark.parametrize("名稱", list(壞回答們))
def test_取最後JSON_壞資料_丟出中文錯誤(名稱):
    with pytest.raises(ValueError, match="讀不出 JSON"):
        live_topics.取最後JSON(壞回答們[名稱])


# ---- a 類（回傳可處理結果）：夾雜多餘文字仍能讀出 ----
def test_取最後JSON_夾雜多餘文字_取出正確物件():
    回答 = '好的，分析如下：\n```json\n{"decision": "new", "topic": "打王"}\n```\n以上。'
    assert live_topics.取最後JSON(回答) == {"decision": "new", "topic": "打王"}


def test_取最後JSON_有多個物件_優先取有decision的最後一個():
    回答 = '{"decision": "same"} 補充 {"note": 1}'
    assert live_topics.取最後JSON(回答) == {"decision": "same"}


# ---- 逐句翻譯（日文翻譯 JSONDecodeError 相關）：壞資料回傳 None，不丟例外 ----
@pytest.mark.parametrize("名稱", ["空字串", "只有空白", "截斷", "純說明文字"])
def test_讀譯文_壞資料_回傳None不丟例外(名稱):
    assert subtitle.讀譯文(壞回答們[名稱]) is None


def test_讀譯文_截斷的陣列_回傳None():
    assert subtitle.讀譯文('["第一句譯文", "第二句譯') is None


def test_讀譯文_夾雜多餘文字_取最後一個陣列():
    回答 = '以下是翻譯：\n["草稿"]\n正式版：\n```json\n["你好", "再見"]\n```'
    assert subtitle.讀譯文(回答) == ["你好", "再見"]
