import sys
import time
import threading
import cv2
import pyautogui
from PySide6.QtCore import Qt, QThread, Signal, QRect, QPoint
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QMainWindow, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame

try:
    import mediapipe as mp
except ImportError:
    mp = None

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01


class HandTracker(QThread):
    hand_update = Signal(float, float, bool, str)
    status_update = Signal(str)
    frame_update = Signal(object)

    def __init__(self, camera_index=0):
        super().__init__()
        self.camera_index = camera_index
        self.running = True

    def stop(self):
        self.running = False
        self.wait(2000)

    def run(self):
        if mp is None:
            self.status_update.emit("MediaPipe is missing. Install the requirements first.")
            return

        cap = None
        for index in (self.camera_index, 1, 2, 3):
            opened = False
            for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
                candidate = cv2.VideoCapture(index, backend)
                if candidate.isOpened():
                    ok, test_frame = candidate.read()
                    if ok and test_frame is not None:
                        cap = candidate
                        self.status_update.emit(f"Camera connected • device {index}")
                        opened = True
                        break
                candidate.release()
            if opened:
                break

        if cap is None:
            self.status_update.emit("Camera unavailable. Close other camera apps and check Windows camera permissions.")
            return

        pinch_active = False
        try:
            with mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                model_complexity=0,
                min_detection_confidence=0.78,
                min_tracking_confidence=0.78,
            ) as hands:
                while self.running:
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        self.status_update.emit("Camera frame unavailable")
                        self.msleep(40)
                        continue

                    frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    preview = cv2.resize(rgb, (400, 225), interpolation=cv2.INTER_AREA)
                    h, w, ch = preview.shape
                    qimg = QImage(preview.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                    self.frame_update.emit(qimg)

                    result = hands.process(rgb)
                    if result.multi_hand_landmarks:
                        lm = result.multi_hand_landmarks[0].landmark
                        hand_score = 1.0
                        if result.multi_handedness:
                            try:
                                hand_score = result.multi_handedness[0].classification[0].score
                            except (AttributeError, IndexError, TypeError):
                                hand_score = 1.0
                        if hand_score < 0.80:
                            pinch_active = False
                            self.hand_update.emit(-1.0, -1.0, False, "Hand confidence low • move closer")
                            self.msleep(20)
                            continue

                        index_tip, thumb_tip = lm[8], lm[4]
                        palm_dx, palm_dy = lm[5].x - lm[17].x, lm[5].y - lm[17].y
                        palm_width = max((palm_dx * palm_dx + palm_dy * palm_dy) ** 0.5, 0.001)
                        dx, dy = index_tip.x - thumb_tip.x, index_tip.y - thumb_tip.y
                        pinch_ratio = ((dx * dx + dy * dy) ** 0.5) / palm_width

                        # Hysteresis prevents flicker near the pinch threshold.
                        pinch_active = pinch_ratio < (0.43 if pinch_active else 0.27)
                        self.hand_update.emit(
                            max(0.0, min(1.0, index_tip.x)),
                            max(0.0, min(1.0, index_tip.y)),
                            pinch_active,
                            "Hand tracked • pinch deliberately to select"
                        )
                    else:
                        pinch_active = False
                        self.hand_update.emit(-1.0, -1.0, False, "Show one hand clearly to the camera")
                    self.msleep(20)
        except Exception as exc:
            self.status_update.emit(f"Tracking error: {exc}")
        finally:
            cap.release()
            self.status_update.emit("Camera stopped")

class KeyboardOverlay(QWidget):
    def __init__(self, parent_window):
        super().__init__(None)
        self.parent_window = parent_window
        self.setWindowTitle("VirtualKey • Air Keyboard")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(820, 300)
        self.hovered_key = None
        self.rows = [
            [("Q","q"),("W","w"),("E","e"),("R","r"),("T","t"),("Y","y"),("U","u"),("I","i"),("O","o"),("P","p")],
            [("A","a"),("S","s"),("D","d"),("F","f"),("G","g"),("H","h"),("J","j"),("K","k"),("L","l")],
            [("Z","z"),("X","x"),("C","c"),("V","v"),("B","b"),("N","n"),("M","m"),("⌫","BACKSPACE"),(".", "."),(",", ",")],
            [("123","123"),("SPACE"," "),("ENTER","ENTER"),("SHIFT","SHIFT")]
        ]

    def key_rects(self):
        w, h = self.width(), self.height()
        margin, gap, top = 20, 7, 52
        row_h = max(38, (h - top - 28 - 3 * gap) // 4)
        rects = []
        for r, row in enumerate(self.rows):
            widths = [2.8 if label == "SPACE" else (1.45 if label in ("ENTER", "SHIFT", "BACKSPACE", "⌫") else 1.0)
                      for label, value in row]
            unit = (w - 2 * margin - (len(row) - 1) * gap) / sum(widths)
            total_w = sum(widths) * unit + (len(row) - 1) * gap
            x = (w - total_w) / 2
            for i, (label, value) in enumerate(row):
                kw = widths[i] * unit
                rects.append((QRect(int(x), int(top + r * (row_h + gap)), int(kw), int(row_h)), label, value))
                x += kw + gap
        return rects

    def set_hover_point(self, screen_x, screen_y):
        local = self.mapFromGlobal(QPoint(int(screen_x), int(screen_y)))
        new_hover = None
        for rect, label, value in self.key_rects():
            if rect.contains(local):
                new_hover = value
                break
        if new_hover != self.hovered_key:
            self.hovered_key = new_hover
            self.update()

    def select_hovered_key(self):
        if self.hovered_key is not None:
            self.parent_window.type_virtual_key(self.hovered_key)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 15, 27, 248))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 20, 20)
        painter.setBrush(QColor(24, 33, 52, 255))
        painter.drawRoundedRect(QRect(2, 2, self.width()-4, 43), 18, 18)
        painter.fillRect(QRect(2, 27, self.width()-4, 18), QColor(24, 33, 52, 255))
        painter.setPen(QColor(115, 164, 255))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(QRect(20, 7, 150, 30), Qt.AlignmentFlag.AlignVCenter, "VIRTUALKEY")
        painter.setPen(QColor(207, 217, 237))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRect(160, 7, self.width()-180, 30), Qt.AlignmentFlag.AlignVCenter,
                         "AIR KEYBOARD  •  Point at a key, then pinch to type")
        for rect, label, value in self.key_rects():
            hovered = value == self.hovered_key
            painter.setBrush(QColor(37, 99, 235, 255) if hovered else QColor(32, 42, 61, 255))
            painter.setPen(QPen(QColor(134, 183, 255) if hovered else QColor(61, 76, 102), 2 if hovered else 1))
            painter.drawRoundedRect(rect, 9, 9)
            painter.setPen(QColor(255, 255, 255) if hovered else QColor(220, 229, 246))
            painter.setFont(QFont("Segoe UI", 9 if len(label) > 4 else 10, QFont.Weight.DemiBold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.setPen(QColor(121, 139, 170))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(QRect(20, self.height()-18, self.width()-40, 14),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         "Blue key = fingertip target  •  Pinch once to select")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VirtualKey — Gesture Keyboard & Mouse")
        self.resize(690, 510)
        self.setMinimumSize(640, 470)
        self.tracker = None
        self.last_pinch = False
        self.pinch_started_at = None
        self.last_click_time = 0.0
        self.last_cursor_move = 0.0
        self.cursor_smoothing = None
        self.hover_candidate = None
        self.hover_candidate_since = 0.0
        self.stable_hover_value = None
        self.shift_enabled = False
        self.number_mode = False
        self.keyboard_visible = True

        root = QWidget()
        root.setStyleSheet("""
            QWidget { background: #0b1020; color: #eef3ff; font-family: 'Segoe UI'; }
            QLabel#title { font-size: 30px; font-weight: 800; color: #f6f8ff; }
            QLabel#muted { color: #9eacc7; font-size: 11px; }
            QPushButton { background: #326df4; color: white; border: 1px solid #4b82ff; border-radius: 10px; padding: 11px 15px; font-weight: 700; }
            QPushButton:hover { background: #4a80ff; }
            QPushButton:disabled { background: #273149; border-color: #273149; color: #77839d; }
            QFrame#panel { background: #121a2c; border: 1px solid #263452; border-radius: 14px; }
        """)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        title = QLabel("VirtualKey")
        title.setObjectName("title")
        subtitle = QLabel("GESTURE CONTROL STUDIO   /   WEBCAM • AIR KEYBOARD • DESKTOP MOUSE")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        panel = QFrame()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)
        self.status = QLabel("Camera not started")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        pl.addWidget(self.status)
        self.preview = QLabel("Webcam preview will appear here after you start the camera.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(225)
        self.preview.setStyleSheet("background: #080d18; border: 1px solid #2a3958; border-radius: 10px; color: #9eacc7;")
        pl.addWidget(self.preview)
        instructions = QLabel(
            "HOW TO USE\n"
            "1. Show one hand clearly to the camera.\n"
            "2. Move your index fingertip to aim at a key.\n"
            "3. Hold a deliberate thumb–index pinch briefly to select.\n"
            "The app ignores low-confidence hand detections and requires a stable target."
        )
        instructions.setWordWrap(True)
        pl.addWidget(instructions)
        layout.addWidget(panel, 1)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start camera")
        self.start_button.clicked.connect(self.start_camera)
        buttons.addWidget(self.start_button)
        self.keyboard_button = QPushButton("Hide keyboard")
        self.keyboard_button.clicked.connect(self.toggle_keyboard)
        buttons.addWidget(self.keyboard_button)
        self.stop_button = QPushButton("Stop camera")
        self.stop_button.clicked.connect(self.stop_camera)
        self.stop_button.setEnabled(False)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)

        self.setCentralWidget(root)
        self.keyboard = KeyboardOverlay(self)
        self.position_keyboard()
        self.keyboard.show()

    def position_keyboard(self):
        screen = QApplication.primaryScreen().availableGeometry()
        width = min(900, max(760, int(screen.width() * 0.62)))
        height = 270
        self.keyboard.resize(width, height)
        self.keyboard.move(screen.x() + (screen.width() - width) // 2,
                           screen.y() + screen.height() - height - 35)

    def start_camera(self):
        if self.tracker and self.tracker.isRunning():
            return
        self.last_pinch = False
        self.pinch_started_at = None
        self.cursor_smoothing = None
        self.tracker = HandTracker()
        self.tracker.hand_update.connect(self.on_hand_update)
        self.tracker.status_update.connect(self.status.setText)
        self.tracker.frame_update.connect(self.update_preview)
        self.tracker.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def update_preview(self, image):
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))

    def stop_camera(self):
        if self.tracker:
            self.tracker.stop()
            self.tracker = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.preview.clear()
        self.preview.setText("Camera stopped")

    def toggle_keyboard(self):
        self.keyboard_visible = not self.keyboard_visible
        if self.keyboard_visible:
            self.position_keyboard()
            self.keyboard.show()
            self.keyboard.raise_()
            self.keyboard_button.setText("Hide keyboard")
        else:
            self.keyboard.hide()
            self.keyboard_button.setText("Show keyboard")

    def on_hand_update(self, x, y, pinch, message):
        self.status.setText(message)
        now = time.time()
        if x < 0 or y < 0:
            self.last_pinch = False
            self.pinch_started_at = None
            self.hover_candidate = None
            self.stable_hover_value = None
            self.keyboard.set_hover_point(-10000, -10000)
            return

        screen = QApplication.primaryScreen().geometry()
        sx = int(screen.x() + x * screen.width())
        sy = int(screen.y() + y * screen.height())
        if self.cursor_smoothing is None:
            self.cursor_smoothing = (sx, sy)
        else:
            old_x, old_y = self.cursor_smoothing
            sx = int(old_x * 0.22 + sx * 0.78)
            sy = int(old_y * 0.22 + sy * 0.78)
            self.cursor_smoothing = (sx, sy)

        if now - self.last_cursor_move > 0.018:
            try:
                pyautogui.moveTo(sx, sy, _pause=False)
            except Exception:
                pass
            self.last_cursor_move = now

        in_keyboard = self.keyboard.isVisible() and self.keyboard.geometry().contains(QPoint(sx, sy))
        self.keyboard.set_hover_point(sx, sy)
        current_hover = self.keyboard.hovered_key if in_keyboard else None

        # Require a stable target before allowing an air-click to select a key.
        if current_hover != self.hover_candidate:
            self.hover_candidate = current_hover
            self.hover_candidate_since = now
            self.stable_hover_value = None
        elif current_hover is not None and now - self.hover_candidate_since >= 0.16:
            self.stable_hover_value = current_hover

        if pinch and not self.last_pinch:
            self.pinch_started_at = now

        if pinch and self.pinch_started_at is not None:
            held_long_enough = now - self.pinch_started_at >= 0.16
            cooldown_done = now - self.last_click_time >= 0.65
            if held_long_enough and cooldown_done:
                if in_keyboard:
                    if self.stable_hover_value is not None and self.stable_hover_value == current_hover:
                        self.keyboard.select_hovered_key()
                        self.last_click_time = now
                        self.status.setText("Key selected • release pinch to select again")
                        self.pinch_started_at = None
                else:
                    try:
                        pyautogui.click()
                        self.last_click_time = now
                    except Exception:
                        pass
                    self.pinch_started_at = None

        if not pinch:
            self.pinch_started_at = None
        self.last_pinch = pinch

    def type_virtual_key(self, key):
        try:
            if key == "123":
                self.number_mode = not self.number_mode
                self.status.setText("Number/symbol mode " + ("on" if self.number_mode else "off"))
                return
            if key == "SHIFT":
                self.shift_enabled = not self.shift_enabled
                self.status.setText("Shift " + ("on" if self.shift_enabled else "off"))
                return
            if key == "BACKSPACE":
                pyautogui.press("backspace")
                return
            if key == "ENTER":
                pyautogui.press("enter")
                return
            if key == " ":
                pyautogui.press("space")
                return

            output = key
            if self.number_mode:
                symbol_map = {
                    "q":"1","w":"2","e":"3","r":"4","t":"5","y":"6","u":"7","i":"8","o":"9","p":"0",
                    "a":"@","s":"#","d":"$","f":"%","g":"&","h":"-","j":"+","k":"(","l":")",
                    "z":"!","x":"?","c":":","v":";","b":"'","n":"~","m":"_"
                }
                output = symbol_map.get(key, key)
            if self.shift_enabled and len(output) == 1 and output.isalpha():
                output = output.upper()
                self.shift_enabled = False
            pyautogui.write(output, interval=0)
        except Exception as exc:
            self.status.setText(f"Input error: {exc}")

    def closeEvent(self, event):
        self.stop_camera()
        self.keyboard.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VirtualKey")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
