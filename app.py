import os
import sys
import json
import re
import io
import zipfile
import webbrowser
import threading
import subprocess
import unicodedata
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
import yt_dlp

PORT = 5500
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transkriptler")
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

def format_duration(dur) -> str:
    if dur is None or dur == "NA":
        return "Bilinmiyor"
    if isinstance(dur, str) and ":" in dur:
        return dur
    try:
        secs = int(float(dur))
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    except Exception:
        return str(dur)

def sanitize_filename(name: str) -> str:
    clean = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean[:100]

def format_timestamp(raw_ts: str) -> str:
    parts = raw_ts.split(":")
    if len(parts) == 3:
        h, m, s = parts[0], parts[1], parts[2].split(".")[0]
        if h == "00":
            return f"{m}:{s}"
        return f"{h}:{m}:{s}"
    elif len(parts) == 2:
        m, s = parts[0], parts[1].split(".")[0]
        return f"{m}:{s}"
    return raw_ts

def process_vtt(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    clean_lines_clean = []
    clean_lines_ts = []
    last_line = ""
    current_ts = "00:00"

    for l in lines:
        s = l.strip()
        if not s or s.startswith("WEBVTT") or s.startswith("Kind:") or s.startswith("Language:"):
            continue
        
        if "-->" in s:
            match = re.match(r"^(\d{2}:\d{2}(?::\d{2})?)", s)
            if match:
                current_ts = format_timestamp(match.group(1))
            continue

        if s.isdigit():
            continue

        s = re.sub(r"<[^>]+>", "", s).strip()
        if not s or s == last_line:
            continue

        if last_line and s.startswith(last_line):
            if clean_lines_clean:
                clean_lines_clean[-1] = s
                clean_lines_ts[-1] = f"[{current_ts}] {s}"
            else:
                clean_lines_clean.append(s)
                clean_lines_ts.append(f"[{current_ts}] {s}")
            last_line = s
            continue

        if last_line:
            w1 = last_line.split()
            w2 = s.split()
            overlap = 0
            for k in range(min(len(w1), len(w2)), 0, -1):
                if w1[-k:] == w2[:k]:
                    overlap = k
                    break
            if overlap > 0:
                s = " ".join(w2[overlap:])

        if s:
            clean_lines_clean.append(s)
            clean_lines_ts.append(f"[{current_ts}] {s}")
            last_line = s

    formatted_ts = "\n".join(clean_lines_ts)

    full_clean = " ".join(clean_lines_clean)
    sentences = re.split(r'(?<=[.!?])\s+', full_clean)
    paragraphs = []
    curr_p = []
    for sent in sentences:
        curr_p.append(sent)
        if len(curr_p) >= 4 or sum(len(x) for x in curr_p) > 350:
            paragraphs.append(" ".join(curr_p))
            curr_p = []
    if curr_p:
        paragraphs.append(" ".join(curr_p))
    formatted_clean = "\n\n".join(paragraphs) if paragraphs else full_clean

    return formatted_ts, formatted_clean

TS_LINE_RE = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$")
LINK_RE = re.compile(r"^Video Linki:\s*(\S+)", re.MULTILINE)
TITLE_RE = re.compile(r"^Video Başlığı:\s*(.+)$", re.MULTILINE)


def build_filename(video_id: str, title: str) -> str:
    """Dosya adı: 'Başlık [videoID].txt' -> ID sayesinde önbellek eşleşmesi kesin olur."""
    return f"{sanitize_filename(title)} [{video_id}].txt"


def has_timestamps(text: str) -> bool:
    return any(TS_LINE_RE.match(line) for line in text.splitlines()[:50])


def find_existing_file(video_id: str, safe_title: str) -> str | None:
    """Yalnızca benzersiz video ID etiketi ile ([video_id]) tam eşleşme arar.
    Başlık benzerliklerinden kaynaklanan mükerrer (+1/2 fazla) eşleşmeleri engeller."""
    if not os.path.exists(TRANSCRIPTS_DIR):
        return None
    files = [f for f in os.listdir(TRANSCRIPTS_DIR) if f.endswith(".txt")]
    tag = f"[{video_id}]"
    for f in files:
        if tag in f:
            return f
    return None


def read_transcript_file(filename: str) -> str | None:
    try:
        with open(os.path.join(TRANSCRIPTS_DIR, filename), "r", encoding="utf-8") as tf:
            return tf.read()
    except OSError:
        return None


def get_existing_transcript(video_id: str, safe_title: str) -> tuple[str, str] | None:
    f = find_existing_file(video_id, safe_title)
    if not f:
        return None
    text = read_transcript_file(f)
    return (f, text) if text is not None else None


def pick_subtitle(info: dict, lang_list: list[str]):
    """Altyazı seçimi. Öncelik:
    1) Manuel (insan yazımı) altyazı, 2) videonun orijinal dilindeki otomatik altyazı,
    3) son çare olarak YouTube'un makine çevirisi otomatik altyazı.
    Dönüş: (dil_kodu, vtt_url, kaynak) veya None
    """
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}

    def vtt_url(fmts):
        for fmt in fmts or []:
            if fmt.get("ext") == "vtt" and fmt.get("url"):
                return fmt["url"]
        return None

    def base(code):
        return code.split("-")[0].lower()

    # 1. ve 2. tur: manuel ve orijinal otomatik altyazılar
    for lang in lang_list:
        lang_l = lang.lower()
        for key in sorted(manual, key=lambda k: (k.lower() != lang_l, k)):
            if key.lower() == lang_l or base(key) == lang_l:
                url = vtt_url(manual[key])
                if url:
                    return key, url, "manuel"
        orig = f"{lang_l}-orig"
        if orig in auto:
            url = vtt_url(auto[orig])
            if url:
                return lang_l, url, "otomatik"
        # Orijinal dili bu dil olan videolarda yt-dlp bazen '-orig' eki koymaz
        if auto and not any(k.endswith("-orig") for k in auto) and info.get("language", "").lower().startswith(lang_l) and lang_l in auto:
            url = vtt_url(auto[lang_l])
            if url:
                return lang_l, url, "otomatik"

    # 3. tur: makine çevirisi
    for lang in lang_list:
        lang_l = lang.lower()
        if lang_l in auto:
            url = vtt_url(auto[lang_l])
            if url:
                return lang_l, url, "otomatik çeviri"
    return None


