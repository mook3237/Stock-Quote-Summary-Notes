# -*- coding: utf-8 -*-
"""
네이버금융에서 가볍게 정보를 긁어옵니다.
⚠️ 주의: 네이버 페이지 구조가 바뀌면 셀렉터를 다시 맞춰야 할 수 있습니다.
"""
import time
import io
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin

import local_cache

KIWOOM_INFO_URL = "http://127.0.0.1:8765/info"
KIWOOM_THEME_URL = "http://127.0.0.1:8765/theme"

_bridge_alive = None       # None=아직 모름, True/False=마지막으로 확인한 상태
_bridge_last_check = 0
_BRIDGE_RECHECK_SEC = 5    # 꺼져있으면 이 시간 동안은 재확인 안 하고 바로 포기 (매번 기다리는 낭비 방지)


def _bridge_probably_alive():
    """
    매번 실제로 접속을 시도하는 대신, 몇 초에 한 번만 살아있는지 확인하고
    그 사이엔 마지막 결과를 그대로 사용 -> 브릿지가 꺼져있을 때 매 종목마다
    타임아웃을 기다리는 낭비를 없앰.
    """
    global _bridge_alive, _bridge_last_check
    now = time.time()
    if _bridge_alive is not None and (now - _bridge_last_check) < _BRIDGE_RECHECK_SEC:
        return _bridge_alive
    try:
        requests.get(KIWOOM_INFO_URL, params={"code": "000000"}, timeout=0.3)
        _bridge_alive = True
    except requests.exceptions.RequestException:
        _bridge_alive = False
    _bridge_last_check = now
    return _bridge_alive


def get_from_kiwoom_bridge(code: str, timeout=1.5):
    """실적/이름 등 (opt10001). 브릿지가 꺼져있거나 응답 없으면 None -> 네이버로 폴백."""
    if not _bridge_probably_alive():
        return None
    try:
        res = requests.get(KIWOOM_INFO_URL, params={"code": code}, timeout=timeout)
        if res.status_code != 200:
            return None
        data = res.json()
        if "error" in data:
            print("[get_from_kiwoom_bridge] 브릿지 오류:", data["error"])
            return None
        return data
    except requests.exceptions.RequestException:
        return None


def get_theme_from_kiwoom_bridge(code: str, timeout=1.5):
    """업종 대체용 테마명 (opt90001). 실패하면 None -> 네이버 업종으로 폴백."""
    if not _bridge_probably_alive():
        return None
    try:
        res = requests.get(KIWOOM_THEME_URL, params={"code": code}, timeout=timeout)
        if res.status_code != 200:
            return None
        data = res.json()
        if "error" in data:
            return None
        themes = data.get("themes") or []
        return " / ".join(themes[:2]) if themes else None
    except requests.exceptions.RequestException:
        return None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://finance.naver.com/",
}

# 뉴스 제목에 이 단어/패턴이 들어가면 광고 또는 자동생성 시황봇 기사로 보고 제외
AD_KEYWORDS = [
    "무료", "리딩방", "카톡", "카카오톡", "상담", "수익인증", "가입",
    "010-", "문자주식", "급등주포착", "종목추천방", "체험단",
    "데이터랩", "거래상위", "거래대금", "거래량 상위",
]


def _get_soup(session, url, timeout=6, referer=None):
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    res = session.get(url, headers=headers, timeout=timeout)
    print(f"[_get_soup] GET {url} -> status={res.status_code}, bytes={len(res.content)}")
    res.raise_for_status()
    return BeautifulSoup(res.content, "html.parser"), res.url


# 이 단어가 뉴스 제목에 있으면 "종목명/업종이 바뀌었을 수 있다"는 신호로 봄
CORP_ACTION_KEYWORDS = [
    "사명변경", "사명 변경", "상호변경", "상호 변경", "종목명변경", "종목명 변경",
    "회사명 변경", "업종변경", "업종 변경", "지주회사 전환", "물적분할", "인적분할",
    "합병", "코스닥 이전상장", "유가증권 이전상장",
]


def detect_corp_action(news_list):
    """뉴스 제목 중 사명/업종 변경 등을 암시하는 게 있으면 True."""
    for title, _ in news_list:
        if any(kw in title for kw in CORP_ACTION_KEYWORDS):
            print(f"[detect_corp_action] 변경 감지 뉴스: {title}")
            return True
    return False


