# Twitch 聊天室擷取（匿名連線，不需要任何登入或金鑰）
# 用 Twitch IRC：irc.chat.twitch.tv，帳號用 justinfanXXXXX 這種匿名名稱
import os
import re
import ssl
import time
import socket
import random
import threading

import transcribe  # 沿用 [mm:ss] 的時間格式
import events      # 每則留言送出 chat_line 事件

機器人 = {"nightbot", "moobot", "streamelements", "streamlabs", "fossabot", "wizebot", "sery_bot", "soundalerts",
       "commanderroot", "anotherttvviewer", "streamstickers", "pretzelrocks", "lurxx"}
重試次數 = 3

私訊 = re.compile(r"^:(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :(.*)$")


def 是機器人(名稱):
    名稱 = 名稱.lower()
    return 名稱.endswith("bot") or 名稱 in 機器人


def 是洗版(內容):
    字們 = 內容.split()
    if len(字們) >= 3 and len(set(字們)) == 1:     # 同一個字／表情重複好幾次
        return True
    return not any(c.isalnum() for c in 內容)       # 只有表情符號或符號


class 聊天室:
    def __init__(self, 頻道, 存檔路徑):
        self.頻道 = 頻道.lower()
        self.存檔路徑 = 存檔路徑
        self.訊息們 = []        # 通過過濾的留言：(秒, 使用者, 內容)
        self.收到 = 0
        self.過濾 = 0
        self.連線中 = False      # 有沒有真的連上
        self._鎖 = threading.Lock()
        self._停 = threading.Event()
        self._起點 = None

    def 開始(self, 起點):
        """起點：和直播稿同一個起算時間（time.time() 的值）。"""
        self._起點 = 起點
        threading.Thread(target=self._跑, daemon=True).start()

    def 關閉(self):
        self._停.set()

    def 取出(self, 開始秒, 結束秒):
        with self._鎖:
            return [m for m in self.訊息們 if 開始秒 < m[0] <= 結束秒]

    def _跑(self):
        失敗 = 0
        with open(self.存檔路徑 or os.devnull, "w", encoding="utf-8") as 檔:      # 存檔路徑 None = 不存聊天室
            while not self._停.is_set():
                try:
                    self._連線並讀取(檔)
                    失敗 = 0 if self.連線中 else 失敗   # 連上過就重新計算
                except Exception:
                    pass
                self.連線中 = False
                if self._停.is_set():
                    return
                失敗 += 1
                if 失敗 > 重試次數:
                    events.送出("info", 印出="\n警告：聊天室連不上（已重試 3 次），之後只用語音稿運作。")
                    return
                time.sleep(2)

    def _連線並讀取(self, 檔):
        原始 = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=10)
        s = ssl.create_default_context().wrap_socket(原始, server_hostname="irc.chat.twitch.tv")
        s.settimeout(1)
        try:
            s.sendall(f"PASS SCHMOOPIIE\r\nNICK justinfan{random.randint(10000, 99999)}\r\n"
                      f"JOIN #{self.頻道}\r\n".encode())
            緩衝 = ""
            while not self._停.is_set():
                try:
                    資料 = s.recv(4096)
                except socket.timeout:
                    continue
                if not 資料:
                    return          # 對方斷線，交給外面重連
                self.連線中 = True
                緩衝 += 資料.decode("utf-8", errors="replace")
                *行們, 緩衝 = 緩衝.split("\r\n")
                for 行 in 行們:
                    if 行.startswith("PING"):
                        s.sendall(("PONG" + 行[4:] + "\r\n").encode())
                        continue
                    m = 私訊.match(行)
                    if m:
                        self._處理(m.group(1), m.group(2), 檔)
        finally:
            s.close()

    def _處理(self, 使用者, 內容, 檔):
        self.收到 += 1
        if 是機器人(使用者) or 內容.startswith("!") or 是洗版(內容):
            self.過濾 += 1
            return
        秒 = time.time() - self._起點
        with self._鎖:
            self.訊息們.append((秒, 使用者, 內容))
        檔.write(f"{transcribe.時間(秒)} {使用者}: {內容}\n")
        檔.flush()
        events.送出("chat_line", 秒=秒, 時間字=transcribe.時間(秒).strip("[]"), 使用者=使用者, 內容=內容,
                    編號=events.新留言編號())
