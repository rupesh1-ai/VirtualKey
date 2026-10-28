# VirtualKey — Gesture Control Studio

Windows desktop prototype for webcam-controlled mouse and floating air keyboard.

## New in this version
- Automatically shows the virtual keyboard when Windows UI Automation detects focus in a common text-entry control (Edit, ComboBox, Document).
- Auto-show ON/OFF button.
- Keyboard overlay does not accept focus, helping the active text field keep focus while selecting virtual keys.
- Existing gesture stabilization remains.

## Run
In the project folder:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

If `.venv` does not exist yet, create it first with `py -3.11 -m venv .venv`.

## Auto-show limitations
Automatic detection works best with standard Windows text boxes and many browser input fields. Some browser address/search bars, custom-drawn apps, elevated apps, or unusual controls may not expose focus through Windows UI Automation. Use the Show keyboard button if a field is not detected. The keyboard remains visible after focus changes to avoid flicker.
