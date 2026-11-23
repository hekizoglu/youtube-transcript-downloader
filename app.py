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
from collections import Counter
from difflib import SequenceMatcher
import yt_dlp

PORT = 5500
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transkriptler")
CLIPS_DIR = os.path.join(BASE_DIR, "kesitler")
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

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


def get_channel_dir(channel_name: str | None = None) -> str:
    """Kanal ismine özel klasör yolunu döner ve oluşturur."""
    name = sanitize_filename(channel_name or "").strip()
    if not name:
        name = "Genel"
    target = os.path.join(TRANSCRIPTS_DIR, name)
    os.makedirs(target, exist_ok=True)
    return target


def get_clips_channel_dir(channel_name: str | None = None) -> str:
    """Kesit videoları için kanal klasörünü döner ve oluşturur."""
    name = sanitize_filename(channel_name or "").strip()
    if not name:
        name = "Genel"
    target = os.path.join(CLIPS_DIR, name)
    os.makedirs(target, exist_ok=True)
    return target


def parse_timestamp_to_seconds(ts_str: str) -> int:
    """'01:14:15' veya '14:15' gibi zaman damgalarını saniyeye çevirir."""
    if not ts_str:
        return 0
    parts = ts_str.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(float(parts[1]))
        elif len(parts) == 1:
            return int(float(parts[0]))
    except Exception:
        pass
    return 0


def seconds_to_timestamp(secs: int) -> str:
    """Saniyeyi '01:14:15' veya '14:15' formatına çevirir."""
    secs = max(0, int(secs))
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def download_video_clip_segment(video_url: str, start_sec: int, end_sec: int, channel_name: str, video_title: str) -> dict:
    """
    Belirli zaman aralığındaki kesiti en yüksek kalitede indirip MP4 formatında kaydeder.
    Tam videoyu indirmez; HTTP Range ile sadece istenen saniyeleri çeker.
    """
    from yt_dlp.utils import download_range_func

    channel_dir = get_clips_channel_dir(channel_name)
    start_ts_str = seconds_to_timestamp(start_sec).replace(":", "-")
    end_ts_str = seconds_to_timestamp(end_sec).replace(":", "-")
    safe_title = sanitize_filename(video_title)
    
    out_tmpl = os.path.join(channel_dir, f"{safe_title} [{start_ts_str}_{end_ts_str}].%(ext)s")
    expected_filename = f"{safe_title} [{start_ts_str}_{end_ts_str}].mp4"
    final_file_path = os.path.join(channel_dir, expected_filename)

    # Zaten daha önce indirilmişse doğrudan dön
    if os.path.exists(final_file_path) and os.path.getsize(final_file_path) > 1024:
        return {
            "success": True,
            "cached": True,
            "filename": expected_filename,
            "relative_path": os.path.relpath(final_file_path, BASE_DIR).replace("\\", "/"),
            "full_path": final_file_path,
            "duration": end_sec - start_sec,
            "size_bytes": os.path.getsize(final_file_path)
        }

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": out_tmpl,
        "download_ranges": download_range_func(None, [(start_sec, end_sec)]),
        "force_keyframes_at_cuts": True,
        "js_runtimes": {"node": {}},
        "extractor_args": {"youtube": {"player_client": ["mweb", "android", "ios"]}},
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    # Çıkan dosyayı doğrula
    if not os.path.exists(final_file_path):
        # Farklı uzantıda kalmış mı kontrol et
        base_no_ext = os.path.splitext(final_file_path)[0]
        found = False
        for ext in (".mp4", ".mkv", ".webm"):
            candidate = base_no_ext + ext
            if os.path.exists(candidate):
                final_file_path = candidate
                expected_filename = os.path.basename(candidate)
                found = True
                break
        if not found:
            raise FileNotFoundError("Kesit videosu indirilemedi veya kaydedilemedi.")

    return {
        "success": True,
        "cached": False,
        "filename": expected_filename,
        "relative_path": os.path.relpath(final_file_path, BASE_DIR).replace("\\", "/"),
        "full_path": final_file_path,
        "duration": end_sec - start_sec,
        "size_bytes": os.path.getsize(final_file_path)
    }


