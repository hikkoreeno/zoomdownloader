import os
import re
import sys
import json
import time
import requests
import subprocess
from playwright.sync_api import sync_playwright
from tqdm import tqdm
from bs4 import BeautifulSoup

def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def download_zoom_recording(share_url, output_dir="downloads", progress_callback=None):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Status update helper
    def update_status(message, progress=None):
        if progress_callback:
            progress_callback({"message": message, "progress": progress})
        print(message)

    # Basic URL cleaning for common typos
    if share_url.startswith("ttps://"):
        share_url = "https://" + share_url[7:]
    elif share_url.startswith("ttp://"):
        share_url = "http://" + share_url[6:]

    update_status(f"[*] Navigating to: {share_url}")
    
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
            update_status("[*] Loading page...")
            page.goto(share_url, wait_until="load", timeout=90000)
            
            # Wait for any response that matches play/info
            update_status("[*] Extracting metadata...")
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
            update_status(f"[-] Error during browsing session: {e}", progress=-1)

        if not play_info:
            update_status("[-] Could not find play info. Direct extraction failed.", progress=-1)
            browser.close()
            return None

        if "result" in play_info:
            play_info = play_info['result']
        elif "data" in play_info:
            play_info = play_info['data']

        # Try multiple potential keys for topic and date
        try:
            topic = (
                play_info.get("meetingTopic") or 
                play_info.get("topic") or 
                (play_info.get("meet") or {}).get("topic") or
                (play_info.get("recording") or {}).get("topic") or
                "Zoom_Recording"
            )
            
            start_time_val = (
                play_info.get("startTime") or 
                play_info.get("meetingTime") or 
                play_info.get("start_time") or 
                (play_info.get("meet") or {}).get("meetingStartTimeStr") or
                (play_info.get("recording") or {}).get("start_time")
            )
            
            # Stream Selection Logic:
            # 1. Look for separate video and audio streams (Higher quality/reliability)
            # 2. Fallback to composite/view streams
            
            video_url = (
                play_info.get("video_url") or 
                play_info.get("viewMp4WithshareUrl") or 
                play_info.get("shareMp4Url") or 
                play_info.get("gallaryMp4Url") or 
                play_info.get("viewMp4Url") or 
                play_info.get("mp4_url") or 
                play_info.get("download_url")
            )
            
            audio_url = play_info.get("audio_url")
            
            resolution = "Unknown"
            if play_info.get("viewMp4WithshareUrl"):
                resolution = play_info.get("shareResolvtions") or "2560*1440"
            elif play_info.get("shareMp4Url"):
                resolution = play_info.get("shareResolvtions") or "2560*1440"
            elif play_info.get("gallaryMp4Url"):
                resolution = play_info.get("viewResolvtions") or "Unknown"
            else:
                resolution = play_info.get("viewResolvtions") or "640*360"

        except Exception as e:
            update_status(f"[-] Error during value extraction: {e}")
            topic = "Zoom_Recording"
            start_time_val = None
            video_url = None
            audio_url = None
            resolution = "Unknown"

        update_status(f"[*] Values found -> Topic: {topic}")

        if not video_url:
            update_status("[-] Video URL not found in play info.", progress=-1)
            browser.close()
            return None

        meeting_date = "unknown_date"
        if start_time_val:
            try:
                if "T" in str(start_time_val):
                    meeting_date = str(start_time_val).split("T")[0].replace("-", "")
                elif "," in str(start_time_val):
                    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06", 
                             "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
                    parts = str(start_time_val).replace(",", "").split(" ")
                    m, d, y = parts[0], parts[1], parts[2]
                    meeting_date = f"{y}{months.get(m, '00')}{int(d):02d}"
            except Exception as e:
                print(f"[*] Could not parse date '{start_time_val}': {e}")

        base_filename = sanitize_filename(f"{meeting_date}_{topic}")
        final_filepath = os.path.join(output_dir, f"{base_filename}.mp4")
        temp_video = os.path.join(output_dir, f"{base_filename}_temp_video.mp4")
        temp_audio = os.path.join(output_dir, f"{base_filename}_temp_audio.m4a")

        update_status(f"[+] Extracting recording: {topic}")
        update_status(f"[*] Target file: {final_filepath}")

        cookies = {c['name']: c['value'] for c in context.cookies()}
        browser.close()

        def download_file(url, path, desc):
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": share_url
            }
            response = requests.get(url, headers=headers, cookies=cookies, stream=True)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            with open(path, 'wb') as f:
                with tqdm(total=total_size, unit='B', unit_scale=True, desc=desc) as pbar:
                    for data in response.iter_content(1024*1024):
                        f.write(data)
                        downloaded += len(data)
                        pbar.update(len(data))
                        if total_size > 0:
                            prog = int((downloaded / total_size) * 100)
                            if progress_callback:
                                # Map two-stage download to 0-90%
                                current_phase_prog = int(prog * 0.45)
                                if "Audio" in desc:
                                    current_phase_prog += 45
                                progress_callback({"message": f"{desc}... {prog}%", "progress": current_phase_prog})

        try:
            # Download Video
            update_status(f"[*] Downloading primary video stream...")
            download_file(video_url, temp_video, "Video Stream")

            # Download Audio if separate
            if audio_url:
                update_status(f"[*] Downloading primary audio stream...")
                download_file(audio_url, temp_audio, "Audio Stream")

            # Final Processing with FFmpeg (Heavy Duty Mode)
            update_status(f"[*] Starting heavy-duty processing for 100% compatibility...")
            if progress_callback:
                progress_callback({"message": "Finalizing video (High-Compatibility Mode)...", "progress": 95})

            # Force yuv420p, even dimensions, and 1080p max for best compatibility
            # This fixes the 0x887A0005 error and ensures it plays everywhere.
            ffmpeg_cmd = ["ffmpeg", "-y"]
            ffmpeg_cmd += ["-i", temp_video]
            if audio_url and os.path.exists(temp_audio):
                ffmpeg_cmd += ["-i", temp_audio]

            # Video Filter: Scale to max 1080p, ensure even dimensions, force yuv420p
            vf_string = "scale='if(gt(iw,1920),1920,iw)':-2,format=yuv420p"
            
            ffmpeg_cmd += [
                "-vf", vf_string,
                "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.1",
                "-preset", "faster", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "faststart",
                final_filepath
            ]

            update_status(f"[*] Running FFmpeg: {' '.join(ffmpeg_cmd)}")
            
            # Use subprocess.run without capture_output to avoid buffer issues, or use explicit redirect
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                error_msg = result.stderr if result.stderr else "Unknown FFmpeg error"
                update_status(f"[-] FFmpeg process failed (Code {result.returncode}): {error_msg}")
                # Fallback to copy only if absolutely necessary, but warn user
                update_status("[!] Falling back to raw stream (playback might be unstable)...")
                if os.path.exists(temp_video):
                    os.replace(temp_video, final_filepath)
            else:
                update_status(f"[+] Processing complete.")

            # Final Cleanup
            for temp_f in [temp_video, temp_audio]:
                if os.path.exists(temp_f):
                    try: os.remove(temp_f)
                    except Exception as clean_e: 
                        update_status(f"[*] Note: Could not remove temp file {os.path.basename(temp_f)}: {clean_e}")

            if not os.path.exists(final_filepath):
                update_status("[-] Error: Final output file was not generated.", progress=-1)
                return None

            update_status(f"[+] Download and conversion finished: {final_filepath}", progress=100)
            return final_filepath

        except Exception as e:
            update_status(f"[-] Download failed during transmission or processing: {str(e)}", progress=-1)
            # Cleanup on crash
            for temp_f in [temp_video, temp_audio]:
                if os.path.exists(temp_f):
                    try: os.remove(temp_f)
                    except: pass
            return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python zoom_downloader.py <ZOOM_SHARE_URL>")
        sys.exit(1)
    
    url = sys.argv[1]
    download_zoom_recording(url)
