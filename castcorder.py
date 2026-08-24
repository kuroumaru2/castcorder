#!/usr/bin/env python3

import argparse
import os
import sys
import time
import logging
import signal
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import configparser
import random
import http.cookiejar

STOP_EVENT = False
PROCESS = None
SCRIPT_DIR = Path(__file__).parent
INITIAL_AUTH_LOGGED = {"tc_ss": False, "api": False}

def sanitize_filename(name):
    invalid_chars = r'[<>:"/\\|?*]'
    return re.sub(invalid_chars, "_", name)

def setup_logging(debug, streamer=None):
    logs_folder = SCRIPT_DIR / "logs"
    logs_folder.mkdir(parents=True, exist_ok=True)
    
    sanitized_streamer = sanitize_filename(streamer) if streamer else None
    log_file = logs_folder / (f"castcorder_direct.log" if not streamer else f"castcorder_{sanitized_streamer}.log")
    
    class StreamOfflineHandler(logging.StreamHandler):
        def emit(self, record):
            try:
                msg = self.format(record)
                if "Stream offline" in msg:
                    sys.stdout.write("\r\033[K" + msg)
                    sys.stdout.flush()
                else:
                    sys.stdout.write("\n" + msg + "\n")
                    sys.stdout.flush()
            except Exception:
                self.handleError(record)
    
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s,%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            StreamOfflineHandler()
        ]
    )
    logging.info(f"Logging initialized to {log_file}")

def check_dependencies():
    required = ["ffmpeg", "yt-dlp", "ffprobe"]
    missing = [tool for tool in required if not shutil.which(tool)]
    if missing:
        logging.error(f"Missing dependencies: {', '.join(missing)}")
        sys.exit(1)

def load_config(config_file):
    config = configparser.ConfigParser()
    config.read(config_file, encoding='utf-8')
    defaults = {
        "check_interval": os.getenv("CHECK_INTERVAL", "15"),
        "retry_delay": os.getenv("RETRY_DELAY", "30"),
        "twitcasting_username": os.getenv("TWITCASTING_USERNAME", ""),
        "twitcasting_password": os.getenv("TWITCASTING_PASSWORD", ""),
        "private_stream_password": os.getenv("PRIVATE_STREAM_PASSWORD", ""),
        "hls_url": os.getenv("HLS_URL", "")
    }
    if "recorder" in config:
        defaults.update(config["recorder"])
    return defaults

def parse_args():
    parser = argparse.ArgumentParser(description="TwitCasting Stream Recorder")
    parser.add_argument("--streamer", help="Streamer username")
    parser.add_argument("--quality", default="best", help="Stream quality (best, high, medium, low)")
    parser.add_argument("--streamers-file", type=Path, default=SCRIPT_DIR / "streamers.txt")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--fast-exit", action="store_true")
    parser.add_argument("--hls-url", help="Direct HLS URL to record")
    return parser.parse_args()

def validate_streamer(streamer):
    if not re.match(r"^[a-zA-Z0-9_:]+$", streamer):
        logging.error(f"Invalid streamer username: {streamer}")
        sys.exit(1)
    return streamer

def select_streamer(args, streamers_file):
    if args.streamer:
        return validate_streamer(args.streamer)
    if not streamers_file.exists():
        logging.error(f"Streamers file not found: {streamers_file}")
        sys.exit(1)
    with streamers_file.open("r", encoding="utf-8") as f:
        streamers = [line.strip() for line in f if line.strip()]
    if not streamers:
        logging.error("No streamers found in streamers.txt")
        sys.exit(1)
    if len(streamers) == 1:
        return validate_streamer(streamers[0])
    print("Select a streamer:")
    for i, streamer in enumerate(streamers, 1):
        print(f"{i}. {streamer}")
    while True:
        try:
            choice = int(input("Enter number: ")) - 1
            if 0 <= choice < len(streamers):
                return validate_streamer(streamers[choice])
            print("Invalid choice.")
        except ValueError:
            print("Enter a valid number.")

def check_disk_space(save_folder, min_space_gb=5):
    total, used, free = shutil.disk_usage(save_folder)
    free_gb = free / (1024 ** 3)
    if free_gb < min_space_gb:
        logging.error(f"Insufficient disk space: {free_gb:.2f} GB available, {min_space_gb} GB required")
        sys.exit(1)