def get_sector(code: str):
    """업종명을 반환. 못 찾으면 None. (디스크 캐시 사용 - 성공 14일 / 실패 10분)"""
    cached = local_cache.get("sector", code)
    if cached is not None:
        return None if cached == "__NODATA__" else cached

    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        with requests.Session() as s:
            soup, _ = _get_soup(s, url)

            # 방법 1(정확): "업종"이라는 라벨(dt) 바로 옆(dd) 안의 링크를 찾음
            # - 페이지 안에 업종 관련 링크가 여러 개 있을 수 있어서(다른 종목 비교 위젯 등),
            #   그냥 페이지에서 처음 만나는 링크를 집으면 엉뚱한 업종이 나올 수 있음
            dt = soup.find("dt", string=lambda t: t and t.strip() == "업종")
            if dt:
                dd = dt.find_next_sibling("dd")
                if dd:
                    a = dd.find("a")
                    if a and a.get_text(strip=True):
                        sector = a.get_text(strip=True)
                        local_cache.set("sector", code, sector)
                        return sector

            # 방법 2(폴백): 위 구조를 못 찾았을 때만, upjong 링크를 후보로 전부 모아서 로그로 남김
            candidates = soup.find_all(
                "a", href=lambda h: h and "sise_group_detail.naver" in h and "type=upjong" in h
            )
            texts = [c.get_text(strip=True) for c in candidates]
            print(f"[get_sector] dt/dd 방식 실패, 후보 링크들: {texts}")
            if candidates:
                sector = texts[0]
                local_cache.set("sector", code, sector)
                return sector

            print("[get_sector] 업종 링크를 페이지에서 못 찾음 (셀렉터 확인 필요)")
            local_cache.set("sector", code, "__NODATA__", ttl_override=600)
    except Exception as e:
        print("[get_sector] 오류:", e)
    return None


def _find_iframe_src(soup, must_contain):
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if must_contain in src:
            return src
    return None


