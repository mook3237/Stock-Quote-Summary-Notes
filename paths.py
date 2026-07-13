# -*- coding: utf-8 -*-
"""
업종/실적 조회 결과를 디스크 파일에 저장해두는 캐시.
프로그램을 껐다 켜도 유지되어서, 한 번 본 종목은 다음에 훨씬 빨리 나옵니다.
(용량은 매우 작음 - 종목 하나당 1KB 미만, 전 종목 다 쌓여도 몇 MB 수준)
"""
import os
import json
import time
import threading

from paths import get_base_dir

CACHE_PATH = os.path.join(get_base_dir(), "local_cache.json")

# 항목별 캐시 유지 기간 (초). 업종은 거의 안 바뀌니 길게, 실적은 분기 단위로만 바뀌니 하루 정도.
TTL = {
    "sector": 14 * 24 * 3600,   # 14일
    "finance": 1 * 24 * 3600,   # 1일
}

_lock = threading.Lock()
_data = None


def _load():
    global _data
    if _data is not None:
        return _data
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                _data = json.load(f)
        except Exception:
            _data = {}
    else:
        _data = {}
    return _data


def _save():
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print("[local_cache] 저장 실패:", e)


def get(kind: str, code: str):
    """kind: 'sector' 또는 'finance'. 유효기간 지났으면 None."""
    with _lock:
        data = _load()
        key = f"{kind}:{code}"
        entry = data.get(key)
        if not entry:
            return None
        ts, value, *rest = entry
        ttl = rest[0] if rest else TTL.get(kind, 3600)
        if time.time() - ts > ttl:
            return None
        return value


def set(kind: str, code: str, value, ttl_override=None):
    with _lock:
        data = _load()
        key = f"{kind}:{code}"
        ttl = ttl_override if ttl_override is not None else TTL.get(kind, 3600)
        data[key] = [time.time(), value, ttl]
        _save()


def invalidate(kind: str, code: str):
    """특정 종목의 캐시를 강제로 지움 (다음 조회 때 새로 받아오게)"""
    with _lock:
        data = _load()
        key = f"{kind}:{code}"
        if key in data:
            del data[key]
            _save()