def find_existing_file(video_id: str, channel_name: str | None = None) -> str | None:
    """Yalnızca benzersiz video ID etiketi ile ([video_id]) tam eşleşme arar.
    Önce ilgili kanal klasörüne bakar, ardından tüm alt klasörleri ve kök klasörü tarar.
    Dönüş: TRANSCRIPTS_DIR'e göre bağıl yol (örn: 'Kemalpaşa Belediyesi/Başlık [ID].txt')
    """
    if not os.path.exists(TRANSCRIPTS_DIR):
        return None
    tag = f"[{video_id}]"

    # 1. Öncelik: Belirtilen kanal klasörü
    if channel_name:
        ch_dir = get_channel_dir(channel_name)
        if os.path.exists(ch_dir):
            for f in os.listdir(ch_dir):
                if f.endswith(".txt") and tag in f:
                    return f"{os.path.basename(ch_dir)}/{f}"

    # 2. Genel arama: Tüm alt klasörler ve kök klasör
    for root, dirs, files in os.walk(TRANSCRIPTS_DIR):
        for f in files:
            if f.endswith(".txt") and tag in f:
                rel = os.path.relpath(os.path.join(root, f), TRANSCRIPTS_DIR).replace("\\", "/")
                return rel
    return None


def read_transcript_file(rel_path: str) -> str | None:
    try:
        if os.path.isabs(rel_path):
            full_path = rel_path
        else:
            full_path = os.path.join(TRANSCRIPTS_DIR, rel_path.replace("/", os.sep))
        with open(full_path, "r", encoding="utf-8") as tf:
            return tf.read()
    except OSError:
        return None


def get_existing_transcript(video_id: str, channel_name: str | None = None) -> tuple[str, str] | None:
    f = find_existing_file(video_id, channel_name)
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
    s = s.replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def ts_to_seconds(ts: str) -> int:
    total = 0
    for part in ts.split(":"):
        total = total * 60 + int(part)
    return total


def fuzzy_word_similarity(query_term: str, target_word: str) -> float:
    """Sıfır LLM / API maliyetiyle yerel benzerlik puanı (0.0 - 1.0).
    Örn: 'armutli' -> 'armutlu' (%92), 'armutlunun' (%92)."""
    if query_term == target_word:
        return 1.0
    if not query_term or not target_word:
        return 0.0
    if abs(len(query_term) - len(target_word)) > 6:
        return 0.0

    first_bonus = 0.06 if query_term[0] == target_word[0] else -0.12

    best = SequenceMatcher(None, query_term, target_word).ratio()
    if len(target_word) >= len(query_term):
        prefix = target_word[:len(query_term)]
        p_ratio = SequenceMatcher(None, query_term, prefix).ratio()
        best = max(best, p_ratio)

    return min(1.0, max(0.0, best + first_bonus))


def line_fuzzy_search(terms: list[str], line_norm: str, threshold: float = 0.78) -> tuple[bool, dict[str, dict]]:
    """Satır içerisinde aranan terimlerin her biri için benzerlik denetimi yapar."""
    words = re.findall(r'[a-z0-9]+', line_norm)
    if not words:
        return False, {}

    matched_details = {}
    for term in terms:
        best_word = None
        best_score = 0.0
        for w in words:
            score = fuzzy_word_similarity(term, w)
            if score > best_score:
                best_score = score
                best_word = w
        if best_score >= threshold:
            matched_details[term] = {"matched": best_word, "score": round(best_score, 2)}
        else:
            return False, {}

    return True, matched_details


