# Parsel Saha Analizi

Haritada bir parsel çizin; yükseklik, eğim sınıfları ve bakı analizini içeren tek sayfalık PDF rapor alın.
Açık kaynak araçlarla geliştirilmiştir (Python, FastAPI, Leaflet, rasterio, GeoPandas).

*English: draw a parcel on a map and get a one-page PDF site-analysis report (elevation, slope classes, aspect) computed from a DEM. Built with open-source tools only.*

## Ne yapar?

- Leaflet haritasında çizilen poligonu alır
- DEM'den parsel için yükseklik, eğim sınıfları (%0–5, 5–15, 15–30, 30–50, 50+) ve bakı dağılımını hesaplar
- Harita görselleri ve tablolarla PDF rapor üretir
- DEM çözünürlüğüne göre otomatik uyarı verir (parselde az sayıda hücre varsa sonuçlar kaba kabul edilmelidir)

## Yerelde çalıştırma

```
python -m venv gis-env
gis-env\Scripts\activate          # Mac/Linux: source gis-env/bin/activate
pip install -r requirements.txt
```

Bir DEM (GeoTIFF) dosyasını `data/dem3m.tif` olarak koyun (ya da `DEM_YOLU` ortam değişkenini verin), sonra:

```
python -m uvicorn app:app --reload
```

Tarayıcıda `http://127.0.0.1:8000` adresini açın. Haritada mavi kesik çizgili alan DEM'in kapsadığı yerdir; parseli onun içine çizin.

## Docker ile

```
docker build -t parsel-analiz .
docker run -p 8000:8000 -v "%cd%\data:/app/data" parsel-analiz
```

(Mac/Linux'ta `-v "$(pwd)/data:/app/data"`.)

## Ortam değişkenleri

| Değişken | Anlamı | Varsayılan |
|---|---|---|
| `DEM_YOLU` | DEM dosyasının yolu | `data/dem3m.tif` |
| `DEM_URL` | DEM yoksa açılışta bu adresten indirilir | yok |
| `MAX_ALAN_M2` | En büyük parsel alanı (m²) | 500000 |
| `SAATLIK_LIMIT` | IP başına saatlik rapor sınırı (0 = sınırsız) | 0 (Docker'da 20) |

## Veri hakkında

DEM bu depoya **dahil değildir**. Geliştirme sırasında 3 m çözünürlüklü lidar DEM kullanılmıştır
(NASA SnowEx20-21 QSI Lidar DEM 3 m, NSIDC).
Bir veri setini kullanmadan veya yeniden dağıtmadan önce kaynağın sayfasındaki lisans ve atıf koşullarını kontrol edin ve buraya ekleyin:

> Veri atfı: *(buraya veri setinin istediği atıf metnini yazın)*

Bu yazılım hazır bir ulusal DEM sağlamaz. Doğruluk tamamen kullanılan DEM'in çözünürlüğüne ve kalitesine bağlıdır.

## Sınırlamalar

- Sonuçlar ön analiz amaçlıdır, saha ölçümü yerine geçmez.
- 30 m gibi kaba DEM'lerle küçük parsellerde parsel içi ayrıntı elde edilemez.
- Genel kullanıma açık kopyalarda harita altlığı sağlayıcılarının (OpenStreetMap, OpenTopoMap) kullanım koşullarına uyun.

## Lisans

*(Lisans seçildikten sonra buraya yazılacak.)*
