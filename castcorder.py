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
import psutil
import configparser

# Global variables
STOP_EVENT = False
PROCESS = None
SCRIPT_DIR = Path(__file__).parent  # Directory of the script

# Sanitize filename for file system compatibility
def sanitize_filename(name):
    invalid_chars = r'[<>:"/\\|?*]'
    return re.sub(invalid_chars, "_", name)

# Setup logging
def setup_logging(debug, streamer=None):
    sanitized_streamer = sanitize_filename(streamer) if streamer else None
    log_file = SCRIPT_DIR / (f"twitcast_recorder_direct.log" if not streamer else f"{sanitized_streamer}/twitcast_recorder_{sanitized_streamer}.log")
    if sanitized_streamer:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Custom logging handler to update console with \r for "Stream offline"
    class StreamOfflineHandler(logging.StreamHandler):
        def emit(self, record):
            if "Stream offline" in record.msg:
                print(f"\r{self.format(record)}", end="", file=sys.stdout)
                sys.stdout.flush()
            else:
                print(f"\n{self.format(record)}", file=sys.stdout)
                sys.stdout.flush()
    
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s,%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            StreamOfflineHandler()
        ]
    )

# Check dependencies
def check_dependencies():
    required = ["ffmpeg", "yt-dlp"]
    missing = []
    for tool in required:
        if not shutil.which(tool):
            missing.append(tool)
    if missing:
        logging.error(f"Missing dependencies: {', '.join(missing)}")
        sys.exit(1)
    try:
        import psutil
    except ImportError:
        logging.warning("Optional dependency 'psutil' missing. Some features may be limited.")

# Load configuration
def load_config(config_file):
    config = configparser.ConfigParser()
    config.read(config_file)
    defaults = {
        "check_interval": os.getenv("CHECK_INTERVAL", "15"),
        "retry_delay": os.getenv("RETRY_DELAY", "15"),
        "twitcasting_username": os.getenv("TWITCASTING_USERNAME", ""),
        "twitcasting_password": os.getenv("TWITCASTING_PASSWORD", ""),
        "private_stream_password": os.getenv("PRIVATE_STREAM_PASSWORD", ""),
        "hls_url": os.getenv("HLS_URL", "")
    }
    if "recorder" in config:
        defaults.update(config["recorder"])
    return defaults

# Parse arguments
def parse_args():
    parser = argparse.ArgumentParser(description="TwitCasting Stream Recorder")
    parser.add_argument("--streamer", help="Streamer username")
    parser.add_argument("--quality", default="best", help="Stream quality (default: best)")
    parser.add_argument("--streamers-file", type=Path, default=SCRIPT_DIR / "streamers.txt", help="File containing streamer usernames")
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging")
    parser.add_argument("--fast-exit", action="store_true", help="Skip cleanup on exit")
    parser.add_argument("--hls-url", help="Direct HLS URL to record")
    return parser.parse_args()

# Validate streamer username
def validate_streamer(streamer):
    if not re.match(r"^[a-zA-Z0-9_:]+$", streamer):
        logging.error(f"Invalid streamer username: {streamer}")
        sys.exit(1)
    return streamer

# Select streamer
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

# Check disk space
def check_disk_space(save_folder, min_space_gb=5):
    total, used, free = shutil.disk_usage(save_folder)
    free_gb = free / (1024 ** 3)
    if free_gb < min_space_gb:
        logging.error(f"Insufficient disk space: {free_gb:.2f} GB available, {min_space_gb} GB required")
        sys.exit(1)

# Fetch stream metadata
def fetch_metadata(streamer, hls_url=None):
    url = f"https://twitcasting.tv/{streamer}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36",
        "Referer": "https://twitcasting.tv/",
        "Origin": "https://twitcasting.tv/"
    }
    stream_id = "unknown"
    
    if hls_url:
        stream_id_match = re.search(r'movie_id=(\d+)|/movie/(\d+)|movieid/(\d+)|/streams/(\d+)', hls_url)
        if stream_id_match:
            stream_id = next((g for g in stream_id_match.groups() if g), "unknown")
            logging.debug(f"Extracted stream_id from HLS URL: {stream_id}")
        else:
            logging.warning(f"Could not extract stream_id from HLS URL: {hls_url}")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
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