def _to_number(val):
    """'1,234' 같은 문자열이나 숫자를 float으로. 안 되면 None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).replace(",", "").strip()
        if s in ("", "-", "nan"):
            return None
        return float(s)
    except Exception:
        return None


def get_quarterly_financials(code: str):
    """
    최근 분기(또는 연간) 매출액/영업이익을 dict로 반환.
    데이터를 못 찾으면 None. (디스크 캐시 사용 - 성공 1일 / 실패 10분)
    """
    cached = local_cache.get("finance", code)
    if cached is not None:
        return None if cached == "__NODATA__" else cached

    result = _fetch_quarterly_financials_uncached(code)

    if result is None:
        # 실패도 짧게(10분) 캐시해서, 같은 종목을 계속 다시 봐도 매번 재시도하지 않게 함
        local_cache.set("finance", code, "__NODATA__", ttl_override=600)
    else:
        local_cache.set("finance", code, result)
    return result


def _has_sales_row(tables):
    for df in tables:
        try:
            if "매출액" in df.iloc[:, 0].astype(str).values:
                return True
        except Exception:
            continue
    return False


def _fetch_quarterly_financials_uncached(code: str):
    main_url = f"https://finance.naver.com/item/main.naver?code={code}"
    direct_url = f"https://finance.naver.com/item/coinfo.naver?code={code}&target=finsum_more"

    tables = None
    wise_url = None
    try:
        with requests.Session() as s:
            soup_direct, url_direct = _get_soup(s, direct_url, referer=main_url)
            wise_src = _find_iframe_src(soup_direct, "wisereport.co.kr")
            if wise_src:
                wise_url = wise_src if wise_src.startswith("http") else urljoin(url_direct, wise_src)
                soup3, _ = _get_soup(s, wise_url, referer=url_direct)
                tables = pd.read_html(io.StringIO(str(soup3)))
                print(f"[get_quarterly_financials] (직통 방식) 표 {len(tables)}개 발견")

            # ⭐ 핵심: 매출액/영업이익 표는 이 페이지 안에 바로 없고, 자바스크립트가
            # 별도로 cF1002.aspx를 더 불러와서 채워넣는 부분이라 그 주소를 직접 호출함.
            if not tables or not _has_sales_row(tables):
                fin_url = f"https://navercomp.wisereport.co.kr/v2/company/cF1002.aspx?cmp_cd={code}&finGubun=MAIN"
                soup_fin, _ = _get_soup(s, fin_url, referer=wise_url or direct_url)
                fin_tables = pd.read_html(io.StringIO(str(soup_fin)))
                print(f"[get_quarterly_financials] (Financial Summary 직접 호출) 표 {len(fin_tables)}개 발견")
                if _has_sales_row(fin_tables):
                    tables = fin_tables
    except Exception as e:
        print("[get_quarterly_financials] 직통 방식 오류:", e)

    # 폴백: 예전 방식 - main.naver 안의 iframe을 따라 들어감 (직통 방식이 완전히 실패했을 때만)
    if not tables or not _has_sales_row(tables):
        try:
            with requests.Session() as s:
                soup1, url1 = _get_soup(s, main_url)
                coinfo_src = _find_iframe_src(soup1, "coinfo.naver")
                if not coinfo_src:
                    all_iframes = [f.get("src") for f in soup1.find_all("iframe")]
                    print(f"[get_quarterly_financials] coinfo iframe 못 찾음. 페이지 내 전체 iframe 목록: {all_iframes}")
                else:
                    coinfo_url = urljoin(url1, coinfo_src)
                    soup2, url2 = _get_soup(s, coinfo_url, referer=url1)
                    wise_src = _find_iframe_src(soup2, "wisereport.co.kr")
                    if wise_src:
                        wise_url2 = wise_src if wise_src.startswith("http") else urljoin(url2, wise_src)
                        fin_url = f"https://navercomp.wisereport.co.kr/v2/company/cF1002.aspx?cmp_cd={code}&finGubun=MAIN"
                        soup_fin, _ = _get_soup(s, fin_url, referer=wise_url2)
                        fallback_tables = pd.read_html(io.StringIO(str(soup_fin)))
                        print(f"[get_quarterly_financials] (폴백 방식) 표 {len(fallback_tables)}개 발견")
                        if _has_sales_row(fallback_tables):
                            tables = fallback_tables
        except Exception as e:
            print("[get_quarterly_financials] 폴백 방식 오류:", e)
            return None

    if not tables:
        return None

    target_df = None
    for df in tables:
        try:
            first_col = df.iloc[:, 0].astype(str)
            if first_col.str.contains("매출액").any():
                target_df = df
                break
        except Exception:
            continue

    if target_df is None:
        print("[get_quarterly_financials] '매출액' 행이 있는 표를 못 찾음")
        return None

    try:
        first_col = target_df.iloc[:, 0].astype(str)
        sales_row = target_df[first_col.str.contains("매출액")].iloc[0]
        profit_row = target_df[first_col.str.contains("영업이익")].iloc[0]

        columns = list(target_df.columns)
        # 값이 채워진(과거 실제 실적) 컬럼들을 시간순(과거->최근)으로 모음
        filled_cols = []
        for col in columns[1:]:
            s_val = sales_row.get(col)
            p_val = profit_row.get(col)
            if pd.notna(s_val) and pd.notna(p_val):
                filled_cols.append((str(col), _to_number(s_val), _to_number(p_val)))

        if not filled_cols:
            print("[get_quarterly_financials] 값이 채워진 분기 컬럼을 못 찾음")
            return None

        quarter_label, sales_val, profit_val = filled_cols[-1]  # 제일 최근 분기

        # 영업이익 연속 흑자 분기 수 (최근부터 거꾸로 세다가 적자/결측 만나면 중단)
        profit_streak = 0
        for _, _, p in reversed(filled_cols):
            if p is not None and p > 0:
                profit_streak += 1
            else:
                break

        # 직전 분기 대비 흑자 전환 여부 (이번 분기 흑자, 직전 분기 적자)
        profit_turnaround = False
        if len(filled_cols) >= 2:
            prev_p = filled_cols[-2][2]
            if profit_val is not None and prev_p is not None:
                profit_turnaround = (profit_val > 0) and (prev_p <= 0)

        # 매출 성장 전환 여부 (이번 분기 전분기 대비 증가, 직전엔 감소했었는지)
        sales_turnaround = False
        if len(filled_cols) >= 3:
            s_now, s_prev, s_prev2 = filled_cols[-1][1], filled_cols[-2][1], filled_cols[-3][1]
            if None not in (s_now, s_prev, s_prev2):
                grew_now = s_now > s_prev
                grew_before = s_prev > s_prev2
                sales_turnaround = grew_now and not grew_before

        result = {
            "quarter": quarter_label,
            "sales": sales_val,
            "profit": profit_val,
            "profit_streak": profit_streak,       # 영업이익 연속 흑자 분기 수 (0이면 이번 분기도 적자)
            "profit_turnaround": profit_turnaround,  # 이번 분기 흑자전환 여부
            "sales_turnaround": sales_turnaround,     # 매출 성장세 전환 여부
        }
        local_cache.set("finance", code, result)
        return result
    except Exception as e:
        print("[get_quarterly_financials] 행 추출 오류:", e)
        return None


def get_latest_news(code: str, max_items: int = 6, max_pages: int = 2):
    """
    광고/자동생성 기사를 제외한 최근 뉴스 [(제목, 링크), ...] 리스트 반환.
    한 페이지에서 max_items를 못 채우면 다음 페이지까지 확인합니다.
    """
    base = "https://finance.naver.com"
    news_list = []
    try:
        with requests.Session() as s:
            for page in range(1, max_pages + 1):
                if len(news_list) >= max_items:
                    break
                url = f"{base}/item/news_news.naver?code={code}&page={page}"
                soup, _ = _get_soup(s, url)
                rows = soup.select("table.type5 tr")
                print(f"[get_latest_news] page {page}: 행 {len(rows)}개 발견")
                for row in rows:
                    title_td = row.select_one("td.title a")
                    if not title_td:
                        continue
                    title = title_td.get_text(strip=True)
                    if any(kw in title for kw in AD_KEYWORDS):
                        continue
                    link = urljoin(base, title_td.get("href", ""))
                    if (title, link) not in news_list:
                        news_list.append((title, link))
                    if len(news_list) >= max_items:
                        break
    except Exception as e:
        print("[get_latest_news] 오류:", e)

    return news_list
