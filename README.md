# 종목 퀵뷰 (올인원 버전)

## 이번에 뭐가 바뀌었나요

- 이전 버전은 `region_select.py`를 매번 따로 실행해야 했는데, 이제는 **`app.py` 하나만 실행**하면
  빨간 테두리 박스(캡처영역)와 노란 메모창이 동시에 뜨고, **그 자리에서 바로 드래그로 옮기고
  모서리로 크기조절**할 수 있습니다. 스크립트를 다시 실행할 필요가 없습니다.
- 위치/크기는 움직이거나 크기 조절한 직후 자동으로 `config.json`에 저장되어, 다음에 켜도 그대로 유지됩니다.
- OCR이 테두리 안쪽 내용만 정확히 잘라서 읽도록 고쳤고, 여러 임계값으로 재시도하도록 했습니다.

## 설치 (최초 1회)

1. 파이썬 설치 (python.org, 설치시 "Add python.exe to PATH" 체크)
2. Windows에 Tesseract-OCR 설치: https://github.com/UB-Mannheim/tesseract/wiki
   - 설치만 하면 프로그램이 알아서 경로를 찾습니다. 코드를 따로 고칠 필요는 없어요.
   - 혹시 자동으로 못 찾으면(설치 경로를 아주 특이하게 바꾼 경우) 콘솔에 안내 메시지가 뜹니다.

## 실행 방법 (둘 중 편한 것으로)

### 방법 A. 그냥 배치파일 더블클릭 (매번 파이썬으로 실행)
`run.bat` 더블클릭 → 라이브러리 설치 후 자동 실행됩니다.

### 방법 B. 진짜 exe 파일로 만들어서 평소처럼 쓰기 (추천, 딱 한 번만 하면 됨)
1. `build_exe.bat` 더블클릭 (한 번만, 몇 분 걸릴 수 있음)
2. 다 되면 `dist` 폴더 안에 `StockQuickView.exe` 가 생깁니다.
3. (키움 브릿지도 쓰신다면) `kiwoom_bridge\build_exe_kiwoom.bat` 도 한 번 실행해서
   `kiwoom_bridge\dist\KiwoomBridge.exe` 를 만들어두세요.
4. **이후로는 매일 `start_all.bat` 더블클릭 한 번이면 끝입니다.**
   (키움 브릿지 exe가 있으면 자동으로 먼저 켜고, 로그인창만 직접 확인해주시면 됩니다.
   키움을 안 쓰신다면 이 파일 없이 `StockQuickView.exe`만 있어도 정상 동작해요.)

⚠️ 저는 리눅스 환경에서 코드를 작성해서, Windows용 .exe를 직접 만들어 드릴 수는 없어요.
`build_exe.bat`/`build_exe_kiwoom.bat`은 사용자분 컴퓨터(Windows)에서 한 번 실행해야 exe가 만들어집니다.
그 이후로는 계속 `start_all.bat` 하나만 쓰면 됩니다.

## 처음 켰을 때 할 일 (최초 설정, 이후엔 안 해도 됨)

1. 빨간 테두리 박스가 화면 어딘가에 뜹니다.
2. **테두리를 드래그**해서 HTS의 종목코드 숫자(예: 098660) 바로 위로 옮깁니다.
3. **오른쪽 아래 빨간 모서리를 드래그**해서 박스 크기를 종목코드 6자리 숫자만 딱 감싸도록 맞춥니다.
   - ⚠️ 아주 중요: 차트나 색깔 있는 배경까지 같이 잡히면 OCR이 엉뚱한 문자를 읽습니다.
     반드시 **숫자만 깔끔하게 나오는 자리**(코드 표시란)를 좁게 감싸주세요.
4. 노란 메모창도 원하는 위치/크기로 조절합니다.
5. 이제 HTS에서 종목을 바꿔보면 0.3초 안에 메모가 갱신됩니다.

이후로는 실행할 때마다 이 위치/크기가 자동으로 유지되니 다시 할 필요 없습니다.
혹시 나중에 위치가 틀어지면 그냥 다시 드래그해서 옮기면 바로 저장됩니다.

## 메모창 오른쪽 위 ⚙ 버튼

- **캡처 영역 보이기/숨기기**: 설정 다 끝났으면 빨간 테두리 박스를 숨겨서 안 거슬리게 할 수 있어요.
- **종료**: 프로그램을 끕니다.

## 디스크 캐시 (속도 개선)

한 번 조회한 종목의 업종/실적은 `local_cache.json` 파일에 저장되어, 프로그램을 껐다 켜도
유지됩니다. 업종은 14일, 실적은 1일간 캐시를 씁니다 (그 안에 같은 종목을 다시 보면
네이버/키움에 재요청 없이 바로 표시). 파일 용량은 아주 작습니다 (종목당 1KB 미만).

혹시 특정 종목의 정보가 이상하게 캐시되어 있다면, `local_cache.json` 파일을 열어서
해당 줄을 지우거나 파일 자체를 삭제하면 다음 조회 때 새로 받아옵니다.

## 실적 분석 (연속 흑자 / 흑자 전환)

