直播重點摘要（階段 1）

第一次設定：
1. 安裝套件：pip install anthropic
2. 設定金鑰（只做一次，PowerShell）：
   setx ANTHROPIC_API_KEY "你的金鑰"
   設完後「關掉再重開」終端機才會生效。

使用：
   python summarize.py sample.txt --type game
   python summarize.py 文字稿.txt --type chat

結果會印在畫面上，並存成「原檔名_摘要.md」。

設定檔 config.json（用 live_topics.py 時）：
  功能開關和常用數字都寫在 config.json，用記事本打開改就好，改完存檔，下次執行就生效。
  命令列參數只是「這一次」臨時覆蓋，優先順序：命令列 > config.json > 程式內建預設。
  欄位：chat（聊天室）、minute_summary（分鐘摘要）、save_audio（存音訊）、fix_with_chat（聊天室參考詞修正）、
        check_minutes、min_topic_min、max_topic_min、model、whisper_model、language、minute_sentences（1 到 3）。
  看目前實際生效的設定與來源：  python live_topics.py --show-config
  臨時覆蓋範例：  --no-chat / --chat、--no-minute / --minute、--no-save-audio / --save-audio、--fix / --no-fix
  注意：API 金鑰不要寫進 config.json，只放在環境變數（預設 ANTHROPIC_API_KEY，可用 api_key_env 改名字）。
  金鑰無效時，程式會用一句中文停下來，不會繼續空跑。

外語直播（日文等）：
  config.json 的 language 可填 "zh"（預設，中文）、"ja"（日文）、"en"（英文）、"ko"（韓文）、"auto"（自動偵測）。
  命令列臨時覆蓋：  python live_topics.py --live 網址 --lang ja     或   --lang auto
  auto：開頭累積約 1 分鐘有人聲的音訊判斷語言，判斷出來就鎖定，之後都用這個語言；失敗會印警告並退回中文。
  不管直播什麼語言，摘要一律是繁體中文；專有名詞第一次出現會附原文，看不懂的詞會標「不確定」。
  轉錄外語影片：  python transcribe.py 影片或網址 --lang ja
  文字稿模式跑外語稿：  python live_topics.py 日文稿.txt --lang ja
  --show-config 會顯示 language 目前的值與來源。

切換語言模型（live_topics.py；config.json 改這幾欄）：
  provider     ："anthropic"（預設，Claude）或 "openai_compatible"（OpenAI、DeepSeek、Ollama 等）
  base_url     ：服務網址，空白 = 該家預設
  api_key_env  ：金鑰放在哪個「環境變數名稱」（不是金鑰本身！）；留空 = 不需要金鑰（Ollama）
  model        ：模型名稱
  price_input / price_output：每百萬 token 的美元單價，只用來估算費用（單價未查證，請自行到官網確認）
  呼叫模型的程式都在 llm.py。summarize.py 單獨使用時仍固定用 Claude。
  用 openai_compatible 前要先裝套件：pip install openai
  金鑰無效、或連不上伺服器（例如 Ollama 沒開）時，程式會用一句中文說明並停止。
  拿不到 token 數的服務，結束時會顯示「無法計算」。

  範例（2026-10-10 查官方文件；模型名稱常會更新，用之前請再到官網確認）：
  OpenAI：（金鑰先 setx OPENAI_API_KEY "你的金鑰"）
    "provider": "openai_compatible", "base_url": "https://api.openai.com/v1",
    "api_key_env": "OPENAI_API_KEY", "model": "gpt-6-luna"
    （base_url 是從官方範例網址推得的；gpt-6-luna 是官方列的小型便宜款，大型款 gpt-6-astra）
  DeepSeek：（金鑰先 setx DEEPSEEK_API_KEY "你的金鑰"）
    "provider": "openai_compatible", "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY", "model": "deepseek-flash"
    （另有 deepseek-v4-pro）
  Ollama（本機，不用金鑰，先開 Ollama 並下載模型）：
    "provider": "openai_compatible", "base_url": "http://localhost:11434/v1",
    "api_key_env": "", "model": "gpt-oss:20b", "price_input": 0, "price_output": 0
    （model 換成你自己用 ollama pull 下載的模型名稱）
  換回 Claude：
    "provider": "anthropic", "base_url": "", "api_key_env": "ANTHROPIC_API_KEY", "model": "claude-haiku-5-5"

字幕框（介面 app.py 才有，命令列不受影響）：
  兩個獨立的小視窗：
    摘要框：預設在螢幕上緣，顯示分鐘摘要、目前話題、支線、觀眾反應（各自可在設定頁開關）。
    字幕框：預設在螢幕下緣，大字置中顯示最近 1 到 2 句逐句字幕；翻譯模式時右上角有小小的「翻譯」標籤。
  兩個框的高度會跟著內容自動變高變矮。
  快捷鍵（設定頁可改）：
    Ctrl+Shift+S 同時開關兩個框　Ctrl+Shift+A 只開關摘要框　Ctrl+Shift+D 只開關字幕框
    Ctrl+Shift+X 切換滑鼠穿透（兩個框一起）。穿透「開」= 點擊穿過字幕；「關」= 可拖曳移動、拖左右邊緣改寬度。
  拖過的框會變成「自由位置」，位置與寬度記在 overlay_位置.json，下次開啟還在原處。
  快捷鍵被別的程式佔用時，主控台會用中文提示，到設定頁換個按鍵即可。

設定頁（主控台的「設定」分頁）：
  可調兩個框的字型、字級、顏色、背景、透明度、文字效果、淡出秒數、位置、螢幕、寬度，
  以及字幕模式、聊天室、分鐘摘要、存音訊、參考詞修正、分鐘摘要句數、翻譯批次、快捷鍵、模型服務與模型名稱。
  調整樣式時字幕框會即時預覽；按「儲存」才寫回 config.json，寫之前自動備份成 config.backup.json。
  「還原預設值」會把表單和字幕框變回預設（一樣要按「儲存」才寫入）。金鑰只顯示「已設定／未設定」。
  執行中改到的功能、模型等項目會標「下次開始生效」。
  config.json 的 overlay 區塊：共用的 click_through、hotkey_toggle、hotkey_summary、hotkey_subtitle、
  hotkey_click_through，加上 summary_box（摘要框）與 subtitle_box（字幕框）兩組樣式。
  舊版只有一個框的 overlay 設定，打開 app.py 時會自動轉成兩個框（原本的備份在 config.backup.json）。

逐句翻譯（字幕模式 subtitle_mode："original" 原文、"translate" 一律翻譯、"auto" 中文原文其他語言翻譯）：
  語言選「自動偵測」時，偵測到外語後字幕會自動切成翻譯。
  翻譯呼叫已關閉延伸思考並限制輸出長度，費用約為原本的 1/6。
  批次：translate_batch_seconds（預設 8 秒）、translate_batch_lines（預設 4 句），可在 config.json 或設定頁調。
  翻譯另外計費，主控台「翻譯」藥丸與結束訊息會分開顯示次數與費用。

按「停止」後會顯示「正在產生最後一個話題的摘要，約需 10 秒…」，完成後跳出提示，可按「打開資料夾」。
