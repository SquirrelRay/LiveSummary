# 版本號：整個專案只寫在這一個地方（改版本只改下面的 版本）。
# 其他地方都從這裡讀：設定框底部的版本字、當機紀錄、exe 的檔案內容（右鍵 → 內容 → 詳細資料）、zip 檔名（LiveSummary-v1.0.0.zip）。
# 只用標準函式庫（build 腳本、spec、LiveSummary.spec 產生 exe 版本資源時也會 import 它）。
版本 = "1.0.0"

產品名 = "直播摘要"
英文名 = "LiveSummary"
授權 = "GPL-3.0"
GitHub倉庫 = "SquirrelRay/LiveSummary"                       # 檢查更新查這個專案的最新發布版
專案網址 = f"https://github.com/{GitHub倉庫}"                 # 設定框「關於」的星星按鈕
發布頁網址 = f"{專案網址}/releases"                           # 查不到下載連結時退回這裡
贊助網址 = "https://ko-fi.com/squirrelray"                    # 設定框「關於」的咖啡按鈕
回報表單網址 = "https://forms.gle/CQpC5R4uDdQVb6mY6"           # 設定框「關於」的回報問題按鈕（Google 表單，不用登入）
著作權人 = "SquirrelRay"          # LICENSE-ADDITIONAL-PERMISSION.txt、exe 檔案內容的版權欄位（改這裡時兩處一起改）


def 版本們():
    """'1.0.0' → (1, 0, 0, 0)；exe 版本資源要四段整數。"""
    段 = [int(x) for x in 版本.split(".")]
    return tuple((段 + [0, 0, 0, 0])[:4])


def 版本字():
    """給人看的：v1.0.0。"""
    return f"v{版本}"


def 壓縮檔名():
    return f"{英文名}-{版本字()}.zip"


def 檔案資訊(原檔名, 說明=None):
    """exe 檔案內容（詳細資料頁）的欄位。原檔名：這個 exe 的檔名。"""
    return {
        "CompanyName": "",
        "FileDescription": 說明 or 產品名,
        "FileVersion": 版本,
        "InternalName": 原檔名.rsplit(".", 1)[0],
        "LegalCopyright": f"Copyright (C) 2026 {著作權人}，{授權} 開放原始碼",
        "OriginalFilename": 原檔名,
        "ProductName": 產品名,
        "ProductVersion": 版本,
    }
