"""網址欄的全形字（打包第 5 步之一）：注音等輸入法會把「_」打成全形「＿」，「/」「:」「.」也可能變全形。
解析網址前先把全形英數字和符號轉半形、去掉前後空白（含全形空白）；其他字（中文、日文、半形片假名）原樣保留。"""
import names_page
import platforms


def test_全形底線變半形():
    assert platforms.整理網址("https://www.twitch.tv/ren＿kisaragi＿＿") == "https://www.twitch.tv/ren_kisaragi__"


def test_全形英數字和網址符號變半形():
    assert platforms.整理網址("ｈｔｔｐｓ：／／ｗｗｗ．ｔｗｉｔｃｈ．ｔｖ／Ｒｅｎ＿０１") == "https://www.twitch.tv/Ren_01"


def test_其他全形符號():
    assert platforms.整理網址("https://www.youtube.com/watch？ｖ＝abc－DEF＿12") == "https://www.youtube.com/watch?v=abc-DEF_12"
    assert platforms.整理網址("＠handle～") == "@handle~"
    assert platforms.整理網址("https://youtu.be/abc。") == "https://youtu.be/abc."


def test_去掉前後空白含全形空白和看不見的字():
    assert platforms.整理網址("  https://www.twitch.tv/abc \n") == "https://www.twitch.tv/abc"
    assert platforms.整理網址("　https://www.twitch.tv/abc　") == "https://www.twitch.tv/abc"
    assert platforms.整理網址("\ufeffhttps://www.twitch.tv/a\u200bbc") == "https://www.twitch.tv/abc"


def test_半形網址原樣不動():
    for 網址 in ("https://www.twitch.tv/ren_kisaragi__", "https://www.youtube.com/@ひらがな/live", "twitch.tv/abc"):
        assert platforms.整理網址(網址) == 網址


def test_中文和日文字不被改():
    assert platforms.整理網址("https://www.youtube.com/@日本語チャンネル/live") == "https://www.youtube.com/@日本語チャンネル/live"
    assert platforms.整理網址("ｱｲｳ") == "ｱｲｳ"           # 半形片假名不是全形英數字，保留


def test_空值():
    assert platforms.整理網址(None) == "" and platforms.整理網址("") == "" and platforms.整理網址("　") == ""


def test_判斷認得全形底線的Twitch頻道名():
    資 = platforms.判斷("https://www.twitch.tv/ren＿kisaragi＿＿")
    assert 資.支援 and 資.平台 == platforms.TWITCH and 資.頻道 == "ren_kisaragi__"


def test_判斷認得整串全形的網址():
    資 = platforms.判斷("　ｈｔｔｐｓ：／／ｗｗｗ．ｔｗｉｔｃｈ．ｔｖ／ｔｅｓｔ＿ｕｓｅｒ＿９　")
    assert 資.支援 and 資.頻道 == "test_user_9"


def test_判斷認得全形的YouTube網址():
    資 = platforms.判斷("https://www.youtube.com/watch？ｖ＝dQw4w9WgXcQ")
    assert 資.支援 and 資.平台 == platforms.YOUTUBE and 資.影片 == "dQw4w9WgXcQ"


def test_名詞清單的頻道辨識也吃全形底線():
    名, 原因 = names_page.頻道("https://www.twitch.tv/ren＿kisaragi＿＿")
    assert 名 == "ren_kisaragi__" and not 原因
