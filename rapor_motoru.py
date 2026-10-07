"""Parsel saha analizi motoru (web uygulaması için).

rapor_uret(geometri, dem_yolu, cikti_klasoru) -> sözlük
  geometri: GeoJSON Polygon/MultiPolygon (WGS84, enlem/boylam)
  Çıktı: <cikti_klasoru>/<id>.png ve <id>.pdf + özet bilgileri
Hatalı girdilerde ValueError fırlatır (mesaj kullanıcıya gösterilir).
"""
import os
import uuid
import datetime
from types import SimpleNamespace

import numpy as np
import geopandas as gpd
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from rasterio.windows import Window, from_bounds, bounds as win_bounds
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.features import geometry_mask
from shapely.geometry import shape, box
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

np.seterr(invalid="ignore")

# ---------------- Ayarlar ----------------
BUF = 100                 # parsel çevresinde ek alan (metre)
SMOOTH = True             # DEM'e hafif yumuşatma
FLAT_DEG = 2              # bu eğimin altı "düz" sayılır (derece)
MIN_PIKSEL_EGRIM_HARITA = 100   # parselde bu kadar DEM hücresi yoksa eşyükselti çizilmez
MIN_ALAN_M2 = 1_000       # 1 dekar
MAX_ALAN_M2 = 2_000_000   # 2000 dekar
SINIR = [5, 15, 30, 50]
SINIF_ADLARI = ["%0–5 (düz / hafif)", "%5–15 (orta)", "%15–30 (dik)",
                "%30–50 (çok dik)", "%50 üstü (aşırı dik)"]
SINIF_RENK = ["#a6d96a", "#fee08b", "#fdae61", "#d73027", "#7f0000"]
YONLER = ["Kuzey", "Kuzeydoğu", "Doğu", "Güneydoğu", "Güney", "Güneybatı", "Batı", "Kuzeybatı"]
BAKI_ADLARI = ["Düz (<%3,5 eğim)"] + YONLER
BAKI_RENK = ["#d9d9d9", "#2166ac", "#67a9cf", "#a1d99b", "#fee08b",
             "#f46d43", "#a6611a", "#b2abd2", "#762a83"]

_FDIR = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(_FDIR, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(_FDIR, "DejaVuSans-Bold.ttf")))


# ---------------- Yardımcılar ----------------
def yuz(p):
    if p == 0:
        return "%0"
    if p < 0.5:
        return "<%1"
    return f"%{p:.0f}"


def _yumusat(a):
    p = np.pad(a, 1, mode="edge")
    h, w = a.shape
    return sum(p[i:i + h, j:j + w] for i in range(3) for j in range(3)) / 9


def _parsel_gdf(geom):
    try:
        g = shape(geom)
    except Exception:
        raise ValueError("Geçersiz geometri.")
    if g.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("Lütfen haritada bir poligon çizin.")
    if not g.is_valid:
        g = g.buffer(0)
    if g.is_empty:
        raise ValueError("Boş geometri.")
    return gpd.GeoDataFrame(geometry=[g], crs=4326)


def _panel(ax, arr, cmap, c, vmin=None, vmax=None, interp="nearest"):
    kw = dict(cmap=cmap, vmin=vmin, vmax=vmax, extent=c.ext, interpolation=interp)
    ax.imshow(arr, alpha=0.3, **kw)
    im = ax.imshow(np.where(c.mask_goster, arr, np.nan), **kw)
    c.parsel_utm.boundary.plot(ax=ax, color="black", linewidth=2)
    ax.set_xlim(c.xlim)
    ax.set_ylim(c.ylim)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    return im


def _olcek_cubugu(ax):
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    hedef = (x1 - x0) / 4
    L = max([v for v in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000) if v <= hedef] or [10])
    bx, by = x0 + (x1 - x0) * 0.05, y0 + (y1 - y0) * 0.04
    ax.plot([bx, bx + L], [by, by], color="black", linewidth=3, solid_capstyle="butt")
    lbl = f"{L} m" if L < 1000 else f"{L // 1000} km"
    ax.text(bx + L / 2, by + (y1 - y0) * 0.012, lbl, ha="center", va="bottom", fontsize=8,
            bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=1))


def _kuzey_oku(ax):
    ax.annotate("", xy=(0.93, 0.90), xytext=(0.93, 0.78), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color="black", lw=2))
    ax.text(0.93, 0.915, "K", transform=ax.transAxes, ha="center", va="bottom",
            fontsize=10, fontweight="bold",
            bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=1))


