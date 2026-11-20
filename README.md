# YouTube Toplu Transkript İndirici (Web & PowerShell)

Bu araç, YouTube kanallarındaki veya oynatma listelerindeki videoların altyazılarını/transkriptlerini otomatik olarak çeker, zaman damgaları ve tekrarlayan kayan yazı karmaşasından arındırarak **temiz, okunabilir düz metin (.txt)** dosyaları haline getirir.

---

## 🚀 1. Seçenek: Web Arayüzü (Tavsiye Edilen)

Modern, karanlık modlu, interaktif bir web paneli üzerinden çalışır.

### Nasıl Başlatılır?
1. `baslat.bat` dosyasına çift tıklayın.
2. Tarayıcınızda otomatik olarak **http://localhost:5500** adresi açılacaktır.

### Özellikler:
- 🎯 **Gelişmiş Tarama:** Kanal linki (örn: `@BarisOzcan`), oynatma listesi veya tek video linkini yapıştırıp tek tıkla listeleyin.
- ⚡ **Seçim & Filtreleme:** Videoları başlığa göre anında arayın, istediğiniz videoları veya tümünü seçin.
- 🌍 **Çoklu Dil Desteği:** Türkçe (`tr`), İngilizce (`en`), Almanca (`de`) veya istediğiniz dilleri seçin.
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

- `baslat.bat`: Web uygulamasını başlatan tek tıkla çalıştırıcı.
- `app.py`: Yerel Python API ve web sunucusu (`localhost:5500`).
- `index.html`: Modern Tailwind CSS tabanlı görsel web arayüzü.
- `transcript_downloader.ps1`: Alternatif PowerShell görsel betiği.
- `transkriptler/`: İndirilen ve temizlenen tüm `.txt` dosyalarının kaydedildiği klasör.

