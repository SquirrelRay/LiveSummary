"""安全網測試：「絕不覆蓋舊檔」的命名邏輯——live_topics.結果檔名、subtitle.字幕器._寫存檔。檔案一律寫在 tmp_path。"""
import re
from pathlib import Path

import live_topics as lt
import subtitle

時間後綴 = r"_\d{8}-\d{4}"


# ---------- 結果檔名 ----------
def test_沒有舊檔就用原名(tmp_path):
    基底 = str(tmp_path / "直播")
    assert lt.結果檔名(基底, True) == (基底 + "_話題摘要.md", 基底 + "_分鐘摘要.md")
    assert lt.結果檔名(基底, False) == (基底 + "_話題摘要.md", None)


def test_舊話題摘要存在就換加了時間的新名字且不覆蓋(tmp_path):
    基底 = str(tmp_path / "直播")
    (tmp_path / "直播_話題摘要.md").write_text("舊內容", encoding="utf-8")
    話題, 分鐘 = lt.結果檔名(基底, True)
    assert re.fullmatch(re.escape(基底) + "_話題摘要" + 時間後綴 + r"\.md", 話題)
    assert re.fullmatch(re.escape(基底) + "_分鐘摘要" + 時間後綴 + r"\.md", 分鐘)    # 兩個檔用同一個後綴
    assert (tmp_path / "直播_話題摘要.md").read_text(encoding="utf-8") == "舊內容"


def test_只有舊分鐘摘要存在也要換名字(tmp_path):
    基底 = str(tmp_path / "直播")
    (tmp_path / "直播_分鐘摘要.md").write_text("舊", encoding="utf-8")
    話題, 分鐘 = lt.結果檔名(基底, True)
    assert re.search(時間後綴, 話題) and re.search(時間後綴, 分鐘)


def test_不要分鐘時舊分鐘檔不影響(tmp_path):
    基底 = str(tmp_path / "直播")
    (tmp_path / "直播_分鐘摘要.md").write_text("舊", encoding="utf-8")
    assert lt.結果檔名(基底, False) == (基底 + "_話題摘要.md", None)


def test_同一分鐘內再撞名就加序號(tmp_path):
    基底 = str(tmp_path / "直播")
    (tmp_path / "直播_話題摘要.md").write_text("舊", encoding="utf-8")
    第一, _ = lt.結果檔名(基底, False)
    Path(第一).touch()
    第二, _ = lt.結果檔名(基底, False)
    assert 第二 != 第一 and not Path(第二).exists()
    assert re.search(時間後綴 + r"(_2)?\.md$", 第二)


# ---------- 字幕器._寫存檔 ----------
def 新字幕器(基底):
    s = subtitle.字幕器()
    s.存檔基底 = str(基底) if 基底 else None
    return s


def test_第一句才建立檔案且內容格式正確(tmp_path):
    s = 新字幕器(tmp_path / "稿")
    assert not list(tmp_path.iterdir())
    路徑 = s._寫存檔("00:01", "こんにちは", "你好")
    assert 路徑 == str(tmp_path / "稿_逐句翻譯.txt")
    assert (tmp_path / "稿_逐句翻譯.txt").read_text(encoding="utf-8") == "[00:01] こんにちは\n　　→ 你好\n"


def test_後續句子接在同一個檔案後面(tmp_path):
    s = 新字幕器(tmp_path / "稿")
    s._寫存檔("00:01", "一", "甲")
    s._寫存檔("00:02", "二", "乙")
    內容 = (tmp_path / "稿_逐句翻譯.txt").read_text(encoding="utf-8")
    assert 內容 == "[00:01] 一\n　　→ 甲\n[00:02] 二\n　　→ 乙\n"


def test_沒翻到的句子標未翻譯(tmp_path):
    s = 新字幕器(tmp_path / "稿")
    s._寫存檔("00:01", "原文", "")
    assert "　　→ 【未翻譯】" in (tmp_path / "稿_逐句翻譯.txt").read_text(encoding="utf-8")


def test_舊檔已存在就改用新檔名不覆蓋(tmp_path):
    舊 = tmp_path / "稿_逐句翻譯.txt"
    舊.write_text("舊內容\n", encoding="utf-8")
    s = 新字幕器(tmp_path / "稿")
    路徑 = s._寫存檔("00:01", "新", "新譯")
    assert 舊.read_text(encoding="utf-8") == "舊內容\n"
    assert re.fullmatch(re.escape(str(tmp_path / "稿_逐句翻譯")) + 時間後綴 + r"\.txt", 路徑)
    assert "新譯" in Path(路徑).read_text(encoding="utf-8")


def test_新舊檔都存在時再加序號(tmp_path):
    (tmp_path / "稿_逐句翻譯.txt").write_text("舊1", encoding="utf-8")
    第一 = 新字幕器(tmp_path / "稿")
    路徑一 = 第一._寫存檔("00:01", "a", "b")        # 產生「加時間」的檔
    第二 = 新字幕器(tmp_path / "稿")
    路徑二 = 第二._寫存檔("00:01", "c", "d")
    assert 路徑二 != 路徑一
    assert (tmp_path / "稿_逐句翻譯.txt").read_text(encoding="utf-8") == "舊1"
    assert "b" in Path(路徑一).read_text(encoding="utf-8") and "d" in Path(路徑二).read_text(encoding="utf-8")


def test_沒有存檔基底就不寫(tmp_path):
    s = 新字幕器(None)
    assert s._寫存檔("00:01", "a", "b") is None
    assert not list(tmp_path.iterdir())
