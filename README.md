# YouTube Toplu Transkript İndirici (Web & PowerShell)

Bu araç, YouTube kanallarındaki veya oynatma listelerindeki videoların altyazılarını/transkriptlerini otomatik olarak çeker, zaman damgaları ve tekrarlayan kayan yazı karmaşasından arındırarak **temiz, okunabilir düz metin (.txt)** dosyaları haline getirir.

---

## ⚡ Tek Komutla Kurulum (Windows)

**PowerShell**'i açın ve şu satırı yapıştırıp Enter'a basın:

```powershell
irm https://raw.githubusercontent.com/hekizoglu/youtube-transcript-downloader/main/kurulum.ps1 | iex
```

Bu komut; Python, Git ve Deno'yu (yoksa) kurar, projeyi `%USERPROFILE%\youtube-transcript-downloader` klasörüne indirir, bağımlılıkları yükler, **masaüstüne ve Başlat menüsüne "YouTube Transkript" kısayolu** ekler ve uygulamayı açar. Aynı komutu tekrar çalıştırmak projeyi günceller.

---

## 🚀 1. Seçenek: Web Arayüzü (Tavsiye Edilen)

Modern, karanlık modlu, interaktif bir web paneli üzerinden çalışır.

### Gereksinimler
- **Python 3.10+** (kurulumda "Add Python to PATH" işaretli olmalı)
- `yt-dlp` — `baslat.bat` her açılışta `requirements.txt` üzerinden **otomatik olarak en son sürüme günceller**. YouTube sık değişiklik yaptığı için eski yt-dlp sürümleri altyazı çekemeyebilir.
- Önerilen: [Deno](https://deno.com/) — yt-dlp'nin güncel sürümleri YouTube'dan tam veri alabilmek için bir JavaScript çalışma ortamı kullanır. Altyazılar bulunamıyorsa Deno'yu kurmayı deneyin (`winget install DenoLand.Deno`).

Manuel kurulum (Windows dışı sistemler için):
```bash
python -m pip install -U -r requirements.txt
python app.py
```

### Nasıl Başlatılır?
1. `baslat.bat` dosyasına çift tıklayın.
2. Tarayıcınızda otomatik olarak **http://localhost:5500** adresi açılacaktır.

### Özellikler:
- 🎯 **Gelişmiş Tarama:** Kanal linki (örn: `@BarisOzcan`), oynatma listesi veya tek video linkini yapıştırıp tek tıkla listeleyin.
- ⚡ **Seçim & Filtreleme:** Videoları başlığa göre anında arayın, istediğiniz videoları veya tümünü seçin.
- 🌍 **Çoklu Dil Desteği:** Türkçe (`tr`), İngilizce (`en`), Almanca (`de`) veya istediğiniz dilleri seçin.
- ✅ **Doğru Altyazı Önceliği:** Önce insan tarafından yazılmış (manuel) altyazı, sonra videonun orijinal dilindeki otomatik altyazı, en son YouTube makine çevirisi seçilir. Kullanılan kaynak dosya başlığında yazar.
- 🔎 **Transkriptlerde Tam Metin Arama:** "Transkriptlerde Ara" butonuyla indirilen tüm dosyaların içinde kelime arayın; zaman damgalı sonuca tıklayınca video tam o saniyeden açılır. Türkçe karakter ve büyük/küçük harf duyarsızdır.
- 🧹 **Akıllı Temizleme:** VTT/SRT etiketlerini, zaman damgalarını ve YouTube'un tekrar eden otomatik kayan altyazılarını mükemmel bir şekilde temizler.
- 👁️ **Tarayıcıda Anında Okuma:** İndirilen transkriptleri sayfadan ayrılmadan açıp okuyabilir, tek tıkla panoya kopyalayabilir veya TXT olarak indirebilirsiniz.
- 📦 **Tek Tıkla ZIP & Klasör:** Tüm transkriptleri tek tıkla ZIP olarak indirebilir veya Windows Gezgini'nde klasörü açabilirsiniz.

---

## 💻 2. Seçenek: PowerShell Görsel Arayüzü

Eğer tarayıcı kullanmak istemiyorsanız:
1. `transcript_downloader.ps1` dosyasına sağ tıklayıp **"PowerShell ile Çalıştır"** deyin.
2. Açılan görsel pencerelerden kanal linkini ve kayıt klasörünü belirleyin.
3. Açılan listeden (`Out-GridView`) istediğiniz videoları seçip **Tamam**'a basın.

---

## 📂 Dosya Yapısı

- `kurulum.ps1`: Tek komutla kurulum ve kısayol oluşturma betiği.
- `baslat.bat`: Web uygulamasını başlatan tek tıkla çalıştırıcı.
- `app.py`: Yerel Python API ve web sunucusu (`localhost:5500`).
- `index.html`: Modern Tailwind CSS tabanlı görsel web arayüzü.
- `transcript_downloader.ps1`: Alternatif PowerShell görsel betiği.
- `requirements.txt`: Python bağımlılıkları (yt-dlp).
- `transkriptler/`: İndirilen ve temizlenen tüm `.txt` dosyalarının kaydedildiği klasör. Dosya adları `Başlık [videoID].txt` biçimindedir; eski `001_Başlık.txt` dosyaları da tanınır ve yeniden indirildiğinde yeni ada taşınır.