def normalize_text(s: str) -> str:
    """Türkçe ve aksan duyarsız küçük harf normalizasyonu (arama için)."""
    s = s.replace("I", "ı").replace("İ", "i").lower()
    s = s.replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def ts_to_seconds(ts: str) -> int:
    total = 0
    for part in ts.split(":"):
        total = total * 60 + int(part)
    return total


def search_transcripts(query: str, max_results: int = 300) -> dict:
    q = normalize_text(query.strip())
    if not q:
        return {"query": query, "total_hits": 0, "files": [], "truncated": False}
    terms = q.split()
    results = []
    total = 0
    truncated = False
    for f in sorted(os.listdir(TRANSCRIPTS_DIR)):
        if not f.endswith(".txt"):
            continue
        text = read_transcript_file(f)
        if not text:
            continue
        link_m = LINK_RE.search(text)
        title_m = TITLE_RE.search(text)
        link = link_m.group(1) if link_m else None
        body = text.split("=" * 60, 1)[-1]
        hits = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            norm = normalize_text(line)
            if not all(t in norm for t in terms):
                continue
            m = TS_LINE_RE.match(line)
            ts = m.group(1) if m else None
            snippet = m.group(2) if m else line
            if not m and len(snippet) > 300:
                # Düz metin paragraflarında eşleşmenin etrafından kes
                idx = normalize_text(snippet).find(terms[0])
                start = max(0, idx - 120)
                snippet = ("…" if start else "") + snippet[start:start + 260] + "…"
            hit = {"timestamp": ts, "text": snippet}
            if link and ts:
                hit["url"] = f"{link}&t={ts_to_seconds(ts)}s"
            hits.append(hit)
            total += 1
            if total >= max_results:
                truncated = True
                break
        if hits:
            results.append({
                "file": f,
                "title": title_m.group(1).strip() if title_m else f[:-4],
                "link": link,
                "hits": hits,
            })
        if truncated:
            break
    return {"query": query, "total_hits": total, "files": results, "truncated": truncated}


