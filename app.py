import os
import sys
import json
import re
import io
import zipfile
import webbrowser
import threading
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
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

def get_existing_transcript(video_id: str, safe_title: str) -> tuple[str, str] | None:
    for f in os.listdir(TRANSCRIPTS_DIR):
        if not f.endswith(".txt"):
            continue
        if video_id in f or (safe_title and safe_title in f):
            file_path = os.path.join(TRANSCRIPTS_DIR, f)
            try:
                with open(file_path, "r", encoding="utf-8") as tf:
                    return f, tf.read()
            except Exception:
                pass
    return None

class TranscriptServer(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

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
                os.startfile(TRANSCRIPTS_DIR)
                self.send_json({"success": True, "message": "Klasör başarıyla açıldı."})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)
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

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        payload = json.loads(body) if body else {}

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
                    existing = get_existing_transcript(vid_id, safe_title)

                    videos.append({
                        "sira": idx,
                        "id": vid_id,
                        "title": title,
                        "duration": duration,
                        "thumbnail": thumbnail,
                        "link": link,
                        "cached": existing is not None,
                        "filename": existing[0] if existing else None,
                        "transcript": existing[1] if existing else None,
                        "status": "success" if existing else "pending"
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

        elif path == "/api/download-single":
            video_id = payload.get("id")
            title = payload.get("title", "Video")
            sira = payload.get("sira", 1)
            raw_langs = payload.get("langs", "tr,en")
            with_timestamps = payload.get("timestamps", True)
            force_reload = bool(payload.get("force", False))

            if not video_id:
                self.send_json({"success": False, "error": "Video ID eksik"}, status=400)
                return

            safe_title = sanitize_filename(title)
            base_filename = f"{sira:03d}_{safe_title}"
            final_txt_path = os.path.join(TRANSCRIPTS_DIR, f"{base_filename}.txt")

            existing = get_existing_transcript(video_id, safe_title)
            if existing and not force_reload:
                cached_text = existing[1]
                has_ts = "[" in cached_text and "]" in cached_text and ("00:" in cached_text or "01:" in cached_text)
                if not (with_timestamps and not has_ts):
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
            downloaded_vtt_path = None
            found_lang = None

            for lang in lang_list:
                temp_tmpl = os.path.join(TRANSCRIPTS_DIR, f"temp_{video_id}_{lang}.%(ext)s")
                ydl_opts_sub = {
                    "skip_download": True,
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": [lang],
                    "subtitlesformat": "vtt",
                    "outtmpl": temp_tmpl,
                    "quiet": True,
                    "no_warnings": True,
                    "ignoreerrors": True,
                }
                try:
                    with yt_dlp.YoutubeDL(ydl_opts_sub) as ydl:
                        ydl.download([video_url])
                except Exception:
                    pass

                for f in os.listdir(TRANSCRIPTS_DIR):
                    if f.startswith(f"temp_{video_id}_{lang}") and f.endswith(".vtt"):
                        downloaded_vtt_path = os.path.join(TRANSCRIPTS_DIR, f)
                        found_lang = lang
                        break

                if downloaded_vtt_path:
                    break

            if not downloaded_vtt_path:
                self.send_json({
                    "success": False,
                    "id": video_id,
                    "title": title,
                    "error": f"Bu videoda seçilen dillerde ({', '.join(lang_list)}) altyazı veya transkript bulunamadı."
                })
                return

            try:
                with open(downloaded_vtt_path, "r", encoding="utf-8", errors="replace") as vf:
                    raw_vtt = vf.read()
            finally:
                try:
                    os.remove(downloaded_vtt_path)
                except OSError:
                    pass

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
                f"Altyazı Dili: {found_lang.upper()}\n"
                + ("=" * 60) + "\n\n"
            )
            
            full_ts = header + formatted_ts
            full_clean = header + formatted_clean
            primary_text = full_ts if with_timestamps else full_clean

            with open(final_txt_path, "w", encoding="utf-8") as tf:
                tf.write(primary_text)

            self.send_json({
                "success": True,
                "id": video_id,
                "cached": False,
                "title": title,
                "lang": found_lang,
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
            server = HTTPServer(("127.0.0.1", p), TranscriptServer)
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
