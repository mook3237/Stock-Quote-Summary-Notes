# -*- coding: utf-8 -*-
"""
종목코드-이름 전체 리스트를 "추가 라이브러리 설치 없이" 만듭니다.
(예전엔 FinanceDataReader를 썼는데, 그게 설치가 막히는 환경이 있어서 제거했습니다.
 requests/pandas/bs4는 이미 requirements.txt에 있어서 별도 설치가 필요 없습니다.)

방법 1(1순위): KRX 상장법인목록 다운로드 페이지 (한 번의 요청으로 전체를 받음, 빠름)
방법 2(폴백): 네이버금융 시가총액 페이지를 페이지별로 순회하며 모음 (방법 1이 막히면 사용)
"""
import os
import re
import time
import pandas as pd
import io
import requests
from bs4 import BeautifulSoup

from paths import get_base_dir

CACHE_PATH = os.path.join(get_base_dir(), "stock_list_cache.csv")
CACHE_TTL_SEC = 60 * 60 * 24  # 24시간

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _decode_best_effort(content: bytes) -> str:
    """euc-kr/utf-8 둘 다 시도해서, 깨진 문자(대체문자)가 더 적은 쪽을 선택"""
    candidates = []
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            text = content.decode(enc)
            broken = text.count("\ufffd")  # 유니코드 대체문자(깨진 글자) 개수
            candidates.append((broken, enc, text))
        except Exception:
            continue
    if not candidates:
        return content.decode("utf-8", errors="replace")
    candidates.sort(key=lambda x: x[0])  # 깨진 글자가 제일 적은 인코딩 선택
    broken, enc, text = candidates[0]
    print(f"[_decode_best_effort] 선택된 인코딩: {enc} (깨진 글자 {broken}개)")
    return text


def _fetch_from_kind():
    """KRX(한국거래소) 상장법인목록 다운로드 - 한 번의 요청으로 전체 종목을 받아옴"""
    url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.raise_for_status()
    print(f"[_fetch_from_kind] status={res.status_code}, bytes={len(res.content)}")

    html_text = _decode_best_effort(res.content)
    tables = pd.read_html(io.StringIO(html_text))
    print(f"[_fetch_from_kind] 표 {len(tables)}개 발견")

    # 표가 여러 개일 수 있으니, '회사명'과 '종목코드' 컬럼이 있는 표를 직접 찾음
    target = None
    for df in tables:
        if "회사명" in df.columns and "종목코드" in df.columns:
            target = df
            break

    if target is None:
        raise ValueError(f"'회사명'/'종목코드' 컬럼이 있는 표를 못 찾음. 발견된 컬럼들: "
                          f"{[list(df.columns) for df in tables]}")

    target = target.rename(columns={"회사명": "Name", "종목코드": "Code"})
    target["Code"] = target["Code"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6)
    return target[["Code", "Name"]]


def _fetch_from_naver_pages():
    """폴백: 네이버금융 시가총액 페이지를 페이지별로 순회하며 종목코드/이름을 모음"""
    rows = []
    with requests.Session() as s:
        for sosok in (0, 1):  # 0=코스피, 1=코스닥
            page = 1
            empty_streak = 0
            while page <= 60:  # 안전장치 (한쪽 시장이 60페이지를 넘을 일은 없음)
                url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
                try:
                    res = s.get(url, headers=HEADERS, timeout=10)
                    soup = BeautifulSoup(res.content, "html.parser")
                except Exception as e:
                    print(f"[_fetch_from_naver_pages] sosok={sosok} page={page} 요청 실패:", e)
                    break

                # 클래스명(a.tltle)에 의존하지 않고, href 패턴 자체로 종목 링크를 찾음
                # (네이버가 클래스명을 바꿔도 안 깨지도록)
                found = 0
                for a in soup.find_all("a", href=True):
                    m = re.search(r"/item/main\.naver\?code=(\d{6})", a["href"])
                    if m:
                        name = a.get_text(strip=True)
                        if name:  # 빈 텍스트(아이콘 링크 등)는 제외
                            rows.append((m.group(1), name))
                            found += 1

                print(f"[_fetch_from_naver_pages] sosok={sosok} page={page}: {found}개 매칭")

                if found == 0:
                    empty_streak += 1
                    if empty_streak >= 2:  # 연속 2페이지가 비면 그 시장은 끝난 것으로 판단
                        break
                else:
                    empty_streak = 0

                page += 1
                time.sleep(0.2)

    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["Code", "Name"]).drop_duplicates()
    print(f"[_fetch_from_naver_pages] 최종 수집된 행 수: {len(df)}")
    return df


def load_stock_db():
    """
    종목코드-이름 캐시를 불러옵니다. 실패해도 예외를 던지지 않고 None을 반환합니다.
    (호출하는 쪽에서 None이면 '종목명 매칭은 안 되지만 계속 동작'하도록 처리)
    """
    if os.path.exists(CACHE_PATH) and (time.time() - os.path.getmtime(CACHE_PATH) < CACHE_TTL_SEC):
        try:
            return pd.read_csv(CACHE_PATH, dtype={"Code": str})
        except Exception as e:
            print("[load_stock_db] 캐시 파일 읽기 실패:", e)

    for fetch_fn, label in [(_fetch_from_kind, "KRX"), (_fetch_from_naver_pages, "네이버")]:
        try:
            df = fetch_fn()
            if df is not None and len(df) > 0:
                df.to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")
                print(f"[load_stock_db] {label}에서 {len(df)}개 종목 목록 저장 완료")
                return df
        except Exception as e:
            print(f"[load_stock_db] {label} 방식 실패:", e)

    # 둘 다 실패하면, 오래됐더라도 기존 캐시라도 사용
    if os.path.exists(CACHE_PATH):
        try:
            print("[load_stock_db] 최신 목록을 못 받아서 기존 캐시(오래됨)를 사용합니다")
            return pd.read_csv(CACHE_PATH, dtype={"Code": str})
        except Exception:
            pass
    return None


def code_to_name(df, code: str):
    if df is None:
        return None
    row = df[df["Code"] == code]
    if len(row):
        return row.iloc[0]["Name"]
    return None


def is_valid_code(df, code: str) -> bool:
    """df가 없으면(종목리스트 로드 실패) 6자리 숫자 형태인지만이라도 확인"""
    if df is None:
        return bool(re.fullmatch(r"\d{6}", code))
    return code in set(df["Code"])
