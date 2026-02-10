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

# Global variables
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
                sys.stdout.write("\r\033[K")
                sys.stdout.write(msg)
                sys.stdout.flush()
                if "Stream offline" not in msg:
                    sys.stdout.write("\n")
            except Exception as e:
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
    required = ["ffmpeg", "yt-dlp"]
    missing = []
    for tool in required:
        if not shutil.which(tool):
            missing.append(tool)
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
                        domain, _, _, _, _, name, value = parts[:7]
                        if 'twitcasting.tv' in domain:
                            cookies[name] = value
        if 'tc_ss' in cookies and not INITIAL_AUTH_LOGGED["tc_ss"]:
            logging.info("Authentication successful: tc_ss cookie found")
            INITIAL_AUTH_LOGGED["tc_ss"] = True
        elif 'tc_ss' not in cookies and not INITIAL_AUTH_LOGGED["tc_ss"]:
            logging.warning("Cookies file does not contain tc_ss cookie")
            INITIAL_AUTH_LOGGED["tc_ss"] = True
        return cookies
    except Exception as e:
        logging.error(f"Failed to parse cookies file: {e}")
        return {}

def is_stream_live(streamer, cookies_file, retry_delay, quality="best", offline_counter=[0]):
    logging.debug(f"Checking stream status for {streamer}")
    time.sleep(random.uniform(0.5, 2.0))
    
    failure_reason = ""
    cmd = [
        "yt-dlp",
        "--get-url",
        "--hls-use-mpegts",
        "--hls-prefer-ffmpeg",
        "--cookies", str(cookies_file),
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "--add-header", "Referer:https://twitcasting.tv/",
        "--add-header", "Origin:https://twitcasting.tv/",
        f"https://twitcasting.tv/{streamer}"
    ]
    config = load_config(SCRIPT_DIR / "config.ini")
    if config.get("private_stream_password"):
        cmd.extend(["--video-password", config["private_stream_password"]])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            logging.info(f"Stream is live via yt-dlp: {streamer}")
            if not INITIAL_AUTH_LOGGED["tc_ss"]:
                logging.info("Authentication successful: Valid response from yt-dlp")
                INITIAL_AUTH_LOGGED["tc_ss"] = True
            offline_counter[0] = 0
            return True, result.stdout.strip()
        failure_reason = "yt-dlp"
        logging.debug(f"yt-dlp stderr: {result.stderr}")
    except subprocess.SubprocessError as e:
        failure_reason = f"yt-dlp ({str(e)})"
        logging.debug(f"yt-dlp stream check failed: {e}")
    
    api_url = f"https://twitcasting.tv/streamserver.php?target={streamer}&mode=client&player=pc_web"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Referer": "https://twitcasting.tv/",
        "Origin": "https://twitcasting.tv/"
    }
    cookies = parse_cookies(cookies_file)
    
    try:
        response = requests.get(api_url, headers=headers, cookies=cookies, timeout=10)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"API response for {streamer}: {data}")
        if not INITIAL_AUTH_LOGGED["api"]:
            logging.info("Authentication successful: Valid response from API")
            INITIAL_AUTH_LOGGED["api"] = True
        
        movie = data.get("movie", {})
        tc_hls = data.get("tc-hls", {})
        is_live = movie.get("live", False)
        
        hls_url = None
        if is_live:
            streams = tc_hls.get("streams", {})
            if quality == "best":
                for q in ["high", "medium", "low"]:
                    if q in streams:
                        hls_url = streams[q]
                        break
            else:
                hls_url = streams.get(quality)
            
            if not isinstance(hls_url, str) or not hls_url:
                logging.warning(f"Invalid HLS URL for quality {quality}: {hls_url}")
                return False, None
        
        if is_live and hls_url:
            logging.info(f"Stream is live via API, HLS URL: {hls_url}")
            offline_counter[0] = 0
            return True, hls_url
        else:
            failure_reason = f"{failure_reason + '/' if failure_reason else ''}API"
            offline_counter[0] += 1
            logging.info(f"Stream offline ({failure_reason}): {streamer}, retrying in {retry_delay}s")
            return False, None
    except requests.RequestException as e:
        failure_reason = f"{failure_reason + '/' if failure_reason else ''}API ({str(e)})"
        logging.debug(f"API request failed: {e}")
        offline_counter[0] += 1
        logging.info(f"Stream offline ({failure_reason}): {streamer}, retrying in {retry_delay}s")
        return False, None

