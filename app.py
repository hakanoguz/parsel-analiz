"""Parsel saha analizi web uygulaması (FastAPI).

Yerel çalıştırma:  python -m uvicorn app:app --reload   ->  http://127.0.0.1:8000

Ortam değişkenleri (hepsi isteğe bağlı):
  DEM_YOLU       DEM dosyasının yolu (varsayılan: data/dem3m.tif)
  DEM_URL        DEM dosyası yoksa açılışta bu adresten indirilir
  MAX_ALAN_M2    en büyük parsel alanı, m² (varsayılan: 500000 = 500 dekar)
  SAATLIK_LIMIT  IP başına saatlik rapor sınırı (varsayılan: 0 = sınırsız)
"""
import os
import time
import threading
import traceback
import urllib.request
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import rasterio
from rasterio.warp import transform_bounds
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import rapor_motoru

BASE = Path(__file__).parent
DEM_YOLU = Path(os.environ.get("DEM_YOLU", BASE / "data" / "dem3m.tif"))
DEM_URL = os.environ.get("DEM_URL")
SAATLIK_LIMIT = int(os.environ.get("SAATLIK_LIMIT", "0"))
CIKTI = BASE / "cikti"
CIKTI.mkdir(exist_ok=True)

rapor_motoru.MAX_ALAN_M2 = int(os.environ.get("MAX_ALAN_M2", "500000"))

_kilit = threading.Lock()          # matplotlib aynı anda tek rapor üretsin
_istekler = defaultdict(deque)     # IP -> son istek zamanları


def _dem_indir():
    """DEM yoksa ve DEM_URL verilmişse açılışta indir."""
    if DEM_YOLU.exists() or not DEM_URL:
        return
    try:
        DEM_YOLU.parent.mkdir(parents=True, exist_ok=True)
        gecici = DEM_YOLU.with_name(DEM_YOLU.name + ".indiriliyor")
        print(f"DEM indiriliyor: {DEM_URL}", flush=True)
        urllib.request.urlretrieve(DEM_URL, gecici)
        gecici.replace(DEM_YOLU)
        print("DEM indirildi.", flush=True)
    except Exception as e:
        print(f"DEM indirilemedi: {e}", flush=True)


@asynccontextmanager
async def lifespan(app):
    _dem_indir()
    yield


app = FastAPI(title="Parsel Saha Analizi", lifespan=lifespan)


class RaporIstegi(BaseModel):
    geometry: dict


def _dem_kontrol():
    if not DEM_YOLU.exists():
        raise HTTPException(503, "DEM verisi şu an yüklü değil. Lütfen biraz sonra tekrar deneyin.")


def _limit_kontrol(ip):
    if not SAATLIK_LIMIT:
        return
    simdi = time.time()
    q = _istekler[ip]
    while q and q[0] < simdi - 3600:
        q.popleft()
    if len(q) >= SAATLIK_LIMIT:
        raise HTTPException(429, f"Saatlik rapor sınırına ulaştınız ({SAATLIK_LIMIT}). Lütfen daha sonra tekrar deneyin.")
    q.append(simdi)


def _eski_dosyalari_sil(saat=24):
    sinir = time.time() - saat * 3600
    for f in CIKTI.glob("*"):
        try:
            if f.stat().st_mtime < sinir:
                f.unlink()
        except OSError:
            pass


@app.get("/")
def anasayfa():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/saglik")
def saglik():
    return {"durum": "ok", "dem_hazir": DEM_YOLU.exists()}


@app.get("/api/dem-extent")
def dem_kapsami():
    _dem_kontrol()
    with rasterio.open(DEM_YOLU) as src:
        bati, guney, dogu, kuzey = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    return {"bounds": [[guney, bati], [kuzey, dogu]]}


@app.post("/api/rapor")
def rapor(istek: RaporIstegi, request: Request):
    _dem_kontrol()
    _limit_kontrol(request.client.host if request.client else "?")
    _eski_dosyalari_sil()
    try:
        with _kilit:
            return rapor_motoru.rapor_uret(istek.geometry, DEM_YOLU, CIKTI)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        traceback.print_exc()   # hata ayrıntısı sunucu günlüğünde görünür
        raise HTTPException(500, "Rapor üretilirken beklenmeyen bir hata oluştu.")


app.mount("/cikti", StaticFiles(directory=CIKTI), name="cikti")