# Download thumbnail
def download_thumbnail(thumbnail_url, save_path):
    if not thumbnail_url:
        return False
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36"
        }
        response = requests.get(thumbnail_url, headers=headers, timeout=10)
        response.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(response.content)
        return True
    except Exception as e:
        logging.warning(f"Failed to download thumbnail: {e}")
        return False

# Generate safe filename
def generate_filename(title, streamer, stream_id, date):
    unsafe_chars = r'[<>:"/\\|?*]'
    title = re.sub(unsafe_chars, "_", title)
    formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("[%Y%m%d]")
    filename = f"{formatted_date} {title} [{streamer}] [{stream_id}]"
    return filename[:255]

# Get unique filename
def get_unique_filename(base_path, ext):
    path = base_path.with_suffix(ext)
    if not path.exists():
        return path
    i = 2
    while True:
        new_path = base_path.with_name(f"{base_path.stem}_{i}{ext}")
        if not new_path.exists():
            return new_path
        i += 1

# Check if stream is live
def is_stream_live(streamer, cookies_file, retry_delay):
    cmd = [
        "yt-dlp",
        "--get-url",
        "--hls-use-mpegts",
        "--cookies", str(cookies_file),
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36",
        "--add-header", "Referer:https://twitcasting.tv/",
        "--add-header", "Origin:https://twitcasting.tv/",
        f"https://twitcasting.tv/{streamer}"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            logging.info(f"Successfully used cookies from {cookies_file} for {streamer}")
            return True, result.stdout.strip()
        if "401" in result.stderr or "unauthorized" in result.stderr.lower():
            logging.error("Authentication error: Check cookies or credentials")
        logging.info(f"Stream offline: {streamer}, retrying in {retry_delay} seconds")
        return False, None
    except subprocess.SubprocessError as e:
        logging.warning(f"Stream check failed: {e}")
        logging.info(f"Stream offline: {streamer}, retrying in {retry_delay} seconds")
        time.sleep(retry_delay)
        return False, None

# Get stream duration using ffprobe
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

# Repair incomplete MP4 files
def repair_mp4(mp4_file):
    repaired_file = mp4_file.with_suffix(".repaired.mp4")
    cmd = ["ffmpeg", "-i", str(mp4_file), "-c", "copy", "-map", "0", "-movflags", "faststart", str(repaired_file)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        mp4_file.unlink()
        shutil.move(repaired_file, mp4_file)
        logging.info(f"Repaired MP4 file: {mp4_file}")
    except subprocess.SubprocessError as e:
        logging.warning(f"Failed to repair MP4 file: {e}")

# Record stream
def record_stream(hls_url, output_file, cookies_file, quality):
    global PROCESS
    logging.info(f"Recording HLS URL: {hls_url}")
    
    # Command to execute yt-dlp for recording the stream
    cmd = [
        "yt-dlp",
        "--hls-use-mpegts",
        "--xattrs",
        "--ignore-no-formats-error",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36",
        "--cookies", str(cookies_file),
        "--add-header", "Referer:https://twitcasting.tv/",
        "--add-header", "Origin:https://twitcasting.tv/",
        "-f", quality,
        "--ffmpeg-location", shutil.which("ffmpeg"),
        "--output", str(output_file),
        "--progress",
        "--hls-prefer-ffmpeg",
        "--no-part",
        "--postprocessor-args", "-movflags frag_keyframe+empty_moov -f mp4",
        hls_url
    ]
    
    # Start the yt-dlp process
    try:
        PROCESS = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
    except subprocess.SubprocessError as e:
        logging.error(f"Failed to start recording process: {e}")
        return
    
    start_time = time.time()
    last_progress = ""
    # Regex to parse yt-dlp progress output
    progress_re = re.compile(r"frame=\s*\d+\s+fps=\s*[\d.]+.*size=\s*(\d+)KiB\s+time=(\d{2}):(\d{2}):(\d{2})\.\d+\s+bitrate=\s*([\d.]+)kbits/s")
    
    # Monitor process output
    while PROCESS.poll() is None:
        try:
            line = PROCESS.stderr.readline().strip()
            if line:
                match = progress_re.search(line)
                if match:
                    size_kib, hours, minutes, seconds, bitrate = match.groups()
                    try:
                        size_kib = int(size_kib)
                        hours, minutes, seconds = int(hours), int(minutes), int(seconds)
                        size_gb = size_kib / (1024 ** 2)  # Convert KiB to GiB
                        duration_str = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
                        bitrate_float = float(bitrate)  # Convert bitrate string to float
                        progress = f"size {size_gb:.2f}gb @ {duration_str} {bitrate_float:.0f}kb/s"
                        print(f"\r{progress:<{len(last_progress)}}", end="", file=sys.stdout)
                        sys.stdout.flush()
                        last_progress = progress
                    except ValueError as e:
                        logging.warning(f"Invalid progress data: {line}. Error: {e}")
                        continue
                else:
                    logging.debug(f"yt-dlp output: {line}")
            if STOP_EVENT:
                PROCESS.terminate()
                logging.info("Recording stopped due to termination signal")
                break
        except Exception as e:
            logging.error(f"Error reading process output: {e}")
            break
    
    end_time = time.time()
    # Clear the last progress line
    print(f"\r{' ' * len(last_progress)}", end="\r", file=sys.stdout)
    sys.stdout.flush()
    
    # Handle process completion
    try:
        stdout, stderr = PROCESS.communicate(timeout=10)
        for line in stdout.splitlines():
            if line.strip():
                logging.info(f"yt-dlp stdout: {line.strip()}")
        for line in stderr.splitlines():
            if line.strip():
                logging.debug(f"yt-dlp stderr: {line.strip()}")
        
        if PROCESS.returncode != 0:
            logging.error(f"Recording failed with return code {PROCESS.returncode}: {stderr}")
        elif output_file.exists():
            size_bytes = output_file.stat().st_size
            size_gib = size_bytes / (1024 ** 3)
            duration = get_stream_duration(output_file)
            if duration == 0:
                duration = int(end_time - start_time)
                logging.debug(f"Using elapsed time as duration: {duration} seconds")
            duration_str = f"{duration//3600:02d}h {(duration%3600)//60:02d}m {duration%60:02d}s"
            speed_kib_s = (size_bytes / 1024) / duration if duration > 0 else 0
            logging.info(f"Recording completed Size: {size_gib:.2f} GiB ({duration_str} @ {speed_kib_s:.2f} KiB/s)")
        else:
            logging.warning(f"Recording file missing: {output_file}")
    except subprocess.TimeoutExpired:
        logging.warning("Recording process timed out during cleanup")
        PROCESS.kill()
    except Exception as e:
        logging.error(f"Error during process cleanup: {e}")
    finally:
        PROCESS = None

# Convert to MKV and embed metadata
def convert_to_mkv(mp4_file, mkv_file, metadata, thumbnail_file):
    cmd = [
        "ffmpeg",
        "-i", str(mp4_file),
        "-c", "copy",
        "-metadata", f"title={metadata['title']}",
        "-metadata", f"artist={metadata['streamer']}",
        "-metadata", f"date={metadata['date']}",
        "-metadata", f"comment=Stream ID: {metadata['stream_id']}"
    ]
    if thumbnail_file and thumbnail_file.exists():
        cmd.extend(["-attach", str(thumbnail_file), "-metadata:s:t", "mimetype=image/jpeg"])
    cmd.append(str(mkv_file))
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        mp4_file.unlink()
        if thumbnail_file and thumbnail_file.exists():
            thumbnail_file.unlink()
        logging.info(f"Converted to MKV: {mkv_file}")
    except subprocess.SubprocessError as e:
        logging.error(f"Conversion failed: {e}")
        raise  # Raise exception to be handled by caller

# Signal handler
def signal_handler(sig, frame):
    global STOP_EVENT, PROCESS
    if STOP_EVENT:
        return
    STOP_EVENT = True
    logging.info("Termination signal received. Cleaning up...")
    if PROCESS:
        try:
            parent = psutil.Process(PROCESS.pid)
            for child in parent.children(recursive=True):
                child.terminate()
            PROCESS.terminate()
        except psutil.NoSuchProcess:
            pass
        if not args.fast_exit:
            time.sleep(2)
            try:
                PROCESS.kill()
            except subprocess.SubprocessError:
                pass
    sys.exit(0)

# Main function
def main():
    global args
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
    
    sanitized_streamer = sanitize_filename(streamer) if streamer else None
    save_folder = SCRIPT_DIR / sanitized_streamer if streamer else SCRIPT_DIR
    save_folder.mkdir(parents=True, exist_ok=True)
    
    check_interval = float(config["check_interval"])
    retry_delay = float(config["retry_delay"])
    
    if args.hls_url:
        logging.info("Recording direct HLS URL")
        date = datetime.now().strftime("%Y-%m-%d")
        filename = f"{datetime.strptime(date, '%Y-%m-%d').strftime('[%Y%m%d]')}_Direct_Recording"
        mp4_file = get_unique_filename(save_folder / filename, ".mp4")
        mkv_file = mp4_file.with_suffix(".mkv")
        metadata = {
            "title": "Direct Recording",
            "streamer": "Unknown",
            "date": date,
            "stream_id": "direct"
        }
        record_stream(args.hls_url, mp4_file, cookies_file, args.quality)
        if mp4_file.exists():
            repair_mp4(mp4_file)
            try:
                convert_to_mkv(mp4_file, mkv_file, metadata, None)
            except Exception as e:
                logging.error(f"Conversion failed: {e}")
                backup_folder = save_folder / "backup"
                backup_folder.mkdir(exist_ok=True)
                shutil.move(mp4_file, get_unique_filename(backup_folder / mp4_file.name, ".mp4"))
        sys.exit(0)
    
    logging.info(f"Monitoring streamer: {streamer}")
    
    while not STOP_EVENT:
        is_live, hls_url = is_stream_live(streamer, cookies_file, retry_delay)
        if is_live and not STOP_EVENT:
            logging.info(f"Stream is live: {streamer}")
            title, stream_id, thumbnail_url = fetch_metadata(streamer, hls_url)
            date = datetime.now().strftime("%Y-%m-%d")
            filename = generate_filename(title, streamer, stream_id, date)
            
            mp4_file = get_unique_filename(save_folder / filename, ".mp4")
            mkv_file = mp4_file.with_suffix(".mkv")
            thumbnail_file = mp4_file.with_suffix(".jpg") if thumbnail_url else None
            
            if thumbnail_url:
                download_thumbnail(thumbnail_url, thumbnail_file)
            
            metadata = {
                "title": title,
                "streamer": streamer,
                "date": date,
                "stream_id": stream_id
            }
            
            record_stream(hls_url, mp4_file, cookies_file, args.quality)
            
            if mp4_file.exists():
                size_bytes = mp4_file.stat().st_size
                duration = get_stream_duration(mp4_file)
                logging.info(f"Processing file: {mp4_file} ({size_bytes / 1024:.2f} KB, {duration}s)")
                repair_mp4(mp4_file)
                try:
                    convert_to_mkv(mp4_file, mkv_file, metadata, thumbnail_file)
                except Exception as e:
                    logging.error(f"Conversion failed: {e}")
                    backup_folder = save_folder / "backup"
                    backup_folder.mkdir(exist_ok=True)
                    shutil.move(mp4_file, get_unique_filename(backup_folder / mp4_file.name, ".mp4"))
            else:
                logging.warning(f"Recording file missing: {mp4_file}")
            
            logging.info("Waiting before next stream check...")
            time.sleep(check_interval)
        else:
            time.sleep(check_interval)

if __name__ == "__main__":
    main()