def fetch_metadata(streamer, hls_url=None):
    url = f"https://twitcasting.tv/{streamer}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Referer": "https://twitcasting.tv/",
        "Origin": "https://twitcasting.tv/"
    }
    stream_id = "unknown"
    
    if hls_url:
        stream_id_match = re.search(r'movie_id=(\d+)|/movie/(\d+)|movieid/(\d+)|/streams/(\d+)', hls_url)
        if stream_id_match:
            stream_id = next((g for g in stream_id_match.groups() if g), "unknown")
            logging.debug(f"Extracted stream_id from HLS URL: {stream_id}")
    
    try:
        response = requests.get(url, headers=headers, timeout=10, cookies=parse_cookies(SCRIPT_DIR / "cookies.txt"))
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.find("meta", property="og:title")["content"] if soup.find("meta", property="og:title") else "Unknown Title"
        thumbnail = soup.find("meta", property="og:image")["content"] if soup.find("meta", property="og:image") else ""
        
        if stream_id == "unknown":
            stream_id_match = re.search(r"movie_id=(\d+)", response.text)
            stream_id = stream_id_match.group(1) if stream_id_match else "unknown"
            logging.debug(f"Extracted stream_id from webpage: {stream_id}")
        
        return title, stream_id, thumbnail
    except Exception as e:
        logging.error(f"Failed to fetch metadata: {e}")
        return "Unknown Title", stream_id, ""

def download_thumbnail(thumbnail_url, save_path):
    if not thumbnail_url:
        return False
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"}
        response = requests.get(thumbnail_url, headers=headers, timeout=10)
        response.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(response.content)
        return True
    except Exception as e:
        logging.warning(f"Failed to download thumbnail: {e}")
        return False

def generate_filename(title, streamer, stream_id, date):
    unsafe_chars = r'[<>:"/\\|?*]'
    title = re.sub(unsafe_chars, "_", title)
    formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("[%Y%m%d]")
    filename = f"{formatted_date} {title} [{streamer}] [{stream_id}]"
    return filename[:255]

def get_unique_filename(base_path, ext):
    path = base_path.with_suffix(ext)
    if not path.exists():
        return path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{base_path.stem}_{timestamp}"
    new_path = base_path.with_name(f"{base_name}{ext}")
    counter = 2
    while new_path.exists():
        new_path = base_path.with_name(f"{base_name}_{counter}{ext}")
        counter += 1
    return new_path

def get_stream_duration(file_path, retries=3, delay=1):
    for attempt in range(retries):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            duration = float(result.stdout.strip())
            return int(duration)
        except (subprocess.SubprocessError, ValueError) as e:
            logging.debug(f"Duration parsing error on attempt {attempt + 1}: {e}")
        time.sleep(delay)
    logging.warning(f"Failed to parse duration for {file_path} after {retries} attempts")
    return 0

def validate_recording(file_path, min_duration=5, min_size_mb=0.1):
    try:
        if not file_path.exists():
            return False, "File does not exist"
        
        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb < min_size_mb:
            return False, f"File size too small: {size_mb:.2f}MB"
        
        duration = get_stream_duration(file_path)
        if duration < min_duration:
            return False, f"File duration too short: {duration}s"
        
        return True, "File valid"
    except Exception as e:
        return False, f"Validation error: {str(e)}"

