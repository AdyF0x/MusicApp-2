import os
import re
import sys
import time
import glob
import yt_dlp


class MusicParser:
    def __init__(self, download_folder: str = "downloads"):
        self.download_folder = download_folder
        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder, exist_ok=True)

        # Базовые опции для yt-dlp (общие)
        self._base_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            'compat_opts': ['no-js-runtimes'],
            'nocheckcertificate': True,
            'socket_timeout': 30,
            'retries': 5,
            'fragment_retries': 5,
        }

    # ------------------------------------------------------------------ #
    #                            ПОИСК                                   #
    # ------------------------------------------------------------------ #
    def search_tracks(self, query: str, limit: int = 10) -> list:
        """
        Ищет треки на YouTube.
        Возвращает список словарей:
          {title, author, webpage_url, url, duration, thumbnail}
        """
        if not query or not query.strip():
            print("Пустой поисковый запрос")
            return []

        query = query.strip()

        ydl_opts = dict(self._base_opts)
        ydl_opts.update({
            'extract_flat': True,
            'skip_download': True,
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_query = f"ytsearch{limit}:{query}"
                print(f"Поиск: {search_query}")

                info = ydl.extract_info(search_query, download=False)

                tracks = []
                if not info:
                    print("yt-dlp вернул пустой результат")
                    return []

                entries = info.get('entries') or []
                for entry in entries:
                    if not entry:
                        continue

                    # Иногда url приходит как "https://www.youtube.com/watch?v=ID"
                    webpage_url = entry.get('webpage_url') or entry.get('url') or ''
                    if not webpage_url:
                        continue

                    # Если это относительная ссылка или id — соберём полный URL
                    if webpage_url.startswith('http'):
                        full_url = webpage_url
                    elif re.fullmatch(r'[\w-]{11}', webpage_url):
                        full_url = f"https://www.youtube.com/watch?v={webpage_url}"
                    else:
                        full_url = webpage_url

                    track_data = {
                        'title': entry.get('title') or 'Unknown',
                        'author': entry.get('uploader') or entry.get('channel') or 'Unknown',
                        'webpage_url': full_url,
                        'url': entry.get('url') or full_url,
                        'duration': entry.get('duration') or 0,
                        'thumbnail': entry.get('thumbnail') or '',
                    }
                    tracks.append(track_data)
                    print(f"  • {track_data['author']} — {track_data['title']}")

                return tracks

        except Exception as e:
            print(f"Ошибка при поиске: {e}")
            return []

    # ------------------------------------------------------------------ #
    #                          СКАЧИВАНИЕ                                #
    # ------------------------------------------------------------------ #
    def _sanitize_filename(self, name: str, max_len: int = 120) -> str:
        """Убирает недопустимые символы и обрезает длину."""
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        # Windows не любит имена, заканчивающиеся на точку/пробел
        name = name.rstrip('. ')
        if len(name) > max_len:
            name = name[:max_len].rstrip('. ')
        return name or "track"

    def _find_existing_file(self, clean_title: str) -> str | None:
        """Проверяет, не скачан ли уже трек."""
        pattern = os.path.join(self.download_folder, f"{clean_title}.*")
        for path in glob.glob(pattern):
            if path.lower().endswith(('.mp3', '.m4a', '.opus', '.webm', '.wav')):
                return path
        return None

    def _safe_postprocessors(self):
        """Постпроцессоры: извлечь аудио в mp3, вписать теги."""
        return [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            },
            {
                'key': 'FFmpegMetadata',
                'add_metadata': True,
            },
        ]

    def download_track(self, track_info: dict, progress_callback=None) -> str | None:
        """
        Скачивает один трек в MP3.
        Возвращает путь к файлу или None.
        progress_callback(dict) — необязательный колбэк со статусом загрузки.
        """
        if not track_info:
            print("Нет информации о треке")
            return None

        url = track_info.get('webpage_url') or track_info.get('url')
        if not url:
            print("Нет URL для скачивания")
            return None

        title = track_info.get('title') or 'track'
        author = track_info.get('author') or 'unknown'

        clean_title = self._sanitize_filename(f"{author} - {title}")

        # Уже скачано?
        existing = self._find_existing_file(clean_title)
        if existing:
            print(f"Уже скачано: {existing}")
            return existing

        # Колбэк прогресса для yt-dlp
        def _hook(d):
            if progress_callback is None:
                return
            try:
                if d.get('status') == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes') or 0
                    percent = (downloaded / total * 100) if total else 0
                    progress_callback({
                        'status': 'downloading',
                        'percent': round(percent, 1),
                        'speed': d.get('speed') or 0,
                        'eta': d.get('eta') or 0,
                    })
                elif d.get('status') == 'finished':
                    progress_callback({'status': 'converting', 'percent': 100})
            except Exception:
                pass

        ydl_opts = dict(self._base_opts)
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': self._safe_postprocessors(),
            'outtmpl': os.path.join(self.download_folder, f'{clean_title}.%(ext)s'),
            'quiet': True,
            'no_warnings': False,
            'progress_hooks': [_hook],
            'retries': 10,
            'fragment_retries': 10,
            'concurrent_fragment_downloads': 4,
        })

        try:
            print(f"Скачивание: {clean_title}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            print(f"Ошибка при скачивании: {e}")

        # Ищем результат
        base_path = os.path.join(self.download_folder, clean_title)
        for ext in ('.mp3', '.m4a', '.opus', '.webm', '.wav'):
            filepath = base_path + ext
            if os.path.exists(filepath):
                print(f"Готово: {filepath}")
                return filepath

        # Фоллбэк — ищем по началу имени (на случай, если yt-dlp изменил имя)
        for file in os.listdir(self.download_folder):
            if file.startswith(clean_title) and file.lower().endswith(
                ('.mp3', '.m4a', '.opus', '.webm', '.wav')
            ):
                full = os.path.join(self.download_folder, file)
                print(f"Найден фоллбэк: {full}")
                return full

        print("Файл не найден после скачивания")
        return None

    # ------------------------------------------------------------------ #
    #                        СЛУЖЕБНЫЕ МЕТОДЫ                             #
    # ------------------------------------------------------------------ #
    def get_video_info(self, video_id: str) -> dict:
        """
        Получает метаданные по YouTube-ID без скачивания.
        Возвращает {title, author, duration}.
        """
        try:
            ydl_opts = dict(self._base_opts)
            ydl_opts['extract_flat'] = False

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                url = f"https://www.youtube.com/watch?v={video_id}"
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', f'Video {video_id}'),
                    'author': info.get('uploader') or info.get('channel') or 'YouTube',
                    'duration': info.get('duration') or 0,
                }
        except Exception as e:
            print(f"Ошибка получения информации о видео {video_id}: {e}")
            return {
                'title': f'Video {video_id}',
                'author': 'YouTube',
                'duration': 0,
            }

    def list_downloaded(self) -> list:
        """Возвращает список уже скачанных аудиофайлов (полные пути)."""
        if not os.path.exists(self.download_folder):
            return []
        files = []
        for f in os.listdir(self.download_folder):
            if f.lower().endswith(('.mp3', '.m4a', '.opus', '.webm', '.wav')):
                files.append(os.path.join(self.download_folder, f))
        return files

    def clear_downloads(self) -> int:
        """Удаляет все скачанные файлы. Возвращает количество удалённых."""
        deleted = 0
        if not os.path.exists(self.download_folder):
            return 0
        for f in os.listdir(self.download_folder):
            path = os.path.join(self.download_folder, f)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    deleted += 1
            except Exception as e:
                print(f"Не удалось удалить {path}: {e}")
        return deleted