def open_in_file_manager(path: str):
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


ALLOWED_HOSTS = ("localhost", "127.0.0.1")


class TranscriptServer(BaseHTTPRequestHandler):
    def _is_local_request(self) -> bool:
        """Başka bir web sitesinin tarayıcı üzerinden bu yerel API'yi tetiklemesini engeller."""
        origin = self.headers.get("Origin")
        if origin:
            return urlparse(origin).hostname in ALLOWED_HOSTS
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ALLOWED_HOSTS

    def log_message(self, format, *args):
        pass  # Konsolu her istekte doldurmasın

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/") and not self._is_local_request():
            self.send_json({"success": False, "error": "Yalnızca yerel istekler kabul edilir."}, status=403)
            return

        if path in ("/", "/index.html"):
            index_path = os.path.join(BASE_DIR, "index.html")
            if os.path.exists(index_path):
                with open(index_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, "index.html bulunamadi")
            return

        elif path == "/api/status":
            txt_files = [f for f in os.listdir(TRANSCRIPTS_DIR) if f.endswith(".txt")]
            self.send_json({
                "status": "ready",
                "output_dir": TRANSCRIPTS_DIR,
                "file_count": len(txt_files),
                "files": txt_files
            })
            return

        elif path == "/api/open-folder":
            try:
                open_in_file_manager(TRANSCRIPTS_DIR)
                self.send_json({"success": True, "message": "Klasör başarıyla açıldı."})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)
            return

        elif path == "/api/transcript":
            name = os.path.basename(parse_qs(parsed.query).get("file", [""])[0])
            text = read_transcript_file(name) if name.endswith(".txt") else None
            if text is None:
                self.send_json({"success": False, "error": "Dosya bulunamadı."}, status=404)
                return
            self.send_json({"success": True, "file": name, "text": text, "has_timestamps": has_timestamps(text)})
            return

        elif path == "/api/search":
            query = parse_qs(parsed.query).get("q", [""])[0]
            if len(query.strip()) < 2:
                self.send_json({"success": False, "error": "En az 2 karakter girin."}, status=400)
                return
            self.send_json({"success": True, **search_transcripts(query)})
            return

        elif path == "/api/download-zip":
            txt_files = [f for f in os.listdir(TRANSCRIPTS_DIR) if f.endswith(".txt")]
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for file_name in txt_files:
                    file_path = os.path.join(TRANSCRIPTS_DIR, file_name)
                    zip_file.write(file_path, arcname=file_name)
            
            zip_data = zip_buffer.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="youtube_transkriptleri.zip"')
            self.send_header("Content-Length", str(len(zip_data)))
            self.end_headers()
            self.wfile.write(zip_data)
            return

        self.send_error(404, "Sayfa bulunamadi")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._is_local_request():
            self.send_json({"success": False, "error": "Yalnızca yerel istekler kabul edilir."}, status=403)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_json({"success": False, "error": "Geçersiz JSON."}, status=400)
            return

        if path == "/api/scan":
            raw_url = payload.get("url", "").strip()
            if not raw_url:
                self.send_json({"success": False, "error": "Lütfen geçerli bir YouTube URL veya kanal adı girin."}, status=400)
                return

            ydl_opts = {
                "extract_flat": True,
                "quiet": True,
                "no_warnings": True,
                "ignoreerrors": True,
            }

            try:
                # 1. Tek video kontrolü (watch?v=, youtu.be/...)
                if "watch?v=" in raw_url or "youtu.be/" in raw_url:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(raw_url, download=False)
                    raw_entries = [info] if info else []
                    channel_title = (info.get("uploader") or info.get("title") or "Tek Video") if info else "Video"

                # 2. Oynatma Listesi kontrolü
                elif "playlist?list=" in raw_url:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(raw_url, download=False)
                    raw_entries = info.get("entries", []) if info else []
                    channel_title = info.get("title") or "Oynatma Listesi"

                # 3. Kanal Tarama (Kullanıcı @kanal, kanal URL'si girdiğinde /videos, /streams, /shorts hepsi taranır!)
                else:
                    if raw_url.startswith("@"):
                        channel_base = f"https://www.youtube.com/{raw_url}".rstrip("/")
                    elif not raw_url.startswith("http://") and not raw_url.startswith("https://"):
                        channel_base = f"https://www.youtube.com/@{raw_url}".rstrip("/")
                    else:
                        # Eğer kullanıcı doğrudan /videos veya /streams girdiyse tab kısmını kaldırıp ana kanala ulaş
                        channel_base = re.sub(r'/(videos|streams|shorts|featured)$', '', raw_url.rstrip("/"))

                    # Kanal başlığını ve tüm sekmeleri eşzamanlı çek
                    tabs = ["/videos", "/streams", "/shorts"]
                    raw_entries = []
                    seen_ids = set()
                    channel_title = ""

                    def scan_tab(tab_suffix):
                        tab_url = channel_base + tab_suffix
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            try:
                                return ydl.extract_info(tab_url, download=False)
                            except Exception:
                                return None

                    with ThreadPoolExecutor(max_workers=3) as executor:
                        tab_results = list(executor.map(scan_tab, tabs))

                    for res in tab_results:
                        if res:
                            if not channel_title and res.get("title"):
                                # "Kemalpaşa Belediyesi - Videos" -> "Kemalpaşa Belediyesi"
                                channel_title = re.sub(r'\s*-\s*(Videos|Canlı|Streams|Shorts).*$', '', res.get("title")).strip()
                            for e in res.get("entries", []) or []:
                                if e and e.get("id") and e.get("id") not in seen_ids:
                                    seen_ids.add(e.get("id"))
                                    raw_entries.append(e)

                    if not channel_title:
                        channel_title = channel_base.split("/")[-1]

                if not raw_entries:
                    self.send_json({"success": False, "error": "Bu bağlantıda hiç video bulunamadı. Lütfen URL'yi kontrol edin."}, status=404)
                    return

                videos = []
                idx = 1
                for item in raw_entries:
                    vid_id = item.get("id")
                    if not vid_id:
                        continue
                    
                    title = item.get("title") or f"Video {vid_id}"
                    duration = format_duration(item.get("duration"))
                    thumbnail = item.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"
                    link = f"https://www.youtube.com/watch?v={vid_id}"
                    
                    safe_title = sanitize_filename(title)
                    existing_file = find_existing_file(vid_id, safe_title)

                    videos.append({
                        "sira": idx,
                        "id": vid_id,
                        "title": title,
                        "duration": duration,
                        "thumbnail": thumbnail,
                        "link": link,
                        "cached": existing_file is not None,
                        "filename": existing_file,
                        "status": "cached" if existing_file else "pending"
                    })
                    idx += 1

                self.send_json({
                    "success": True,
                    "channel_title": channel_title,
                    "count": len(videos),
                    "videos": videos
                })
            except Exception as e:
                self.send_json({"success": False, "error": f"Tarama hatası: {str(e)}"}, status=500)
            return

        elif path == "/api/clear-transcripts":
            count = 0
            if os.path.exists(TRANSCRIPTS_DIR):
                for f in os.listdir(TRANSCRIPTS_DIR):
                    if f.endswith(".txt"):
                        try:
                            os.remove(os.path.join(TRANSCRIPTS_DIR, f))
                            count += 1
                        except OSError:
                            pass
            self.send_json({"success": True, "deleted_count": count})
            return

        elif path == "/api/download-single":
            video_id = payload.get("id")
            title = payload.get("title", "Video")
            raw_langs = payload.get("langs", "tr,en")
            with_timestamps = payload.get("timestamps", True)
            force_reload = bool(payload.get("force", False))

            if not video_id:
                self.send_json({"success": False, "error": "Video ID eksik"}, status=400)
                return

            safe_title = sanitize_filename(title)
            final_txt_path = os.path.join(TRANSCRIPTS_DIR, build_filename(video_id, title))

            existing = get_existing_transcript(video_id, safe_title)
            if existing and not force_reload:
                cached_text = existing[1]
                has_ts = has_timestamps(cached_text)
                if has_ts == bool(with_timestamps):
                    self.send_json({
                        "success": True,
                        "id": video_id,
                        "cached": True,
                        "title": title,
                        "text": cached_text,
                        "text_timestamped": cached_text if has_ts else "",
                        "text_clean": cached_text if not has_ts else "",
                        "file": existing[0]
                    })
                    return

            lang_list = [l.strip() for l in raw_langs.split(",") if l.strip()]
            if not lang_list:
                lang_list = ["tr", "en"]

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            ydl_opts_sub = {"skip_download": True, "quiet": True, "no_warnings": True}
            try:
                with yt_dlp.YoutubeDL(ydl_opts_sub) as ydl:
                    info = ydl.extract_info(video_url, download=False) or {}
                    picked = pick_subtitle(info, lang_list)
                    raw_vtt = None
                    if picked:
                        found_lang, sub_url, sub_source = picked
                        raw_vtt = ydl.urlopen(sub_url).read().decode("utf-8", errors="replace")
            except Exception as e:
                self.send_json({
                    "success": False,
                    "id": video_id,
                    "title": title,
                    "error": f"Video bilgisi alınamadı: {str(e)[:300]}"
                })
                return

            if not picked or not raw_vtt:
                self.send_json({
                    "success": False,
                    "id": video_id,
                    "title": title,
                    "error": f"Bu videoda seçilen dillerde ({', '.join(lang_list)}) altyazı veya transkript bulunamadı."
                })
                return

            formatted_ts, formatted_clean = process_vtt(raw_vtt)
            if not formatted_ts and not formatted_clean:
                self.send_json({
                    "success": False,
                    "id": video_id,
                    "title": title,
                    "error": "Altyazı dosyası indirildi ancak metin içeriği boş."
                })
                return

            header = (
                f"Video Başlığı: {title}\n"
                f"Video Linki: {video_url}\n"
                f"Altyazı Dili: {found_lang.upper()} ({sub_source})\n"
                + ("=" * 60) + "\n\n"
            )
            
            full_ts = header + formatted_ts
            full_clean = header + formatted_clean
            primary_text = full_ts if with_timestamps else full_clean

            # Aynı videonun eski formattaki ('001_Başlık.txt') dosyasını temizle
            if existing and existing[0] != os.path.basename(final_txt_path):
                try:
                    os.remove(os.path.join(TRANSCRIPTS_DIR, existing[0]))
                except OSError:
                    pass

            with open(final_txt_path, "w", encoding="utf-8") as tf:
                tf.write(primary_text)

            self.send_json({
                "success": True,
                "id": video_id,
                "cached": False,
                "title": title,
                "lang": found_lang,
                "source": sub_source,
                "text": primary_text,
                "text_timestamped": full_ts,
                "text_clean": full_clean,
                "file": os.path.basename(final_txt_path)
            })
            return

        self.send_error(404, "Endpoint bulunamadi")

def run():
    server = None
    selected_port = PORT
    for p in range(PORT, PORT + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), TranscriptServer)
            selected_port = p
            break
        except OSError:
            continue

    if not server:
        print("Uygun port bulunamadi!")
        return

    print(f"=====================================================")
    print(f" YouTube Transkript Sunucusu Baslatildi!")
    print(f" Adres: http://localhost:{selected_port}")
    print(f" Klasor: {TRANSCRIPTS_DIR}")
    print(f"=====================================================")

    def open_browser():
        webbrowser.open(f"http://localhost:{selected_port}")
    threading.Timer(0.7, open_browser).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSunucu durduruldu.")

if __name__ == "__main__":
    run()
