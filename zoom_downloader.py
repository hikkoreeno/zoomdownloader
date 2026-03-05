import os
import re
import sys
import json
import time
import requests
from playwright.sync_api import sync_playwright
from tqdm import tqdm
from bs4 import BeautifulSoup

def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def download_zoom_recording(share_url, output_dir="downloads"):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Basic URL cleaning for common typos
    if share_url.startswith("ttps://"):
        share_url = "https://" + share_url[7:]
    elif share_url.startswith("ttp://"):
        share_url = "http://" + share_url[6:]

    print(f"[*] Navigating to: {share_url}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()

        play_info = None

        # Intercept network responses to find play/info
        def handle_response(response):
            nonlocal play_info
            if "play/info" in response.url:
                try:
                    if response.status == 200:
                        data = response.json()
                        res = data.get("result") or data.get("data")
                        if res and (res.get("viewMp4Url") or res.get("mp4_url")):
                            play_info = data
                            print(f"[+] Found valid play info API: {response.url}")
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            print("[*] Loading page...")
            page.goto(share_url, wait_until="load", timeout=90000)
            
            # Wait for any response that matches play/info
            print("[*] Extracting metadata...")
            for _ in range(30):
                if play_info:
                    break
                # Try clicking play if it's there as it sometimes triggers the API
                try:
                    play_button = page.locator("button.vjs-big-play-button").or_(page.locator(".vjs-play-control"))
                    if play_button.is_visible():
                        play_button.click()
                except:
                    pass
                time.sleep(1)

        except Exception as e:
            print(f"[-] Error during browsing session: {e}")

        if not play_info:
            print("[-] Could not find play info. Direct extraction failed.")
            browser.close()
            return


            
        if "result" in play_info:
            play_info = play_info['result']
        elif "data" in play_info:
            play_info = play_info['data']

        # Try multiple potential keys for topic and date
        try:
            # Topic can be in root or nested in 'meet' or 'recording'
            topic = (
                play_info.get("meetingTopic") or 
                play_info.get("topic") or 
                (play_info.get("meet") or {}).get("topic") or
                (play_info.get("recording") or {}).get("topic") or
                "Zoom_Recording"
            )
            
            # Start time can be a string or a timestamp
            start_time_val = (
                play_info.get("startTime") or 
                play_info.get("meetingTime") or 
                play_info.get("start_time") or 
                (play_info.get("meet") or {}).get("meetingStartTimeStr") or
                (play_info.get("recording") or {}).get("start_time")
            )
            
            # Stream Selection Logic:
            # 1. viewMp4WithshareUrl (Composite: Speaker + Share - Best compatibility)
            # 2. shareMp4Url (Shared Screen - High Resolution)
            # 3. gallaryMp4Url (Gallery View)
            # 4. viewMp4Url / mp4_url / download_url (Speaker View)
            mp4_url = (
                play_info.get("viewMp4WithshareUrl") or 
                play_info.get("shareMp4Url") or 
                play_info.get("gallaryMp4Url") or 
                play_info.get("viewMp4Url") or 
                play_info.get("mp4_url") or 
                play_info.get("download_url")
            )
            
            resolution = "Unknown"
            if play_info.get("viewMp4WithshareUrl"):
                print("[+] Selected stream: Composite (Speaker + Share)")
                resolution = play_info.get("shareResolvtions") or "2560*1440"
            elif play_info.get("shareMp4Url"):
                print("[+] Selected stream: Shared Screen (High Resolution)")
                resolution = play_info.get("shareResolvtions") or "2560*1440"
            elif play_info.get("gallaryMp4Url"):
                print("[+] Selected stream: Gallery View")
                # Gallery usually follows view resolution
                resolution = play_info.get("viewResolvtions") or "Unknown"
            else:
                print("[+] Selected stream: Speaker View / Default")
                resolution = play_info.get("viewResolvtions") or "640*360"

        except Exception as e:
            print(f"[-] Error during value extraction: {e}")
            topic = "Zoom_Recording"
            start_time_val = None
            mp4_url = None
            resolution = "Unknown"

        print(f"[*] Values found -> Topic: {topic}, StartTime: {start_time_val}")

        if not mp4_url:
            print("[-] Direct MP4 URL not found in play info.")
            browser.close()
            return

        # Try to get the meeting date as well
        meeting_date = "unknown_date"
        if start_time_val:
            try:
                if "T" in str(start_time_val):
                    # Format: "2026-02-05T11:02:24Z" -> "20260205"
                    meeting_date = str(start_time_val).split("T")[0].replace("-", "")
                elif "," in str(start_time_val):
                    # Format: "Dec 25, 2025 07:56 PM" -> "20251225"
                    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06", 
                             "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
                    parts = str(start_time_val).replace(",", "").split(" ")
                    # Expecting [Month, Day, Year, ...]
                    m, d, y = parts[0], parts[1], parts[2]
                    meeting_date = f"{y}{months.get(m, '00')}{int(d):02d}"
            except Exception as e:
                print(f"[*] Could not parse date '{start_time_val}': {e}")

        filename = sanitize_filename(f"{meeting_date}_{topic}.mp4")
        filepath = os.path.join(output_dir, filename)

        print(f"[+] Extracting recording: {topic}")
        print(f"[*] Target file: {filepath}")

        # Use requests to download because it's better for large files and progress bars
        # We MUST extract cookies before closing the browser
        cookies = {c['name']: c['value'] for c in context.cookies()}
        
        browser.close()

        if not mp4_url:
            print("[-] Direct MP4 URL not found in play info.")
            return

        print(f"[*] Starting download...")
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": share_url
            }
            
            response = requests.get(mp4_url, headers=headers, cookies=cookies, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024 * 1024 # 1MB

            with open(filepath, 'wb') as f:
                with tqdm(total=total_size, unit='B', unit_scale=True, desc=filename) as pbar:
                    for data in response.iter_content(block_size):
                        f.write(data)
                        pbar.update(len(bytes(data)))
            
            print(f"\n[+] Download complete: {filepath}")
            print(f"[*] Detected Resolution: {resolution}")
            
            # Provide advice for high resolution videos
            if "*" in resolution:
                try:
                    w, h = map(int, resolution.split("*"))
                    if w > 1920 or h > 1080:
                        print("\n[!] IMPORTANT: This recording is in High Resolution (QHD/2K).")
                        print("[!] If your media player shows an 'Unsupported Encoding' error, please try:")
                        print("[!] 1. Using VLC Media Player (https://www.videolan.org/)")
                        print("[!] 2. Opening the file with a Web Browser (Chrome/Edge)")
                        print("[!] 3. Windows Media Player might not support this resolution/codec by default.")
                except:
                    pass

            return filepath

        except Exception as e:
            print(f"[-] Download failed: {e}")
            return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python zoom_downloader.py <ZOOM_SHARE_URL>")
        sys.exit(1)
    
    url = sys.argv[1]
    download_zoom_recording(url)