실적 최근 몇 개 분기를 같이 보고 아래 내용을 자동으로 계산해서 보여줍니다 (추가 네트워크
요청 없이, 이미 받아온 표 안의 데이터를 활용합니다):
- 영업이익 연속 흑자 분기 수
- 이번 분기 영업이익 흑자 전환 여부
- 매출 성장세 전환 여부

## 그래도 이상한 문자가 나온다면

1. 캡처 박스가 숫자만 딱 감싸고 있는지 다시 확인해주세요 (여백/차트선/아이콘 포함 X).
2. HTS 차트 폰트 크기를 조금 키워보세요 (너무 작으면 OCR이 잘 못 읽습니다).
3. 그래도 안 되면, 어떤 글자가 잘못 나오는지 알려주세요. 그 패턴 보고 전처리를 더 다듬을게요.

## 비용

업종/실적/뉴스 전부 네이버금융에서 무료로 긁어오는 방식이라 별도 비용은 없습니다.
단, 네이버 페이지 구조가 바뀌면 `crawler.py`의 파싱 부분을 손봐야 할 수 있어요.


StockQuickView (All-in-One Version)

What's New in This Version

One-Script Seamless Execution: Previously, you had to run region_select.py separately. Now, simply run app.py to instantly launch both the red capture box and the yellow note window. You can drag to move and resize them on the fly via their edges without restarting the script.

Auto-Save Configuration: Positions and dimensions are automatically saved to config.json immediately after moving or resizing, persisting across application restarts.

Enhanced OCR Accuracy: Improved the crop logic so the OCR targets only the inside of the bounding box. It also retries recognition using multiple adaptive threshold values for maximum accuracy.


Prerequisites & Installation (First-time only)
1. Install Python: Download from python.org (Make sure to check "Add python.exe to PATH" during installation).
2. Install Tesseract-OCR for Windows: Download the installer from the UB-Mannheim Tesseract Wiki.
   1.The application automatically detects the default Tesseract path. No manual code modification is required.
   2. If you choose a custom installation path and the app fails to locate it, a guided path setup message will appear in the console.

How to Run (Choose Option A or B)

Option A. Run via Batch File (Launches via Python every time)
Double-click run.bat → Automatically installs required libraries and launches the application.

Option B. Build & Run as an Executable (Recommended, One-time setup)
1.Double-click build_exe.bat (This single-use process may take a few minutes)
2.Once complete, StockQuickView.exe will be generated inside the dist folder.
3.(Optional for Kiwoom Bridge users) Execute kiwoom_bridge\build_exe_kiwoom.bat to generate kiwoom_bridge\dist\KiwoomBridge.exe.
4.Moving forward, simply double-click start_all.bat to launch everything.
   1.If the Kiwoom Bridge executable is present, it will launch first automatically (you only need to handle the manual login window). The app runs perfectly as a standalone StockQuickView.exe even if you do not use Kiwoom.

Initial Setup Guide (First-time only)
1. A red capture bounding box will appear on your screen upon launch.
2. Drag the red box directly over the stock code field (e.g., 098660) on your HTS (Home Trading System)
3. .Drag the bottom-right corner to resize the box so it tightly wraps only the 6-digit stock code.
   1.⚠️ Crucial: If charts, background colors, or text padding bleed into the box, the OCR engine may output garbage characters. Ensure it tightly bounds only the clean numeric text area.
4. Adjust the yellow note window to your preferred size and position.
5. Switch stocks in your HTS; the note will dynamically refresh within 0.3 seconds.

Your layout configurations will automatically persist for future sessions. If the window alignment shifts, simply drag to reposition, and the new coordinates will overwrite the previous config.

Note Window Settings (⚙ Gear Button)
 - Toggle Capture Region Visibility: Hide the red bounding box once configuration is complete to keep your workspace clean.
 - Exit: Safely terminates the application.

High-Performance Disk Caching

Stock financials and sectors are stored locally in local_cache.json to optimize performance across restarts.

 - Sectors: Cached for 14 days.
 - Financials: Cached for 1 day.
   (Repeatedly viewing the same tickers within these windows loads data instantly from the local cache without making redundant requests to Naver/Kiwoom. The footprint is minimal, under 1KB per ticker.)

If a specific stock's data is corrupted or improperly cached, open local_cache.json and delete the corresponding row (or wipe the file entirely) to force a fresh fetch on the next lookup.

Financial Analysis Engine (Consecutive Profits / Turnaround Diagnostics)

The engine parses trailing quarterly data out of the box to calculate and display advanced financial metrics without spawning extra network overhead:

Consecutive quarters of profitable operating income.
Current quarter profitability turnarounds (Turned-to-Profit).
Structural revenue growth trend shifts.

Troubleshooting OCR Character Artifacts

1. Double-check that the red capture box tightly encompasses the numbers only (exclude margins, chart lines, or UI icons)
2. .Increase your HTS chart/text font size slightly (extremely small pixels degrade OCR recognition quality).
3. If errors persist, please submit an issue detailing the exact corrupted output string. We will refine the pre-processing regex to handle the edge case.

Cost
This tool scraps sector metrics, financial indicators, and live news directly from Naver Financial for free. No API keys or premium fees are required.
Note: If Naver rolls out a breaking database schema change or UI redesign, the parser selectors inside crawler.py may require an update.