def _pdf_yaz(yol, png_yol, ozet_satirlari, egim_satirlari, baki_satirlari, not1, not2):
    W, H = landscape(A4)
    c = canvas.Canvas(yol, pagesize=landscape(A4))
    c.setFont("DejaVu-Bold", 17)
    c.drawString(2 * cm, H - 1.8 * cm, "Parsel Saha Analizi Raporu")
    c.setFont("DejaVu", 9)
    c.drawRightString(W - 2 * cm, H - 1.8 * cm, datetime.date.today().strftime("%d.%m.%Y"))

    y0 = H - 3.2 * cm
    adim_y = 0.5 * cm

    def kolon(x, baslik, satirlar):
        c.setFont("DejaVu-Bold", 10)
        c.drawString(x, y0, baslik)
        c.setFont("DejaVu", 9)
        yy = y0 - 0.65 * cm
        for s in satirlar:
            c.drawString(x, yy, s)
            yy -= adim_y
        return yy

    alt = min(kolon(2 * cm, "Özet", ozet_satirlari),
              kolon(11.5 * cm, "Eğim sınıfları (alan)", egim_satirlari),
              kolon(19.5 * cm, "Bakı dağılımı", baki_satirlari[:5]),
              kolon(24.5 * cm, " ", baki_satirlari[5:]))

    img = ImageReader(png_yol)
    iw, ih = img.getSize()
    max_h = alt - 0.4 * cm - 2.4 * cm
    w_img = min(W - 4 * cm, max_h * iw / ih)
    h_img = w_img * ih / iw
    c.drawImage(img, (W - w_img) / 2, 2.4 * cm + (max_h - h_img) / 2, width=w_img, height=h_img)

    c.setFont("DejaVu", 7.5)
    c.drawString(2 * cm, 1.7 * cm, not1[:170])
    if len(not1) > 170:
        c.drawString(2 * cm, 1.3 * cm, not1[170:])
        c.drawString(2 * cm, 0.9 * cm, not2)
    else:
        c.drawString(2 * cm, 1.3 * cm, not2)
    c.save()