STOPWORDS = {
    've', 'ile', 'bir', 'bu', 'su', 'o', 'icin', 'gibi', 'kadar', 'olan', 'olarak', 'sayin', 'baskanim',
    'degerli', 'arkadaslar', 'tesekkur', 'ederim', 'evet', 'hayir', 'kabul', 'edilenler', 'edilmeyenler',
    'oy', 'birligiyle', 'cokluguyla', 'madde', 'maddesi', 'gundem', 'yok', 'var', 'daha', 'cok', 'ben',
    'biz', 'sen', 'siz', 'onlar', 'tarafindan', 'seklinde', 'ancak', 'cunku', 'boyle', 'soyle', 'simdi',
    'sonra', 'once', 'uzere', 'dolayi', 'yani', 'diye', 'bunu', 'bunun', 'buna', 'burada', 'surada',
    'orada', 'seyi', 'seyler', 'gerek', 'lazim', 'konuda', 'konusunda', 'iliskin', 'yonelik', 'ilgili',
    'hakkinda', 'ayrica', 'zaten', 'tabii', 'zaman', 'birlikte', 'hepsi', 'kendi', 'kendisi', 'hic',
    'hicbir', 'biri', 'birisi', 'bazi', 'tum', 'butun', 'gore', 'karsi', 'dogru', 'sonucunda', 'yapilan',
    'yapilmasi', 'edilen', 'edilmesi', 'oldugu', 'oldugunu', 'olmasi', 'etmek', 'etmesi', 'olmak',
    'gelen', 'gelmesi', 'veren', 'vermesi', 'alan', 'almasi', 'demek', 'dedi', 'dedim', 'derim',
    'diyor', 'diyoruz', 'baktigimizda', 'soyledi', 'soyluyorum', 'arkadasimiz', 'uyemiz', 'meclisimiz',
    'komisyonumuz', 'oturum', 'birlesim', 'toplanti', 'toplantisi', 'baskan', 'meclis', 'karar',
    'belediye', 'belediyesi', 'kemalpasa', 'chp', 'ak', 'parti', 'mhp', 'iyi', 'grup', 'sozcusu',
    'efendim', 'lutfen', 'tamam', 'peki', 'olur', 'olmaz', 'yoktur', 'vardir', 'de', 'da', 'ki', 'mi', 'mu',
    'eee', 'sey', 'iste', 'bey', 'edenler', 'etmeyenler', 'sunuyorum', 'oylariniza', 'edilmistir',
    'gercekten', 'ediyorum', 'bizim', 'degil', 'onu', 'istiyorum', 'tane', 'ayni', 'biraz', 'bize',
    'bana', 'onun', 'onlarin', 'bizler', 'sizler', 'nasil', 'nicin', 'neden', 'hangi', 'her', 'herkes',
    'baska', 'bununla', 'bunda', 'bundan', 'ondan', 'onlar', 'sunlar', 'bunlar', 'kendi', 'kendine',
    'bizleri', 'sizleri', 'yine', 'hala', 'bile', 'dahi', 'ise', 'eger', 'yada', 'veya', 'yahut',
    'madem', 'oysa', 'halbuki', 'belki', 'sanki', 'keske', 'insallah', 'bari', 'neyse', 'ama',
    'sekilde', 'gecen', 'buyurun', 'sadece', 'olsun', 'oyle', 'diger', 'iki', 'gun', 'sizin', 'benim',
    'bunu', 'sunu', 'biri', 'hemen', 'fazla', 'az', 'kendi', 'onlari', 'bunlari', 'bize', 'size',
    'benden', 'senden', 'ondan', 'bizden', 'sizden', 'onlardan', 'dolayisiyla', 'zamanda', 'iste',
    'boylece', 'buradaki', 'oradaki', 'buraya', 'oraya', 'nerede', 'nereden', 'nereye'
}


