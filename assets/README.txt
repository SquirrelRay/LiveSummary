程式圖示放這裡：assets\icon.ico（Windows .ico，建議一個檔裡含 16、24、32、48、64、128、256 像素各一張）。

- 有這個檔：打包時套用到 LiveSummary.exe、helper.exe 的圖示，並附進 _internal\assets\icon.ico，
  程式啟動時用它當視窗圖示（app.py：QApplication.setWindowIcon）。
- 沒有這個檔：全部用預設圖示，打包不會失敗。
- 位置寫在 app_paths.圖示相對位置；LiveSummary.spec、app.py 都只從那裡取。
