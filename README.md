# Zoom Downloader

A Python script to download Zoom meeting recordings from a share URL.

## Features
- Extracts MP4 stream URLs from Zoom share links.
- Selects the best available stream (Composite > Shared Screen > Gallery > Speaker).
- Supports high-resolution recordings (up to 2560x1440).
- Provides advice for playback of high-resolution files.
- Downloads files using `requests` with a progress bar.

## Installation
```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage
```bash
python zoom_downloader.py "YOUR_ZOOM_URL"
```