def parse_cookies(cookies_file):
    cookies = {}
    try:
        with open(cookies_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    parts = line.strip().split('\t')
                    if len(parts) >= 7:
                        cookies[parts[5]] = parts[6]
        if 'tc_ss' in cookies and not INITIAL_AUTH_LOGGED["tc_ss"]:
            logging.info("Authentication successful: tc_ss cookie found")
            INITIAL_AUTH_LOGGED["tc_ss"] = True
        return cookies
    except Exception as e:
        logging.error(f"Failed to parse cookies file: {e}")
        return {}

def is_stream_live(streamer, cookies_file, retry_delay, quality="best"):
    time.sleep(random.uniform(0.5, 2.0))
    cmd = [
        "yt-dlp", "--get-url", "--hls-use-mpegts", "--hls-prefer-ffmpeg",
        "--cookies", str(cookies_file),
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36",
        "--add-header", "Referer:https://twitcasting.tv/",
        f"https://twitcasting.tv/{streamer}"
    ]
    config = load_config(SCRIPT_DIR / "config.ini")
    if config.get("private_stream_password"):
        cmd.extend(["--video-password", config["private_stream_password"]])
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0 and res.stdout.strip():
            return True, res.stdout.strip()
    except subprocess.SubprocessError:
        pass

    api_url = f"https://twitcasting.tv/streamserver.php?target={streamer}&mode=client&player=pc_web"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36"}
    try:
        response = requests.get(api_url, headers=headers, cookies=parse_cookies(cookies_file), timeout=10)
        data = response.json()
        if data.get("movie", {}).get("live", False):
            streams = data.get("tc-hls", {}).get("streams", {})
            hls_url = streams.get(quality if quality != "best" else "high")
            if hls_url:
                return True, hls_url
    except Exception:
        pass

    logging.info(f"Stream offline: {streamer}, retrying in {retry_delay}s")
    return False, None

def fetch_metadata(streamer, hls_url=None):
    url = f"https://twitcasting.tv/{streamer}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36"}
    stream_id = "unknown"
    if hls_url:
        match = re.search(r'movie_id=(\d+)|/movie/(\d+)|/streams/(\d+)', hls_url)
        if match:
            stream_id = next((g for g in match.groups() if g), "unknown")
    try:
        response = requests.get(url, headers=headers, timeout=10, cookies=parse_cookies(SCRIPT_DIR / "cookies.txt"))
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.find("meta", property="og:title")["content"] if soup.find("meta", property="og:title") else "Unknown Title"
        thumbnail = soup.find("meta", property="og:image")["content"] if soup.find("meta", property="og:image") else ""
        return title, stream_id, thumbnail
    except Exception:
        return "Unknown Title", stream_id, ""

def download_thumbnail(thumbnail_url, save_path):
    if not thumbnail_url:
        return False
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36"}
        res = requests.get(thumbnail_url, headers=headers, timeout=10)
        with open(save_path, "wb") as f:
            f.write(res.content)
        return True
    except Exception:
        return False

def generate_filename(title, streamer, stream_id, date):
    title = re.sub(r'[<>:"/\\|?*]', "_", title)
    formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("[%Y%m%d]")
    return f"{formatted_date} {title} [{streamer}] [{stream_id}]"[:255]

def get_unique_filename(base_path, ext):
    path = base_path.with_suffix(ext)
    if not path.exists():
        return path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_path.with_name(f"{base_path.stem}_{timestamp}{ext}")

def validate_recording(file_path):
    if not file_path.exists() or file_path.stat().st_size < 100 * 1024:
        return False, "File too small or missing"
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(file_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if not res.stdout.strip():
            return False, "No valid video stream (blank recording detected)"
        return True, "Valid"
    except Exception as e:
        return False, f"Probe error: {e}"

def record_stream(hls_url, output_file, cookies_file, quality, streamer=None):
    global PROCESS, STOP_EVENT
    logging.info(f"Recording HLS URL: {hls_url}")
    logging.info(f"Writing File {output_file.name}")
    
    config = load_config(SCRIPT_DIR / "config.ini")
    cmd = [
        "yt-dlp", "--hls-use-mpegts", "--downloader", "ffmpeg", "--no-part",
        "--cookies", str(cookies_file),
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36",
        "-f", quality, "--output", str(output_file), hls_url
    ]
    if config.get("private_stream_password"):
        cmd.extend(["--video-password", config["private_stream_password"]])
        
    try:
        PROCESS = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in PROCESS.stdout:
            if "frame=" in line or "size=" in line or "time=" in line:
                sys.stdout.write(f"\r\033[K{line.strip()}")
                sys.stdout.flush()
            if STOP_EVENT:
                PROCESS.terminate()
                break
        PROCESS.wait()
        sys.stdout.write("\n")
    except Exception as e:
        logging.error(f"Error during recording execution: {e}")
    finally:
        PROCESS = None

def signal_handler(sig, frame):
    global STOP_EVENT
    STOP_EVENT = True
    logging.info("Signal received. Stopping gracefully...")

def main():
    global STOP_EVENT
    args = parse_args()
    config = load_config(SCRIPT_DIR / "config.ini")
    signal.signal(signal.SIGINT, signal_handler)
    
    streamer = select_streamer(args, args.streamers_file) if not args.hls_url else None
    setup_logging(args.debug, streamer)
    check_dependencies()
    check_disk_space(SCRIPT_DIR)
    
    cookies_file = SCRIPT_DIR / "cookies.txt"
    save_folder = SCRIPT_DIR / (sanitize_filename(streamer) if streamer else "")
    save_folder.mkdir(parents=True, exist_ok=True)
    
    check_interval = float(config["check_interval"])
    retry_delay = float(config["retry_delay"])
    
    while not STOP_EVENT:
        is_live, hls_url = is_stream_live(streamer, cookies_file, retry_delay, args.quality)
        if is_live:
            logging.info(f"Stream is live: {streamer}")
            title, stream_id, thumbnail_url = fetch_metadata(streamer, hls_url)
            filename = generate_filename(title, streamer, stream_id, datetime.now().strftime("%Y-%m-%d"))
            ts_file = get_unique_filename(save_folder / filename, ".ts")
            
            if thumbnail_url:
                download_thumbnail(thumbnail_url, ts_file.with_suffix(".jpg"))
                
            record_stream(hls_url, ts_file, cookies_file, args.quality, streamer)
            
            valid, reason = validate_recording(ts_file)
            if not valid:
                logging.warning(f"Invalid file generated ({reason}). Cleaning up file and cooling down...")
                ts_file.unlink(missing_ok=True)
                time.sleep(10)
            else:
                logging.info(f"Recording successfully saved: {ts_file.name}")
        
        time.sleep(check_interval)

if __name__ == "__main__":
    main()