# ---------------- Ana fonksiyon ----------------
def rapor_uret(geometri, dem_yolu, cikti_klasoru, parsel_adi="Çizilen parsel"):
    rid = uuid.uuid4().hex[:12]
    cikti = os.path.join(str(cikti_klasoru), rid)

    parsel = _parsel_gdf(geometri)
    utm = parsel.estimate_utm_crs()
    parsel_utm = parsel.to_crs(utm)
    alan_m2 = float(parsel_utm.area.sum())
    if alan_m2 < MIN_ALAN_M2:
        raise ValueError(f"Parsel çok küçük ({alan_m2 / 1000:.1f} dekar). En az {MIN_ALAN_M2 / 1000:.0f} dekar olmalı.")
    if alan_m2 > MAX_ALAN_M2:
        raise ValueError(f"Parsel çok büyük ({alan_m2 / 1000:.0f} dekar). En çok {MAX_ALAN_M2 / 1000:.0f} dekar olabilir.")
    pminx, pminy, pmaxx, pmaxy = parsel.total_bounds
    orta_enlem = (pminy + pmaxy) / 2

    with rasterio.open(dem_yolu) as src:
        parsel_dem = parsel.to_crs(src.crs).geometry.iloc[0]
        if not box(*src.bounds).contains(parsel_dem):
            raise ValueError("Parsel DEM kapsamının dışına çıkıyor. Mavi kesik çizgili alanın içinde çizin.")

        if src.crs.is_geographic:
            cell_m = (abs(src.res[0]) * 111320 * np.cos(np.radians(orta_enlem))
                      + abs(src.res[1]) * 110540) / 2
        else:
            try:
                f = src.crs.linear_units_factor[1]
            except Exception:
                f = 1.0
            cell_m = (abs(src.res[0]) + abs(src.res[1])) / 2 * f
        RES = int(max(2, min(10, round(cell_m))))

        buf = parsel_utm.buffer(BUF).to_crs(src.crs)
        minx, miny, maxx, maxy = buf.total_bounds
        w = from_bounds(minx, miny, maxx, maxy, src.transform)
        win = Window(int(np.floor(w.col_off)), int(np.floor(w.row_off)),
                     int(np.ceil(w.width)) + 1, int(np.ceil(w.height)) + 1)
        try:
            win = win.intersection(Window(0, 0, src.width, src.height))
        except Exception:
            raise ValueError("Parsel DEM dosyasının dışında kalıyor.")
        if win.width < 2 or win.height < 2:
            raise ValueError("Parsel DEM dosyasının dışında kalıyor.")
        data = src.read(1, window=win).astype("float32")
        if src.nodata is not None:
            data[data == src.nodata] = np.nan
        data[data < -500] = np.nan
        win_tr = src.window_transform(win)
        left, bottom, right, top = win_bounds(win, src.transform)

        tr, wd, ht = calculate_default_transform(
            src.crs, utm, data.shape[1], data.shape[0],
            left, bottom, right, top, resolution=RES)
        dem = np.full((ht, wd), np.nan, dtype="float32")
        reproject(source=data, destination=dem,
                  src_transform=win_tr, src_crs=src.crs,
                  dst_transform=tr, dst_crs=utm,
                  resampling=Resampling.bilinear,
                  src_nodata=np.nan, dst_nodata=np.nan)

    ham_piksel = alan_m2 / cell_m ** 2

    # Eğim ve bakı
    dem_s = _yumusat(dem) if SMOOTH else dem
    gy, gx = np.gradient(dem_s, RES)
    slope_pct = np.hypot(gx, gy) * 100
    slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = np.degrees(np.arctan2(-gx, gy)) % 360

    sl_cls = np.digitize(slope_pct, SINIR).astype(float)
    sl_cls[np.isnan(slope_pct)] = np.nan
    asp_cls = (((aspect + 22.5) // 45) % 8) + 1
    asp_cls = np.where(slope_deg < FLAT_DEG, 0, asp_cls)
    asp_cls[np.isnan(slope_deg)] = np.nan

    # Parsel içi istatistikler
    mask = geometry_mask(parsel_utm.geometry, out_shape=dem.shape,
                         transform=tr, invert=True, all_touched=False)
    if (mask & ~np.isnan(slope_pct)).sum() < 20:
        mask = geometry_mask(parsel_utm.geometry, out_shape=dem.shape,
                             transform=tr, invert=True, all_touched=True)
    mask_goster = geometry_mask(parsel_utm.geometry, out_shape=dem.shape,
                                transform=tr, invert=True, all_touched=True)
    valid = mask & ~np.isnan(dem) & ~np.isnan(slope_pct)
    if mask.sum() == 0 or valid.sum() == 0:
        raise ValueError("Parsel içinde geçerli yükseklik verisi bulunamadı.")
    if valid.sum() < 0.9 * mask.sum():
        raise ValueError("Parselin bir kısmında DEM verisi yok (boş alan). Parseli veri olan yerde çizin.")

    z = dem[valid]
    sp = slope_pct[valid]
    n_sinif = len(SINIF_ADLARI)
    egim_dagilim = [float((sl_cls[valid] == k).mean() * 100) for k in range(n_sinif)]
    baki_dagilim = [float((asp_cls[valid] == k).mean() * 100) for k in range(9)]
    baskin = YONLER[int(np.argmax(baki_dagilim[1:]))]

    dusuk_cozunurluk = ham_piksel < MIN_PIKSEL_EGRIM_HARITA
    if dusuk_cozunurluk:
        not1 = (f"Veri: DEM ({cell_m:.0f} m hücre). Parsel yaklaşık {ham_piksel:.0f} DEM hücresi içeriyor; "
                "sonuçlar genel eğilimi gösterir, parsel içi ayrıntı için daha ince çözünürlüklü veri gerekir.")
    else:
        yeniden = "" if RES == round(cell_m) else f", analiz için {RES} m'ye yeniden örneklenmiştir"
        not1 = (f"Veri: DEM ({cell_m:.0f} m hücre{yeniden}). "
                f"Parsel yaklaşık {ham_piksel:.0f} DEM hücresi içeriyor.")
    not2 = "Sonuçlar ön analiz amaçlıdır, saha ölçümü yerine geçmez."

    ozet_satirlari = [
        f"Parsel: {parsel_adi}",
        f"Alan: {alan_m2:,.0f} m² ({alan_m2 / 1000:.1f} dekar)",
        f"Yükseklik (min / ort / maks): {z.min():.0f} / {z.mean():.0f} / {z.max():.0f} m",
        f"Kot farkı: {z.max() - z.min():.0f} m",
        f"Ortalama eğim: %{sp.mean():.0f}",
        f"Eğim (%95'lik dilim): %{np.percentile(sp, 95):.0f}",
        f"Baskın bakı: {baskin}",
    ]
    egim_satirlari = [f"{n}: {yuz(p)} ({p / 100 * alan_m2 / 1000:.1f} dekar)"
                      for n, p in zip(SINIF_ADLARI, egim_dagilim)]
    baki_satirlari = [f"{n}: {yuz(p)}" for n, p in zip(BAKI_ADLARI, baki_dagilim)]

    # Harita görseli
    ctx = SimpleNamespace(
        ext=(tr.c, tr.c + tr.a * wd, tr.f + tr.e * ht, tr.f),
        mask_goster=mask_goster, parsel_utm=parsel_utm)
    xmin, ymin, xmax, ymax = parsel_utm.total_bounds
    mg = max(xmax - xmin, ymax - ymin) * 0.15
    ctx.xlim = (xmin - mg, xmax + mg)
    ctx.ylim = (ymin - mg, ymax + mg)

    fig, axs = plt.subplots(1, 3, figsize=(12.5, 6.5))
    try:
        im = _panel(axs[0], dem, "terrain", ctx, interp="bilinear")
        aralik = z.max() - z.min()
        adim = 5 if aralik < 50 else 10 if aralik < 150 else 20 if aralik < 400 else 50
        seviyeler = np.arange(np.floor(z.min() / adim) * adim, z.max() + adim, adim)
        if not dusuk_cozunurluk and len(seviyeler) > 1:
            axs[0].contour(np.where(mask_goster, dem_s, np.nan), levels=seviyeler, extent=ctx.ext,
                           origin="upper", colors="k", linewidths=0.4, alpha=0.6)
            cb_etiket = f"Eşyükselti eğrileri: {adim} m aralıklı"
        else:
            cb_etiket = ("Eşyükselti eğrileri düşük çözünürlük nedeniyle çizilmedi"
                         if dusuk_cozunurluk else "")
        axs[0].set_title("Yükseklik (m)")
        cax = axs[0].inset_axes([0.1, -0.09, 0.8, 0.03])
        cb = fig.colorbar(im, cax=cax, orientation="horizontal")
        cb.set_label(cb_etiket, fontsize=8)
        cb.ax.tick_params(labelsize=8)
        _olcek_cubugu(axs[0])
        _kuzey_oku(axs[0])

        _panel(axs[1], sl_cls, ListedColormap(SINIF_RENK), ctx, vmin=-0.5, vmax=n_sinif - 0.5)
        axs[1].set_title("Eğim sınıfları")
        axs[1].legend(handles=[Patch(color=c_, label=f"{n}  {yuz(p)}")
                               for c_, n, p in zip(SINIF_RENK, SINIF_ADLARI, egim_dagilim)],
                      loc="upper center", bbox_to_anchor=(0.5, -0.03), ncol=2, fontsize=8, frameon=False)
        _olcek_cubugu(axs[1])
        _kuzey_oku(axs[1])

        _panel(axs[2], asp_cls, ListedColormap(BAKI_RENK), ctx, vmin=-0.5, vmax=8.5)
        axs[2].set_title("Bakı")
        axs[2].legend(handles=[Patch(color=c_, label=n) for c_, n in zip(BAKI_RENK, BAKI_ADLARI)],
                      loc="upper center", bbox_to_anchor=(0.5, -0.03), ncol=3, fontsize=8, frameon=False)
        _olcek_cubugu(axs[2])
        _kuzey_oku(axs[2])

        plt.tight_layout()
        plt.savefig(cikti + ".png", dpi=150, bbox_inches="tight")
    finally:
        plt.close(fig)

    _pdf_yaz(cikti + ".pdf", cikti + ".png", ozet_satirlari, egim_satirlari,
             baki_satirlari, not1, not2)

    return {
        "id": rid,
        "pdf_url": f"/cikti/{rid}.pdf",
        "png_url": f"/cikti/{rid}.png",
        "uyari": not1 if dusuk_cozunurluk else None,
        "ozet": {
            "alan_dekar": round(alan_m2 / 1000, 1),
            "kot_min": int(round(float(z.min()))),
            "kot_ort": int(round(float(z.mean()))),
            "kot_maks": int(round(float(z.max()))),
            "kot_farki": int(round(float(z.max() - z.min()))),
            "ort_egim": int(round(float(sp.mean()))),
            "p95_egim": int(round(float(np.percentile(sp, 95)))),
            "baskin_baki": baskin,
            "hucre_m": round(float(cell_m), 1),
            "ham_piksel": int(round(float(ham_piksel))),
            "egim_siniflari": [
                {"ad": n, "yuzde": round(p, 1), "dekar": round(p / 100 * alan_m2 / 1000, 1)}
                for n, p in zip(SINIF_ADLARI, egim_dagilim)],
            "baki": [{"ad": n, "yuzde": round(p, 1)} for n, p in zip(BAKI_ADLARI, baki_dagilim)],
        },
    }