def search_transcripts(query: str, max_results: int | None = None, fuzzy: bool = False, threshold: float = 0.78, channel: str | None = None) -> dict:
    q = normalize_text(query.strip())
    if not q:
        return {"query": query, "fuzzy": fuzzy, "threshold": threshold, "total_hits": 0, "files": [], "truncated": False}
    terms = q.split()
    results = []
    total = 0
    truncated = False

    target_dir = os.path.join(TRANSCRIPTS_DIR, sanitize_filename(channel)) if channel else TRANSCRIPTS_DIR

    txt_files = []
    if os.path.exists(target_dir):
        for root, dirs, files in os.walk(target_dir):
            for f in files:
                if f.endswith(".txt"):
                    rel = os.path.relpath(os.path.join(root, f), TRANSCRIPTS_DIR).replace("\\", "/")
                    txt_files.append((rel, os.path.join(root, f)))

    txt_files.sort(key=lambda x: x[0])

    for rel_path, full_path in txt_files:
        text = read_transcript_file(full_path)
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

            matched_terms = {}
            if fuzzy:
                is_match, matched_terms = line_fuzzy_search(terms, norm, threshold)
                if not is_match:
                    continue
            else:
                if not all(t in norm for t in terms):
                    continue

            m = TS_LINE_RE.match(line)
            ts = m.group(1) if m else None
            snippet = m.group(2) if m else line
            if not m and len(snippet) > 300:
                focus_word = terms[0]
                if fuzzy and focus_word in matched_terms:
                    focus_word = matched_terms[focus_word]["matched"]
                idx = norm.find(focus_word)
                if idx == -1: idx = 0
                start = max(0, idx - 120)
                snippet = ("…" if start else "") + snippet[start:start + 260] + "…"

            hit = {"timestamp": ts, "text": snippet}
            if fuzzy and matched_terms:
                hit["fuzzy_matches"] = matched_terms
            if link and ts:
                hit["url"] = f"{link}&t={ts_to_seconds(ts)}s"
            hits.append(hit)
            total += 1
            if max_results and total >= max_results:
                truncated = True
                break

        if hits:
            channel_name = os.path.dirname(rel_path) or "Genel"
            results.append({
                "file": rel_path,
                "channel": channel_name,
                "title": title_m.group(1).strip() if title_m else os.path.basename(rel_path)[:-4],
                "link": link,
                "hits": hits,
            })
        if truncated:
            break

    return {
        "query": query,
        "fuzzy": fuzzy,
        "threshold": threshold,
        "total_hits": total,
        "files": results,
        "truncated": truncated
    }


def extract_word_pool(channel_name: str | None = None, top_n: int = 0) -> dict:
    counts = Counter()
    display_map = {}

    target_dir = os.path.join(TRANSCRIPTS_DIR, sanitize_filename(channel_name)) if channel_name else TRANSCRIPTS_DIR

    total_words = 0
    if os.path.exists(target_dir):
        for root, dirs, files in os.walk(target_dir):
            for f in files:
                if f.endswith(".txt"):
                    text = read_transcript_file(os.path.join(root, f))
                    if not text:
                        continue
                    body = text.split("=" * 60, 1)[-1]
                    tokens = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]{3,}", body)
                    for tok in tokens:
                        total_words += 1
                        n = normalize_text(tok)
                        if len(n) >= 3 and n not in STOPWORDS and not n.isdigit():
                            counts[n] += 1
                            if n not in display_map:
                                display_map[n] = tok.capitalize()

    words_list = []
    # top_n > 0 ise sınırlı, 0 veya None ise en az 2 kez geçen tüm anlamlı kelimeleri al
    most_common_items = counts.most_common(top_n) if (top_n and top_n > 0) else [item for item in counts.most_common() if item[1] >= 2]
    max_count = max(counts.values()) if counts else 1
    for word_norm, cnt in most_common_items:
        weight = max(1, min(10, int((cnt / max_count) * 10)))
        words_list.append({
            "text": display_map.get(word_norm, word_norm.capitalize()),
            "norm": word_norm,
            "count": cnt,
            "weight": weight
        })

    return {
        "success": True,
        "channel": channel_name or "Tüm Kanallar",
        "total_words": total_words,
        "unique_keywords": len(counts),
        "words": words_list
    }