def record_stream(hls_url, output_file, cookies_file, quality, streamer=None, max_retries=3, retry_delay=10):
    global PROCESS, STOP_EVENT
    logging.info(f"Recording HLS URL: {hls_url}")
    logging.info(f"Writing File {output_file.name}")
    
    config = load_config(SCRIPT_DIR / "config.ini")
    cmd = [
        "yt-dlp",
        "--hls-use-mpegts",
        "--hls-prefer-ffmpeg",
        "--downloader", "ffmpeg",
        "--no-part",
        "--xattrs",
        "--cookies", str(cookies_file),
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "--add-header", "Referer:https://twitcasting.tv/",
        "--add-header", "Origin:https://twitcasting.tv/",
        "-f", quality,
        "--output", str(output_file),
        hls_url
    ]
    if config.get("private_stream_password"):
        cmd.extend(["--video-password", config["private_stream_password"]])
    
    retry_count = 0
    start_time = time.time()
    output_path = Path(output_file)
    
    while not STOP_EVENT and retry_count < max_retries:
        try:
            PROCESS = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                universal_newlines=True
            )
        except subprocess.SubprocessError as e:
            logging.error(f"Failed to start recording process: {e}")
            PROCESS = None
            return
        
        last_size_bytes = 0
        last_update_time = start_time
        print("\nRecording progress (file size monitoring):")
        
        while PROCESS.poll() is None:
            try:
                current_time = time.time()
                
                if output_path.exists():
                    try:
                        current_size_bytes = output_path.stat().st_size
                        size_mb = current_size_bytes / (1024 * 1024)
                        size_gb = current_size_bytes / (1024 ** 3)
                        
                        elapsed = current_time - start_time
                        hours = int(elapsed // 3600)
                        minutes = int((elapsed % 3600) // 60)
                        seconds = int(elapsed % 60)
                        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                        
                        if current_time - last_update_time >= 1.0:  # update every ~1 second
                            if current_size_bytes > last_size_bytes:
                                delta_bytes = current_size_bytes - last_size_bytes
                                delta_time = current_time - last_update_time
                                speed_mib_s = (delta_bytes / (1024 * 1024)) / delta_time
                                
                                progress = (
                                    f"Size: {size_gb:.2f} GB   "
                                    f"Duration: {duration_str}   "
                                    f"Speed: {speed_mib_s:.2f} MiB/s"
                                )
                            else:
                                progress = f"Size: {size_gb:.2f} GB   Duration: {duration_str}   (no growth)"
                            
                            print(f"\r{progress:<80}", end="", flush=True)
                            last_size_bytes = current_size_bytes
                            last_update_time = current_time
                    except Exception:
                        # File might be locked or not yet fully written
                        pass
                
                if STOP_EVENT:
                    logging.info("Termination signal received, stopping recording...")
                    PROCESS.terminate()
                    break
                
                time.sleep(0.3)  # ~3 checks per second
                
            except Exception as e:
                logging.error(f"Error during progress monitoring: {e}")
                break
        
        # Clear the progress line
        print("\r" + " " * 80 + "\r", end="", flush=True)
        
        try:
            stdout, stderr = PROCESS.communicate(timeout=30)
            for line in stdout.splitlines():
                if line.strip():
                    logging.info(f"yt-dlp stdout: {line.strip()}")
            for line in stderr.splitlines():
                if line.strip():
                    logging.debug(f"yt-dlp stderr: {line.strip()}")
            
            if output_file.exists():
                size_bytes = output_file.stat().st_size
                logging.info(f"File exists after download: {output_file}, Size: {size_bytes / 1024:.2f} KiB")
            else:
                logging.warning(f"File does not exist after download: {output_file}")
            
            if PROCESS.returncode != 0:
                logging.error(f"Recording failed with return code {PROCESS.returncode}")
            
            if output_file.exists():
                is_valid, reason = validate_recording(output_file, min_duration=5, min_size_mb=0.1)
                if is_valid:
                    size_bytes = output_file.stat().st_size
                    size_gib = size_bytes / (1024 ** 3)
                    duration = get_stream_duration(output_file)
                    if duration == 0:
                        duration = int(time.time() - start_time)
                        logging.debug(f"Using elapsed time as duration: {duration} seconds")
                    duration_str = f"{duration//3600:02d}h {(duration%3600)//60:02d}m {duration%60:02d}s"
                    speed_kib_s = (size_bytes / 1024) / duration if duration > 0 else 0
                    logging.info(f"Recording completed Size: {size_gib:.2f} GiB ({duration_str} @ {speed_kib_s:.2f} KiB/s)")
                    logging.info(f"File saved as: {output_file}")
                    break
                else:
                    logging.warning(f"Invalid recording: {reason}")
                    output_file.unlink(missing_ok=True)
                    retry_count += 1
                    if retry_count < max_retries and not STOP_EVENT:
                        logging.info(f"Retrying recording ({retry_count}/{max_retries})...")
                        if streamer:
                            is_live, new_hls_url = is_stream_live(streamer, cookies_file, retry_delay, quality)
                            if not is_live:
                                logging.info("Stream is no longer live, stopping retries.")
                                break
                            hls_url = new_hls_url
                        time.sleep(retry_delay)
                        output_file = get_unique_filename(output_file.with_suffix(''), ".ts")
                        logging.info(f"New output file: {output_file}")
                        continue
            else:
                logging.warning(f"Recording file missing: {output_file}")
                retry_count += 1
                if retry_count < max_retries and not STOP_EVENT:
                    logging.info(f"Retrying recording ({retry_count}/{max_retries})...")
                    if streamer:
                        is_live, new_hls_url = is_stream_live(streamer, cookies_file, retry_delay, quality)
                        if not is_live:
                            logging.info("Stream is no longer live, stopping retries.")
                            break
                        hls_url = new_hls_url
                    time.sleep(retry_delay)
                    output_file = get_unique_filename(output_file.with_suffix(''), ".ts")
                    logging.info(f"New output file: {output_file}")
                    continue
        except subprocess.TimeoutExpired:
            logging.warning("Recording process timed out during cleanup")
            PROCESS.kill()
        except Exception as e:
            logging.error(f"Error during process cleanup: {e}")
        finally:
            PROCESS = None
        if STOP_EVENT:
            break
    
    if retry_count >= max_retries:
        logging.error(f"Max retries ({max_retries}) reached, giving up on recording.")

def signal_handler(sig, frame):
    global STOP_EVENT, PROCESS
    if STOP_EVENT:
        return
    STOP_EVENT = True
    logging.info("Termination signal received. Waiting for recording to complete...")

def main():
    global args, STOP_EVENT, PROCESS
    args = parse_args()
    config = load_config(SCRIPT_DIR / "config.ini")
    
    signal.signal(signal.SIGINT, signal_handler)
    streamer = select_streamer(args, args.streamers_file) if not args.hls_url else None
    setup_logging(args.debug, streamer)
    check_dependencies()
    check_disk_space(SCRIPT_DIR)
    
    cookies_file = SCRIPT_DIR / "cookies.txt"
    if not cookies_file.exists():
        logging.error("Cookies file not found: cookies.txt")
        sys.exit(1)
    
    cookies = parse_cookies(cookies_file)
    
    sanitized_streamer = sanitize_filename(streamer) if streamer else None
    save_folder = SCRIPT_DIR / sanitized_streamer if streamer else SCRIPT_DIR
    save_folder.mkdir(parents=True, exist_ok=True)
    
    check_interval = float(config["check_interval"])
    retry_delay = float(config["retry_delay"])
    
    if args.hls_url:
        logging.info("Recording direct HLS URL")
        date = datetime.now().strftime("%Y-%m-%d")
        filename = f"{datetime.strptime(date, '%Y-%m-%d').strftime('[%Y%m%d]')}_Direct_Recording"
        ts_file = get_unique_filename(save_folder / filename, ".ts")
        logging.info(f"Writing file {ts_file.name}")
        record_stream(args.hls_url, ts_file, cookies_file, args.quality, streamer=streamer)
        if ts_file.exists():
            logging.info(f"File saved as: {ts_file}")
        if STOP_EVENT and not args.fast_exit:
            logging.info("Waiting for recording cleanup before exit...")
            time.sleep(2)
        sys.exit(0)
    
    logging.info(f"Monitoring streamer: {streamer}")
    
    while not STOP_EVENT:
        is_live, hls_url = is_stream_live(streamer, cookies_file, retry_delay, args.quality)
        if is_live and not STOP_EVENT:
            logging.info(f"Stream is live: {streamer}")
            title, stream_id, thumbnail_url = fetch_metadata(streamer, hls_url)
            date = datetime.now().strftime("%Y-%m-%d")
            filename = generate_filename(title, streamer, stream_id, date)
            
            ts_file = get_unique_filename(save_folder / filename, ".ts")
            thumbnail_file = ts_file.with_suffix(".jpg") if thumbnail_url else None
            
            if thumbnail_url:
                download_thumbnail(thumbnail_url, thumbnail_file)
            
            record_stream(hls_url, ts_file, cookies_file, args.quality, streamer=streamer)
            
            if ts_file.exists():
                size_bytes = ts_file.stat().st_size
                duration = get_stream_duration(ts_file)
                logging.info(f"Recording saved: {ts_file} ({size_bytes / 1024:.2f} KB, {duration}s)")
            else:
                logging.warning(f"Recording file missing: {ts_file}")
            
            logging.info("Waiting before next stream check...")
            time.sleep(check_interval)
        else:
            time.sleep(check_interval)
        
        if STOP_EVENT:
            logging.info("Exiting main loop after recording completion...")
            if PROCESS and not args.fast_exit:
                logging.info("Waiting for recording cleanup before exit...")
                try:
                    PROCESS.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    logging.warning("Recording process did not terminate in time, forcing exit")
                    PROCESS.kill()
            break
    
    sys.exit(0)

if __name__ == "__main__":
    main()