# ---------------------------------------------------------------------- #
#                      МОДУЛЬНЫЕ ФУНКЦИИ (API)                            #
# ---------------------------------------------------------------------- #
_default_parser: MusicParser | None = None


def _get_parser() -> MusicParser:
    """Ленивая инициализация парсера (чтобы не создавать папку при импорте)."""
    global _default_parser
    if _default_parser is None:
        _default_parser = MusicParser()
    return _default_parser


def search_tracks(query: str, limit: int = 10) -> list:
    return _get_parser().search_tracks(query, limit)


def download_selected_track(track_info: dict, progress_callback=None) -> str | None:
    return _get_parser().download_track(track_info, progress_callback)


def get_video_info(video_id: str) -> dict:
    return _get_parser().get_video_info(video_id)


def list_downloaded() -> list:
    return _get_parser().list_downloaded()


def clear_downloads() -> int:
    return _get_parser().clear_downloads()


# ---------------------------------------------------------------------- #
#                          ТЕСТОВЫЙ ЗАПУСК                                #
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    print("=" * 60)
    print("Тест MusicParser")
    print("=" * 60)

    # Проверка зависимостей
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print("yt-dlp не установлен. Установи: pip install yt-dlp")
        sys.exit(1)

    test_query = "Imagine Dragons Believer"
    tracks = search_tracks(test_query, limit=5)

    if not tracks:
        print("Треки не найдены")
        sys.exit(1)

    print(f"\nНайдено: {len(tracks)}")
    for i, t in enumerate(tracks, 1):
        print(f"{i}. {t['author']} — {t['title']} ({t['duration']}s)")

    print("\nСкачиваем первый трек...")

    def _cb(p):
        if p['status'] == 'downloading':
            print(f"  ⏬ {p['percent']}%  (ETA {p['eta']}s)", end='\r')
        elif p['status'] == 'converting':
            print("\n  🔄 Конвертация...")

    start = time.time()
    filepath = download_selected_track(tracks[0], progress_callback=_cb)

    print()
    if filepath:
        print(f"✅ Успешно: {filepath}")
        print(f"⏱  Затрачено: {time.time() - start:.1f}s")
    else:
        print("❌ Не удалось скачать")

    print("\nСкачанные файлы:")
    for f in list_downloaded():
        print("  •", f)