def open_in_file_manager(path: str):
    norm = os.path.normpath(os.path.abspath(path))
    if sys.platform.startswith("win"):
        try:
            # 1. Windows Gezgini'ni doğrudan klasör yoluyla başlat
            subprocess.Popen(f'explorer.exe "{norm}"', shell=True)
        except Exception:
            try:
                os.startfile(norm)
            except Exception:
                pass
    elif sys.platform == "darwin":
        subprocess.Popen(["open", norm])
    else:
        subprocess.Popen(["xdg-open", norm])


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
            txt_files = []
            for root, dirs, files in os.walk(TRANSCRIPTS_DIR):
                for f in files:
                    if f.endswith(".txt"):
                        rel = os.path.relpath(os.path.join(root, f), TRANSCRIPTS_DIR).replace("\\", "/")
                        txt_files.append(rel)
            self.send_json({
                "status": "ready",
                "output_dir": TRANSCRIPTS_DIR,
                "file_count": len(txt_files),
                "files": txt_files
            })
            return

        elif path == "/api/open-folder":
            try:
                channel = parse_qs(parsed.query).get("channel", [""])[0]
                if channel:
                    target_dir = get_channel_dir(channel)
                else:
                    target_dir = TRANSCRIPTS_DIR
                norm_dir = os.path.normpath(os.path.abspath(target_dir))
                open_in_file_manager(norm_dir)
                txt_count = 0
                for root, dirs, files in os.walk(norm_dir):
                    txt_count += len([f for f in files if f.endswith(".txt")])
                self.send_json({
                    "success": True,
                    "message": "Klasör açma komutu çalıştırıldı.",
                    "path": norm_dir,
                    "channel": channel or "Tüm Kanallar",
                    "count": txt_count
                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)
            return

        elif path == "/api/transcript":
            raw_file = parse_qs(parsed.query).get("file", [""])[0].strip()
            # Yol güvenlik kontrolü: TRANSCRIPTS_DIR dışına çıkışları engelle
            clean_rel = os.path.normpath(raw_file).replace("\\", "/").lstrip("/")
            if clean_rel.startswith("../") or "/../" in clean_rel:
                self.send_json({"success": False, "error": "Geçersiz dosya yolu."}, status=400)
                return
            text = read_transcript_file(clean_rel) if clean_rel.endswith(".txt") else None
            if text is None:
                self.send_json({"success": False, "error": "Dosya bulunamadı."}, status=404)
                return
            self.send_json({"success": True, "file": clean_rel, "text": text, "has_timestamps": has_timestamps(text)})
            return

        elif path == "/api/search":
            query = parse_qs(parsed.query).get("q", [""])[0]
            fuzzy = parse_qs(parsed.query).get("fuzzy", ["0"])[0].lower() in ("1", "true", "yes")
            try:
                threshold = float(parse_qs(parsed.query).get("threshold", ["0.78"])[0])
            except ValueError:
                threshold = 0.78
            channel = parse_qs(parsed.query).get("channel", [""])[0]
            raw_limit = parse_qs(parsed.query).get("limit", ["0"])[0]
            try:
                max_results = int(raw_limit) if int(raw_limit) > 0 else None
            except ValueError:
                max_results = None

            if len(query.strip()) < 2:
                self.send_json({"success": False, "error": "En az 2 karakter girin."}, status=400)
                return
            self.send_json({"success": True, **search_transcripts(query, max_results=max_results, fuzzy=fuzzy, threshold=threshold, channel=channel)})
            return

        elif path == "/api/word-pool":
            channel = parse_qs(parsed.query).get("channel", [""])[0]
            raw_limit = parse_qs(parsed.query).get("limit", ["0"])[0]
            try:
                limit = int(raw_limit)
            except ValueError:
                limit = 0
            self.send_json(extract_word_pool(channel_name=channel, top_n=limit))
            return

        elif path == "/api/open-clips-folder":
            open_in_file_manager(CLIPS_DIR)
            self.send_json({"success": True, "path": CLIPS_DIR})
            return

        elif path == "/api/download-zip":
            channel = parse_qs(parsed.query).get("channel", [""])[0]
            zip_buffer = io.BytesIO()
            zip_filename = "youtube_transkriptleri.zip"
            
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                if channel:
                    ch_dir = get_channel_dir(channel)
                    safe_ch = sanitize_filename(channel)
                    zip_filename = f"{safe_ch}_transkriptler.zip"
                    for f in os.listdir(ch_dir):
                        if f.endswith(".txt"):
                            file_path = os.path.join(ch_dir, f)
                            zip_file.write(file_path, arcname=f)
                else:
                    for root, dirs, files in os.walk(TRANSCRIPTS_DIR):
                        for f in files:
                            if f.endswith(".txt"):
                                file_path = os.path.join(root, f)
                                rel = os.path.relpath(file_path, TRANSCRIPTS_DIR)
                                zip_file.write(file_path, arcname=rel)

            zip_data = zip_buffer.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{zip_filename}"')
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
                    existing_file = find_existing_file(vid_id, channel_title)

                    videos.append({
                        "sira": idx,
                        "id": vid_id,
                        "title": title,
                        "duration": duration,
                        "thumbnail": thumbnail,
                        "link": link,
                        "channel": channel_title,
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
            channel_name = payload.get("channel") or payload.get("channel_title") or "Genel"
            raw_langs = payload.get("langs", "tr,en")
            with_timestamps = payload.get("timestamps", True)
            force_reload = bool(payload.get("force", False))

            if not video_id:
                self.send_json({"success": False, "error": "Video ID eksik"}, status=400)
                return

            channel_dir = get_channel_dir(channel_name)
            filename = build_filename(video_id, title)
            final_txt_path = os.path.join(channel_dir, filename)
            rel_file_path = f"{os.path.basename(channel_dir)}/{filename}"

            existing = get_existing_transcript(video_id, channel_name)
            if existing and not force_reload:
                cached_text = existing[1]
                has_ts = has_timestamps(cached_text)
                if has_ts == bool(with_timestamps):
                    self.send_json({
                        "success": True,
                        "id": video_id,
                        "cached": True,
                        "title": title,
                        "channel": channel_name,
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

            # Eski dosya farklı bir yerde veya isimdeyse temizle
            if existing and existing[0] != rel_file_path:
                try:
                    old_path = os.path.join(TRANSCRIPTS_DIR, existing[0].replace("/", os.sep))
                    if os.path.exists(old_path) and os.path.abspath(old_path) != os.path.abspath(final_txt_path):
                        os.remove(old_path)
                except OSError:
                    pass

            with open(final_txt_path, "w", encoding="utf-8") as tf:
                tf.write(primary_text)

            self.send_json({
                "success": True,
                "id": video_id,
                "cached": False,
                "title": title,
                "channel": channel_name,
                "lang": found_lang,
                "source": sub_source,
                "text": primary_text,
                "text_timestamped": full_ts,
                "text_clean": full_clean,
                "file": rel_file_path
            })
            return

        elif path == "/api/download-clip":
            video_url = payload.get("url", "").strip()
            video_id = payload.get("id", "").strip()
            video_title = payload.get("title", "").strip() or "Video Kesiti"
            channel_name = payload.get("channel", "").strip() or "Genel"
            ts_str = payload.get("timestamp", "").strip()
            pad_before = int(payload.get("pad_before", 10))
            pad_after = int(payload.get("pad_after", 20))

            if not video_url and video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}"

            if not video_url:
                self.send_json({"success": False, "error": "Geçerli bir video URL veya ID belirtilmedi."}, status=400)
                return

            center_sec = parse_timestamp_to_seconds(ts_str)
            start_sec = max(0, center_sec - max(0, pad_before))
            end_sec = center_sec + max(5, pad_after)

            try:
                result = download_video_clip_segment(
                    video_url=video_url,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    channel_name=channel_name,
                    video_title=video_title
                )
                self.send_json({
                    "success": True,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "start_ts": seconds_to_timestamp(start_sec),
                    "end_ts": seconds_to_timestamp(end_sec),
                    "clip": result
                })
            except Exception as e:
                self.send_json({"success": False, "error": f"Kesit indirme hatası: {str(e)}"}, status=500)
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
