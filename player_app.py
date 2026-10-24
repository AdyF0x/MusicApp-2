import sys
import os
import threading
import re
import json
import keyboard

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QListWidget, QLabel, QSlider,
    QCheckBox, QMessageBox, QGroupBox
)
from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtGui import QFont, QShortcut, QKeySequence

from music_parser import (
    search_tracks,
    download_selected_track,
    get_video_info,
)


class MusicPlayerApp(QMainWindow):

    progress_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(70)

        self.current_track_path = None
        self.current_playlist_index = -1
        self.is_playing = False
        self.is_repeat = False
        self.playlist = []
        self.track_names = []
        self.current_tracks = []

        # Состояние трансляции
        self.mic_broadcast_enabled = False
        self.mic_volume = 80

        self.init_ui()
        self.setup_global_hotkeys()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_position)
        self.timer.start(1000)

        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.progress_signal.connect(self.on_download_progress)

        self.load_playlist_state()

    def setup_global_hotkeys(self):
        """Глобальные горячие клавиши (работают в свернутом окне)"""
        try:
            keyboard.add_hotkey('F6', lambda: self.toggle_play())
            keyboard.add_hotkey('F5', lambda: self.play_previous_track())
            keyboard.add_hotkey('F7', lambda: self.play_next_track())
        except Exception as e:
            print(f"Ошибка установки глобальных клавиш: {e}")

    # ------------------------------------------------------------------ #
    #                              UI                                    #
    # ------------------------------------------------------------------ #
    def init_ui(self):
        self.setWindowTitle("Музыкальный Плеер")
        self.setGeometry(300, 150, 600, 800)
        self.setMinimumSize(450, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # ---------------- Поиск ----------------
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите исполнителя, название или ссылку на YouTube...")
        self.search_input.setFont(QFont("Arial", 11))
        self.search_input.returnPressed.connect(self.search_tracks)
        search_layout.addWidget(self.search_input)

        self.search_button = QPushButton("Найти")
        self.search_button.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.search_button.setFixedHeight(35)
        self.search_button.clicked.connect(self.search_tracks)
        search_layout.addWidget(self.search_button)
        main_layout.addLayout(search_layout)

        self.search_results_label = QLabel("Результаты поиска (двойной клик для скачивания):")
        self.search_results_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        main_layout.addWidget(self.search_results_label)

        self.results_widget = QListWidget()
        self.results_widget.setFont(QFont("Arial", 10))
        self.results_widget.itemDoubleClicked.connect(self.download_selected)
        self.results_widget.setStyleSheet("""
            QListWidget { border: 1px solid #ccc; border-radius: 5px; padding: 5px; min-height: 100px; }
            QListWidget::item { padding: 8px; }
            QListWidget::item:selected { background-color: #2196F3; color: white; }
        """)
        main_layout.addWidget(self.results_widget)

        # ---------------- Текущий трек ----------------
        self.current_track_label = QLabel("Нет трека")
        self.current_track_label.setFont(QFont("Arial", 12))
        self.current_track_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_track_label.setStyleSheet("background-color: #f0f0f0; padding: 10px; border-radius: 5px;")
        main_layout.addWidget(self.current_track_label)

        # ---------------- Плейлист ----------------
        playlist_label = QLabel("Плейлист (двойной клик для воспроизведения):")
        playlist_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        main_layout.addWidget(playlist_label)

        self.playlist_widget = QListWidget()
        self.playlist_widget.setFont(QFont("Arial", 10))
        self.playlist_widget.itemDoubleClicked.connect(self.play_selected_track)
        self.playlist_widget.setStyleSheet("""
            QListWidget { border: 1px solid #ccc; border-radius: 5px; padding: 5px; max-height: 140px; }
            QListWidget::item { padding: 8px; }
            QListWidget::item:selected { background-color: #4CAF50; color: white; }
        """)
        main_layout.addWidget(self.playlist_widget)

        # ---------------- Кнопки управления ----------------
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)

        self.play_button = QPushButton("▶ Воспроизвести (F6)")
        self.play_button.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.play_button.setFixedHeight(40)
        self.play_button.clicked.connect(self.toggle_play)
        controls_layout.addWidget(self.play_button)

        self.stop_button = QPushButton("⏹ Стоп")
        self.stop_button.setFont(QFont("Arial", 10))
        self.stop_button.setFixedHeight(40)
        self.stop_button.clicked.connect(self.stop_playback)
        controls_layout.addWidget(self.stop_button)

        self.prev_button = QPushButton("⏮ Назад (F5)")
        self.prev_button.setFont(QFont("Arial", 10))
        self.prev_button.setFixedHeight(40)
        self.prev_button.clicked.connect(self.play_previous_track)
        controls_layout.addWidget(self.prev_button)

        self.next_button = QPushButton("Вперёд (F7) ⏭")
        self.next_button.setFont(QFont("Arial", 10))
        self.next_button.setFixedHeight(40)
        self.next_button.clicked.connect(self.play_next_track)
        controls_layout.addWidget(self.next_button)

        main_layout.addLayout(controls_layout)

        # ---------------- Настройки ----------------
        settings_layout = QHBoxLayout()
        self.repeat_checkbox = QCheckBox("🔁 Повтор")
        self.repeat_checkbox.setFont(QFont("Arial", 10))
        self.repeat_checkbox.stateChanged.connect(self.toggle_repeat)
        settings_layout.addWidget(self.repeat_checkbox)

        self.clear_button = QPushButton("🗑 Очистить список")
        self.clear_button.setFont(QFont("Arial", 10))
        self.clear_button.setFixedHeight(30)
        self.clear_button.clicked.connect(self.clear_playlist)
        settings_layout.addWidget(self.clear_button)

        self.clear_all_button = QPushButton("🗑 Очистить всё (и файлы)")
        self.clear_all_button.setFont(QFont("Arial", 10))
        self.clear_all_button.setFixedHeight(30)
        self.clear_all_button.setStyleSheet("QPushButton { color: red; }")
        self.clear_all_button.clicked.connect(self.clear_all)
        settings_layout.addWidget(self.clear_all_button)

        settings_layout.addStretch()
        main_layout.addLayout(settings_layout)

        # ---------------- НАСТРОЙКИ ЗВУКА ----------------
        audio_group = QGroupBox("🎚 Настройки звука")
        audio_group.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        audio_layout = QVBoxLayout(audio_group)

        # 1. Громкость плеера
        music_row = QHBoxLayout()
        music_row.addWidget(QLabel("🎵 Музыка:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.valueChanged.connect(self.change_volume)
        music_row.addWidget(self.volume_slider)
        self.volume_label = QLabel("70%")
        self.volume_label.setFixedWidth(45)
        music_row.addWidget(self.volume_label)
        audio_layout.addLayout(music_row)

        # 2. Трансляция в микрофон (чтобы слышали другие)
        broadcast_row = QHBoxLayout()
        self.mic_broadcast_checkbox = QCheckBox("🎤 Микрофон (трансляция музыки другим)")
        self.mic_broadcast_checkbox.setFont(QFont("Arial", 10))
        self.mic_broadcast_checkbox.stateChanged.connect(self.toggle_mic_broadcast)
        broadcast_row.addWidget(self.mic_broadcast_checkbox)
        
        self.mic_help_button = QPushButton("?")
        self.mic_help_button.setFixedWidth(30)
        self.mic_help_button.setToolTip("Как это работает?")
        self.mic_help_button.clicked.connect(self.show_mic_help)
        broadcast_row.addWidget(self.mic_help_button)
        broadcast_row.addStretch()
        audio_layout.addLayout(broadcast_row)

        # 3. Громкость трансляции в микрофон
        mic_vol_row = QHBoxLayout()
        mic_vol_row.addWidget(QLabel("🎙 Громкость микрофона:"))
        self.mic_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.mic_volume_slider.setRange(0, 100)
        self.mic_volume_slider.setValue(80)
        self.mic_volume_slider.valueChanged.connect(self.change_mic_volume)
        mic_vol_row.addWidget(self.mic_volume_slider)
        self.mic_volume_label = QLabel("80%")
        self.mic_volume_label.setFixedWidth(45)
        mic_vol_row.addWidget(self.mic_volume_label)
        audio_layout.addLayout(mic_vol_row)

        main_layout.addWidget(audio_group)

        # ---------------- Прогресс ----------------
        progress_layout = QHBoxLayout()
        self.position_label = QLabel("0:00")
        self.position_label.setFixedWidth(45)
        progress_layout.addWidget(self.position_label)

        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 100)
        self.progress_slider.sliderMoved.connect(self.seek_position)
        progress_layout.addWidget(self.progress_slider)

        self.duration_label = QLabel("0:00")
        self.duration_label.setFixedWidth(45)
        progress_layout.addWidget(self.duration_label)
        main_layout.addLayout(progress_layout)

        # ---------------- Статус ----------------
        self.status_label = QLabel("Готов. F6 — Play/Pause | F5 — Назад | F7 — Вперёд")
        self.status_label.setFont(QFont("Arial", 9))
        self.status_label.setStyleSheet("color: #666;")
        main_layout.addWidget(self.status_label)

        # Локальные хоткеи (на случай если глобальные не сработают)
        QShortcut(QKeySequence("F6"), self, activated=self.toggle_play)
        QShortcut(QKeySequence("F5"), self, activated=self.play_previous_track)
        QShortcut(QKeySequence("F7"), self, activated=self.play_next_track)

    # ------------------------------------------------------------------ #
    #                          ПОИСК / СКАЧИВАНИЕ                        #
    # ------------------------------------------------------------------ #
    def is_youtube_url(self, text):
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([\w-]+)', r'(?:youtu\.be\/)([\w-]+)',
            r'(?:youtube\.com\/embed\/)([\w-]+)', r'(?:youtube\.com\/v\/)([\w-]+)',
            r'(?:youtube\.com\/shorts\/)([\w-]+)',
        ]
        return any(re.search(p, text) for p in patterns)

    def extract_video_id(self, text):
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([\w-]+)', r'(?:youtu\.be\/)([\w-]+)',
            r'(?:youtube\.com\/embed\/)([\w-]+)', r'(?:youtube\.com\/v\/)([\w-]+)',
            r'(?:youtube\.com\/shorts\/)([\w-]+)',
        ]
        for p in patterns:
            m = re.search(p, text)
            if m: return m.group(1)
        return None

    def search_tracks(self):
        query = self.search_input.text().strip()
        if not query:
            self.status_label.setText("Введите запрос для поиска")
            return

        if self.is_youtube_url(query):
            video_id = self.extract_video_id(query)
            if video_id:
                self.status_label.setText(f"Получение информации о видео: {video_id}...")
                self.search_button.setEnabled(False)

                def _worker():
                    video_info = get_video_info(video_id)
                    track_info = {
                        'webpage_url': f"https://www.youtube.com/watch?v={video_id}",
                        'title': video_info['title'],
                        'author': video_info['author'],
                        'duration': video_info['duration'],
                    }
                    self._download_track_thread(track_info)

                threading.Thread(target=_worker, daemon=True).start()
                return
            else:
                self.status_label.setText("Не удалось извлечь ID видео из ссылки")
                return

        self.status_label.setText(f"Поиск: {query}...")
        self.search_button.setEnabled(False)
        self.results_widget.clear()
        self.current_tracks = []
        threading.Thread(target=self._search_tracks_thread, args=(query,), daemon=True).start()

    def _search_tracks_thread(self, query):
        try:
            tracks = search_tracks(query, limit=10)
            self.current_tracks = tracks

            if tracks:
                for t in tracks:
                    d = t.get('duration', 0)
                    minutes, seconds = d // 60, d % 60
                    time_str = f"{minutes}:{seconds:02d}" if d > 0 else ""
                    self.results_widget.addItem(f"{t['author']} - {t['title']} {time_str}")
                self.status_label.setText(f"Найдено {len(tracks)} треков.")
            else:
                self.status_label.setText("Треки не найдены. Проверьте запрос или VPN.")
        except Exception as e:
            self.status_label.setText(f"Ошибка: {e}")
        finally:
            self.search_button.setEnabled(True)

    def download_selected(self, item):
        index = self.results_widget.row(item)
        if 0 <= index < len(self.current_tracks):
            track = self.current_tracks[index]
            self.status_label.setText(f"Скачивание: {track['author']} - {track['title']}...")
            threading.Thread(target=self._download_track_thread, args=(track,), daemon=True).start()

    def on_download_progress(self, p):
        if p.get('status') == 'downloading':
            self.status_label.setText(f"⏬ Скачивание: {p.get('percent', 0)}% (ETA {p.get('eta', 0)}s)")
        elif p.get('status') == 'converting':
            self.status_label.setText("🔄 Конвертация в MP3...")

    def _download_track_thread(self, track):
        try:
            if not track.get('webpage_url') and not track.get('url'):
                self.status_label.setText("Ошибка: нет URL для скачивания")
                self.search_button.setEnabled(True)
                return

            def _cb(p):
                self.progress_signal.emit(p)

            filepath = download_selected_track(track, progress_callback=_cb)

            if filepath:
                filename = os.path.basename(filepath)
                self.playlist.append(filepath)
                self.track_names.append(filename)
                self.playlist_widget.addItem(filename)
                self.status_label.setText(f"Добавлено: {filename}")
                self.current_track_label.setText(filename)
                self.save_playlist_state()
                self._play_file(filepath)
            else:
                self.status_label.setText("Ошибка при скачивании. Попробуйте другой трек.")
        except Exception as e:
            self.status_label.setText(f"Ошибка: {e}")
        finally:
            self.search_button.setEnabled(True)

    # ------------------------------------------------------------------ #
    #                         ВОСПРОИЗВЕДЕНИЕ                            #
    # ------------------------------------------------------------------ #
    def play_selected_track(self, item):
        index = self.playlist_widget.row(item)
        if 0 <= index < len(self.playlist):
            self.current_playlist_index = index
            self._play_file(self.playlist[index])

    def _play_file(self, filepath):
        if not os.path.exists(filepath):
            self.status_label.setText(f"Файл не найден: {filepath}")
            self.remove_missing_file(filepath)
            return

        self.current_track_path = filepath
        self.player.setSource(QUrl.fromLocalFile(filepath))
        self.player.play()

        self.is_playing = True
        self.play_button.setText("⏸ Пауза (F6)")
        self.current_track_label.setText(f"🎵 {os.path.basename(filepath)}")
        self.status_label.setText(f"▶ Воспроизводится: {os.path.basename(filepath)}")
        self.highlight_current_track()

    def highlight_current_track(self):
        if 0 <= self.current_playlist_index < self.playlist_widget.count():
            self.playlist_widget.setCurrentRow(self.current_playlist_index)

    def toggle_play(self):
        if self.player.source().isEmpty():
            if self.playlist:
                self.current_playlist_index = 0
                self._play_file(self.playlist[0])
            else:
                self.status_label.setText("Плейлист пуст. Добавьте треки через поиск")
            return

        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_button.setText("▶ Воспроизвести (F6)")
            self.status_label.setText("⏸ Пауза")
            self.is_playing = False
        else:
            self.player.play()
            self.play_button.setText("⏸ Пауза (F6)")
            self.status_label.setText("▶ Воспроизведение")
            self.is_playing = True

    def stop_playback(self):
        self.player.stop()
        self.play_button.setText("▶ Воспроизвести (F6)")
        self.is_playing = False
        self.position_label.setText("0:00")
        self.progress_slider.setValue(0)
        self.status_label.setText("⏹ Остановлено")

    def play_next_track(self):
        if not self.playlist: return
        if self.current_playlist_index < len(self.playlist) - 1:
            self.current_playlist_index += 1
        else:
            self.current_playlist_index = 0
        self._play_file(self.playlist[self.current_playlist_index])

    def play_previous_track(self):
        if not self.playlist: return
        if self.current_playlist_index > 0:
            self.current_playlist_index -= 1
        else:
            self.current_playlist_index = len(self.playlist) - 1
        self._play_file(self.playlist[self.current_playlist_index])

    def toggle_repeat(self, state):
        self.is_repeat = (state == Qt.CheckState.Checked.value)
        self.status_label.setText("🔁 Повтор включен" if self.is_repeat else "Повтор выключен")

    def on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.is_repeat:
                self.player.setPosition(0)
                self.player.play()
            else:
                self.play_next_track()

    # ------------------------------------------------------------------ #
    #                          ПЛЕЙЛИСТ                                  #
    # ------------------------------------------------------------------ #
    def clear_playlist(self):
        self.playlist.clear()
        self.track_names.clear()
        self.playlist_widget.clear()
        self.player.stop()
        self.current_track_label.setText("Нет трека")
        self.status_label.setText("🗑 Плейлист очищен (файлы сохранены)")
        self.current_playlist_index = -1
        self.save_playlist_state()

    def clear_all(self):
        reply = QMessageBox.question(
            self, "Подтверждение удаления",
            "Удалить все скачанные файлы из папки 'downloads'?\nЭто действие нельзя отменить!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.player.stop()
            self.is_playing = False
            self.play_button.setText("▶ Воспроизвести (F6)")

            download_folder = "downloads"
            deleted = 0
            if os.path.exists(download_folder):
                for f in os.listdir(download_folder):
                    fp = os.path.join(download_folder, f)
                    try:
                        if os.path.isfile(fp):
                            os.remove(fp)
                            deleted += 1
                    except Exception as e:
                        print(f"Ошибка удаления {fp}: {e}")

            self.playlist.clear()
            self.track_names.clear()
            self.playlist_widget.clear()
            self.current_track_label.setText("Нет трека")
            self.status_label.setText(f"🗑 Удалено {deleted} файлов, плейлист очищен")
            self.current_playlist_index = -1
            self.save_playlist_state()

    def remove_missing_file(self, filepath):
        if filepath in self.playlist:
            idx = self.playlist.index(filepath)
            self.playlist.pop(idx)
            if idx < len(self.track_names):
                self.track_names.pop(idx)
            self.playlist_widget.takeItem(idx)
            self.save_playlist_state()
            self.status_label.setText(f"Файл удалён из плейлиста: {os.path.basename(filepath)}")

    # ------------------------------------------------------------------ #
    #                            ЗВУК / МИКРОФОН                         #
    # ------------------------------------------------------------------ #
    def change_volume(self, value):
        self.audio_output.setVolume(value / 100)
        self.volume_label.setText(f"{value}%")

    def change_mic_volume(self, value):
        self.mic_volume = value
        self.mic_volume_label.setText(f"{value}%")
        # Громкость для трансляции (задел на будущее, если подключат VB-Cable)

    def toggle_mic_broadcast(self, state):
        self.mic_broadcast_enabled = (state == Qt.CheckState.Checked.value)
        if self.mic_broadcast_enabled:
            self.status_label.setText("🎤 Микрофон ВКЛ: Музыка транслируется в микрофон")
        else:
            self.status_label.setText("🎤 Микрофон ВЫКЛ: Музыка слышна только в колонках")

    def show_mic_help(self):
        QMessageBox.information(
            self, "Как включить трансляцию в микрофон",
            "Чтобы другие люди в Discord или игре слышали музыку:\n\n"
            "1. Скачайте и установите бесплатную программу VB-Audio Virtual Cable\n"
            "   (ссылка: https://vb-audio.com/Cable/)\n\n"
            "2. Перезагрузите компьютер.\n\n"
            "3. В настройках Windows (Звук -> Устройство вывода) выберите 'CABLE Input'.\n"
            "   (Теперь весь звук с компьютера пойдет в виртуальный кабель).\n\n"
            "4. В Discord/TeamSpeak/игре зайдите в настройки микрофона и выберите\n"
            "   устройство ввода 'CABLE Output'.\n\n"
            "5. Включите галочку 'Микрофон (трансляция музыки другим)' в этом плеере.\n\n"
            "Готово! Теперь ваши друзья услышат музыку, которая играет в плеере."
        )

    # ------------------------------------------------------------------ #
    #                         ПРОГРЕСС / ВРЕМЯ                           #
    # ------------------------------------------------------------------ #
    def update_position(self):
        if self.player.source().isEmpty(): return
        duration = self.player.duration()
        position = self.player.position()
        if duration > 0:
            self.progress_slider.setValue(int(position / duration * 100))
            self.position_label.setText(self._format_time(position))
            self.duration_label.setText(self._format_time(duration))

    def seek_position(self, value):
        if self.player.source().isEmpty(): return
        duration = self.player.duration()
        if duration > 0:
            self.player.setPosition(int(value / 100 * duration))

    def _format_time(self, ms):
        s = ms // 1000
        return f"{s // 60}:{s % 60:02d}"

    # ------------------------------------------------------------------ #
    #                          СОХРАНЕНИЕ                                #
    # ------------------------------------------------------------------ #
    def save_playlist_state(self):
        try:
            state = {'playlist': self.playlist, 'track_names': self.track_names}
            with open('playlist_state.json', 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения плейлиста: {e}")

    def load_playlist_state(self):
        try:
            if not os.path.exists('playlist_state.json'):
                return
            with open('playlist_state.json', 'r', encoding='utf-8') as f:
                state = json.load(f)

            playlist = state.get('playlist', [])
            track_names = state.get('track_names', [])

            valid_playlist, valid_names = [], []
            for i, fp in enumerate(playlist):
                if os.path.exists(fp):
                    valid_playlist.append(fp)
                    valid_names.append(track_names[i] if i < len(track_names) else os.path.basename(fp))
                else:
                    print(f"Файл не найден: {fp}")

            self.playlist = valid_playlist
            self.track_names = valid_names

            for name in self.track_names:
                self.playlist_widget.addItem(name)

            if self.playlist:
                self.status_label.setText(f"Загружено {len(self.playlist)} треков из сохранённого плейлиста")
                self.current_track_label.setText(f"Загружено: {len(self.playlist)} треков")
            else:
                self.status_label.setText("Сохранённый плейлист пуст или файлы удалены")
        except Exception as e:
            print(f"Ошибка загрузки плейлиста: {e}")

    def closeEvent(self, event):
        self.save_playlist_state()
        self.player.stop()
        self.timer.stop()
        try:
            keyboard.unhook_all() # Отключаем глобальные клавиши при выходе
        except:
            pass
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MusicPlayerApp()
    window.show()

    sys.exit(app.exec())