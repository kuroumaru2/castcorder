#!/usr/bin/env python3
import sys
import os
import subprocess
import time
import json
import logging
from datetime import datetime
import threading
import re
import signal
import argparse
import platform
import random
import shutil

# Optional psutil for better process management
try:
    import psutil
except ImportError:
    psutil = None
    print("psutil not installed. Enhanced process termination disabled.")

# Added tqdm import with fallback
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None
    print("tqdm not installed. Progress bar will be disabled.")

# Ensure unbuffered stdout and stderr for real-time console updates
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Enable ANSI support on Windows
if sys.platform == "win32":
    os.system("color")

# Global termination lock to prevent reentrant signal handler
termination_lock = threading.Lock()

# Custom StreamHandler to handle Unicode characters
class UnicodeSafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            self.stream.write(msg + self.terminator)
            self.flush()
        except UnicodeEncodeError:
            msg = self.format(record).encode('ascii', 'replace').decode('ascii')
            self.stream.write(msg + self.terminator)
            self.flush()

# StreamRecorder class to encapsulate state
class StreamRecorder:
    def __init__(self, streamer_url, save_folder, log_file, quality="best", use_progress_bar=False, timeout=25200):
        self.terminating = False
        self.process = None
        self.stop_event = None
        self.progress_thread = None
        self.current_mp4_file = None
        self.current_thumbnail_path = None
        self.last_streamlink_check_success = False
        self.cleaned_up = False
        self.watchdog_stop_event = threading.Event()
        self.lock = threading.Lock()
        self.streamer_url = streamer_url
        self.save_folder = save_folder
        self.log_file = log_file
        self.quality = quality
        self.use_progress_bar = use_progress_bar
        self.check_interval = int(os.environ.get('CHECK_INTERVAL', 15))
        self.retry_delay = int(os.environ.get('RETRY_DELAY', 15))
        self.streamlink_timeout = int(os.environ.get('STREAMLINK_TIMEOUT', timeout))

    def setup_logging(self, debug=False):
        """Set up logging with file and console handlers, avoiding duplicates."""
        logger = logging.getLogger(__name__)
        logger.handlers = []
        logger.setLevel(logging.DEBUG if debug else logging.INFO)
        logger.propagate = False
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        console_handler = UnicodeSafeStreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.debug(f"Logger handlers after setup: {len(logger.handlers)} ({[type(h).__name__ for h in logger.handlers]})")
        return logger

# Check dependencies
def check_streamlink():
    try:
        subprocess.run(["streamlink", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("Streamlink is installed and accessible")
    except FileNotFoundError:
        logger.error("Streamlink is not installed or not in PATH. Please install Streamlink.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error checking Streamlink: {e}")
        sys.exit(1)

def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("FFmpeg is installed and accessible")
    except FileNotFoundError:
        logger.error("FFmpeg is not installed or not in PATH. Please install FFmpeg.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error checking FFmpeg: {e}")
        sys.exit(1)

def check_ytdlp():
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("yt-dlp is installed and accessible")
    except FileNotFoundError:
        logger.error("yt-dlp is not installed or not in PATH. Please install yt-dlp.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error checking yt-dlp: {e}")
        sys.exit(1)

# Read streamers from file
def read_streamers(file_path="streamers.txt"):
    if not os.path.exists(file_path):
        logger.error(f"Streamers file '{file_path}' not found.")
        sys.exit(1)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            streamers = [line.strip() for line in f if line.strip()]
        if not streamers:
            logger.error(f"Streamers file '{file_path}' is empty.")
            sys.exit(1)
        return streamers
    except UnicodeDecodeError:
        logger.error(f"Failed to decode {file_path} as UTF-8. Trying fallback encoding.")
        with open(file_path, 'r', encoding='latin1') as f:
            streamers = [line.strip() for line in f if line.strip()]
        return streamers
    except Exception as e:
        logger.error(f"Error reading streamers file '{file_path}': {e}")
        sys.exit(1)

# Select streamer
def select_streamer(streamers, arg=None):
    if arg and arg in streamers:
        return arg
    elif arg:
        logger.warning(f"Streamer '{arg}' not found in streamers.txt. Prompting for selection.")
    print("Available streamers:")
    for i, streamer in enumerate(streamers, 1):
        print(f"{i}. {streamer}")
    while True:
        try:
            choice = input("Enter the number of the streamer to record: ")
            index = int(choice) - 1
            if 0 <= index < len(streamers):
                return streamers[index]
            else:
                print(f"Please enter a number between 1 and {len(streamers)}.")
        except ValueError:
            print("Please enter a valid number.")

# Safe filename generation
def safe_filename(filename):
    max_length = 200
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    return filename[:max_length]

# Check disk space
def check_disk_space(path, min_space_mb=100):
    try:
        stat = shutil.disk_usage(path)
        free_mb = stat.free / (1024 * 1024)
        if free_mb < min_space_mb:
            logger.error(f"Insufficient disk space at {path}: {free_mb:.2f} MB free, {min_space_mb} MB required.")
            sys.exit(1)
        logger.debug(f"Disk space check: {free_mb:.2f} MB free at {path}")
    except Exception as e:
        logger.warning(f"Failed to check disk space at {path}: {e}")

# Parse command-line arguments
def parse_args():
    parser = argparse.ArgumentParser(description="TwitCasting Stream Recorder")
    parser.add_argument("--streamer", help="Streamer username")
    parser.add_argument("--quality", default="best", help="Stream quality (default: best)")
    parser.add_argument("--save-folder", default=os.path.dirname(os.path.abspath(__file__)),
                        help="Base folder for saving recordings")
    parser.add_argument("--streamers-file", default="streamers.txt", help="Path to streamers file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--progress-bar", action="store_true", help="Enable tqdm progress bar (may not work in all terminals)")
    parser.add_argument("--timeout", type=int, default=25200, help="Streamlink timeout in seconds (default: 25200)")
    parser.add_argument("--fast-exit", action="store_true", help="Force instant exit on Ctrl+C (skips cleanup, may leave temporary files)")
    parser.add_argument("--no-watchdog", action="store_true", help="Disable watchdog thread for testing")
    parser.add_argument("--hls-url", help="HLS URL to record (e.g., https://example.com/stream.m3u8). Overrides automatic fetching.")
    return parser.parse_args()

# Extract stream ID from HLS URL
def extract_stream_id_from_hls_url(hls_url):
    """Extract the stream ID from the HLS URL."""
    match = re.search(r'/streams/(\d+)/', hls_url)
    if match:
        return match.group(1)
    logger.warning(f"Could not extract stream ID from HLS URL: {hls_url}")
    return None

# Fetch HLS URL using yt-dlp
def fetch_hls_url(streamer_url, cookies=None):
    """Fetch the HLS URL using yt-dlp."""
    logger.debug(f"Attempting to fetch HLS URL for {streamer_url} using yt-dlp")
    cmd = [
        "yt-dlp", "--get-url", streamer_url,
        "--add-header", "Referer:https://twitcasting.tv/",
        "--add-header", "Origin:https://twitcasting.tv/"
    ]
    
    # Add cookies if provided
    cookies_file = None
    if cookies:
        cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
        try:
            with open(cookies_file, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for cookie in cookies.split(';'):
                    if cookie.strip():
                        try:
                            name, value = cookie.strip().split('=', 1)
                            # Skip problematic cookies (e.g., Google Analytics)
                            if name.startswith('_ga') or '.' in value:
                                logger.debug(f"Skipping cookie '{name}' due to potential parsing issues")
                                continue
                            # Sanitize value to remove problematic characters
                            value = re.sub(r'[^\w\-]', '_', value)
                            f.write(f".twitcasting.tv\tTRUE\t/\tFALSE\t0\t{name}\t{value}\n")
                        except ValueError:
                            logger.warning(f"Invalid cookie format: {cookie}")
            cmd.extend(["--cookies", cookies_file])
            logger.debug(f"Wrote cookies to {cookies_file}")
        except Exception as e:
            logger.warning(f"Failed to write cookies file: {e}")
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode == 0:
            hls_url = stdout.strip()
            if re.match(r'^https?://.*\.(m3u8|mp4)$', hls_url):
                logger.info(f"Fetched HLS URL using yt-dlp: {hls_url}")
                return hls_url
            else:
                logger.warning(f"yt-dlp returned invalid HLS URL: {hls_url}")
                return None
        else:
            logger.error(f"yt-dlp failed to fetch URL: {stderr}")
            return None
    except subprocess.TimeoutExpired:
        logger.error("yt-dlp timed out while fetching HLS URL")
        if process:
            process.terminate()
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                logger.warning("Failed to terminate yt-dlp process")
        return None
    except subprocess.SubprocessError as e:
        logger.error(f"Subprocess error while running yt-dlp: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching HLS URL with yt-dlp: {e}")
        return None
    finally:
        if cookies_file and os.path.exists(cookies_file):
            try:
                os.remove(cookies_file)
                logger.debug(f"Deleted temporary cookies file: {cookies_file}")
            except Exception as e:
                logger.warning(f"Failed to delete cookies file: {e}")

# Main execution
if __name__ == "__main__":
    args = parse_args()
    QUALITY = args.quality
    BASE_SAVE_FOLDER = args.save_folder
    STREAMERS_FILE = args.streamers_file
    USE_PROGRESS_BAR = args.progress_bar
    TIMEOUT = args.timeout
    FAST_EXIT = args.fast_exit
    NO_WATCHDOG = args.no_watchdog
    HLS_URL = args.hls_url or os.environ.get('HLS_URL')

    # Initialize logger with null handler
    logger = logging.getLogger(__name__)
    logger.addHandler(logging.NullHandler())

    # Log command-line arguments
    logger.debug(f"Command-line arguments: {vars(args)}")

    # Detect terminal type
    is_cmd = os.environ.get('COMSPEC', '').lower().endswith('cmd.exe')
    logger.info(f"Terminal: {'CMD' if is_cmd else 'Other'}, Interactive: {sys.stderr.isatty()}")
    if is_cmd and USE_PROGRESS_BAR:
        logger.warning("CMD terminal detected. Progress bar may not display correctly. Use --progress-bar in PowerShell.")
    if not sys.stderr.isatty():
        logger.warning("Non-interactive terminal detected. Progress updates may not display correctly.")
    if not USE_PROGRESS_BAR and is_cmd:
        logger.info("Progress bar disabled due to CMD terminal. Use --progress-bar to enable.")

    # Check dependencies
    check_streamlink()
    check_ffmpeg()
    check_ytdlp()

    # Read streamers and select one
    streamers = read_streamers(STREAMERS_FILE)
    selected_streamer = select_streamer(streamers, args.streamer)

    # Validate streamer username
    if not re.match(r'^[a-zA-Z0-9_:]+$', selected_streamer):
        logger.error(f"Invalid streamer username: {selected_streamer}. Must contain only letters, numbers, underscores, or colons.")
        sys.exit(1)

    # Setup streamer-specific paths
    from urllib.parse import quote
    STREAMER_URL = f"https://twitcasting.tv/{selected_streamer}"
    streamer_name = selected_streamer.replace(':', '_')
    SAVE_FOLDER = os.path.join(BASE_SAVE_FOLDER, streamer_name)
    LOG_FILE = os.path.join(SAVE_FOLDER, f"{streamer_name}_twitcasting_recorder.log")

    # Create save folder and check disk space
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    check_disk_space(SAVE_FOLDER)

    # Initialize recorder
    recorder = StreamRecorder(STREAMER_URL, SAVE_FOLDER, LOG_FILE, QUALITY, USE_PROGRESS_BAR, TIMEOUT)
    logger = recorder.setup_logging(debug=args.debug)

    # Log script info
    SCRIPT_VERSION = "v2025.05.05.09"
    logger.info(f"Running script version: {SCRIPT_VERSION}")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"tqdm available: {tqdm is not None}")
    logger.info(f"psutil available: {psutil is not None}")

    # Set UTF-8 encoding
    os.environ["PYTHONIOENCODING"] = "utf-8"

    # Check for shadowing files
    for shadow_file in ["requests.py", "bs4.py"]:
        if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), shadow_file)):
            logger.error(f"Found '{shadow_file}' in script directory, which shadows a required module. Please rename or remove it.")
            sys.exit(1)

    # Import requests and BeautifulSoup
    try:
        import requests
        logger.info(f"Successfully imported requests from {requests.__file__}")
    except ImportError as e:
        logger.error(f"Failed to import requests: {e}")
        requests = None

    try:
        from bs4 import BeautifulSoup
        logger.info(f"Successfully imported BeautifulSoup from {BeautifulSoup.__module__}")
    except ImportError as e:
        logger.error(f"Failed to import BeautifulSoup: {e}")
        BeautifulSoup = None

    # TwitCasting credentials
    TWITCASTING_USERNAME = os.environ.get('TWITCASTING_USERNAME')
    TWITCASTING_PASSWORD = os.environ.get('TWITCASTING_PASSWORD')
    PRIVATE_STREAM_PASSWORD = os.environ.get('PRIVATE_STREAM_PASSWORD')
    TWITCASTING_COOKIES = os.environ.get('TWITCASTING_COOKIES', '')
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36"

    def login_to_twitcasting(username, password):
        if not requests or not BeautifulSoup:
            logger.error("Cannot log in: requests or BeautifulSoup module is not available")
            return None
        login_url = "https://twitcasting.tv/indexpasswordlogin.php?redir=%2Findexloginwindow.php%3Fnext%3D%252F"
        session = requests.Session()
        try:
            response = session.get(login_url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            csrf_token = soup.find("input", {"name": "csrf_token"})
            csrf_value = csrf_token["value"] if csrf_token else ""
            login_data = {
                "username": username,
                "password": password,
                "csrf_token": csrf_value,
            }
            login_response = session.post(login_url, data=login_data, timeout=10)
            login_response.raise_for_status()
            if "login" in login_response.url or "error" in login_response.text.lower():
                logger.error("Login failed: Invalid credentials or CAPTCHA required")
                return None
            cookies = session.cookies.get_dict()
            if "twitcasting_sess" not in cookies:
                logger.error("Login failed: twitcasting_sess cookie not found")
                return None
            logger.info("Login successful. Retrieved cookies.")
            return [f"{key}={value}" for key, value in cookies.items()]
        except requests.RequestException as e:
            logger.error(f"Login error: {e}")
            return None

    def is_stream_live(recorder):
        max_retries_per_cycle = 10
        original_handlers = logger.handlers[:]
        logger.handlers = [h for h in logger.handlers if not isinstance(h, (logging.StreamHandler, UnicodeSafeStreamHandler))]
        try:
            sys.stderr.write("\n")
            sys.stderr.flush()
            while not recorder.terminating:
                for attempt in range(max_retries_per_cycle):
                    cmd = [
                        "streamlink", "--json", recorder.streamer_url, recorder.quality,
                        "--http-header", f"User-Agent={DEFAULT_USER_AGENT}", "-v"
                    ]
                    if PRIVATE_STREAM_PASSWORD:
                        cmd.extend(["--twitcasting-password", PRIVATE_STREAM_PASSWORD])
                    if TWITCASTING_COOKIES:
                        for cookie in TWITCASTING_COOKIES.split(';'):
                            cookie = cookie.strip()
                            if cookie and '=' in cookie:
                                cmd.extend(["--http-cookie", cookie])
                            else:
                                logger.warning(f"Skipping invalid cookie: {cookie}")
                    process = None
                    try:
                        process = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            text=True,
                            encoding='utf-8'
                        )
                        stdout, _ = process.communicate(timeout=30)
                        recorder.last_streamlink_check_success = True
                        if process.returncode == 0:
                            stream_data = json.loads(stdout)
                            is_live = "error" not in stream_data
                            logger.info(f"Streamlink check: {'Live' if is_live else 'Offline'}")
                            
                            if is_live:
                                max_metadata_retries = 3
                                for metadata_attempt in range(max_metadata_retries):
                                    try:
                                        logger.debug(f"Fetching stream metadata (attempt {metadata_attempt + 1}/{max_metadata_retries})")
                                        title, stream_id, thumbnail_url = fetch_stream_info()
                                        
                                        if not title:
                                            logger.warning("Stream appears live but couldn't get valid title")
                                            if metadata_attempt < max_metadata_retries - 1:
                                                time.sleep(2)
                                                continue
                                            else:
                                                title = f"{streamer_name}'s TwitCasting Stream"
                                                logger.info(f"Using fallback title: {title}")
                                        
                                        if not stream_id:
                                            logger.warning("Stream appears live but couldn't get valid stream ID")
                                            if metadata_attempt < max_metadata_retries - 1:
                                                time.sleep(2)
                                                continue
                                            else:
                                                logger.error("Failed to get stream ID after all retries")
                                                return (False, None, None, None)
                                        
                                        logger.info(f"Got stream metadata - Title: '{title}', ID: {stream_id}")
                                        return (True, title, stream_id, thumbnail_url)
                                    except Exception as e:
                                        logger.error(f"Failed to fetch stream metadata: {e}")
                                        if metadata_attempt < max_metadata_retries - 1:
                                            logger.info(f"Retrying metadata fetch in 2 seconds...")
                                            time.sleep(2)
                                        else:
                                            return (False, None, None, None)
                            return (False, None, None, None)
                        else:
                            logger.debug(f"Streamlink check failed: {stdout}")
                            if attempt < max_retries_per_cycle - 1:
                                msg = f"Retrying in {recorder.retry_delay} seconds... (Attempt {attempt + 1}/{max_retries_per_cycle})"
                                sys.stderr.write(msg + "\r")
                                sys.stderr.flush()
                                time.sleep(recorder.retry_delay)
                    except subprocess.TimeoutExpired:
                        logger.error("Streamlink check timed out")
                        recorder.last_streamlink_check_success = False
                        if process:
                            process.terminate()
                            try:
                                process.wait(timeout=0.1)
                            except subprocess.TimeoutExpired:
                                logger.warning("Failed to terminate streamlink process")
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON decode error: {e}")
                        recorder.last_streamlink_check_success = False
                        if attempt < max_retries_per_cycle - 1:
                            time.sleep(recorder.retry_delay)
                    finally:
                        if process and process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=0.1)
                            except subprocess.TimeoutExpired:
                                logger.warning("Failed to terminate streamlink process")
                msg = f"All {max_retries_per_cycle} retries failed. Retrying in {recorder.retry_delay} seconds..."
                sys.stderr.write(msg + "\r")
                sys.stderr.flush()
                time.sleep(recorder.retry_delay)
        finally:
            logger.handlers = original_handlers
            sys.stderr.write("\n")
            sys.stderr.flush()
        return (False, None, None, None)

    def fetch_stream_info():
        """Fetch stream information including title, stream ID, and thumbnail URL."""
        title = f"{streamer_name}'s TwitCasting Stream"
        stream_id = None
        thumbnail_url = None
        
        if not requests or not BeautifulSoup:
            logger.warning("Cannot fetch stream info: requests or BeautifulSoup unavailable")
            return title, stream_id, thumbnail_url
            
        try:
            headers = {'User-Agent': DEFAULT_USER_AGENT}
            if TWITCASTING_COOKIES:
                headers['Cookie'] = TWITCASTING_COOKIES
                
            logger.debug(f"Fetching stream info from {STREAMER_URL}")
            response = requests.get(STREAMER_URL, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()
                logger.debug(f"Found stream title: {title}")
            else:
                logger.warning("Could not find stream title in page metadata")
                
            movie_link = soup.find("a", href=re.compile(r'/movie/\d+'))
            if movie_link:
                stream_id_match = re.search(r'/movie/(\d+)', movie_link["href"])
                if stream_id_match:
                    stream_id = stream_id_match.group(1)
                    logger.debug(f"Found stream ID from movie link: {stream_id}")
                else:
                    logger.warning("Movie link found but couldn't extract stream ID")
            else:
                logger.debug("Movie link not found, searching for stream ID in page scripts")
                script_tags = soup.find_all("script")
                for script in script_tags:
                    if script.string and "movieId" in script.string:
                        id_match = re.search(r'movieId["\']?\s*:\s*["\']?(\d+)["\']?', script.string)
                        if id_match:
                            stream_id = id_match.group(1)
                            logger.debug(f"Found stream ID from script: {stream_id}")
                            break
                
                if not stream_id:
                    logger.warning("Could not find stream ID in page content")
            
            og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
            if og_image and og_image.get("content") and og_image["content"].startswith("http"):
                thumbnail_url = og_image["content"]
                logger.debug(f"Found thumbnail URL: {thumbnail_url}")
            else:
                logger.debug("Could not find thumbnail URL")
                
        except requests.RequestException as e:
            logger.warning(f"Network error fetching stream info: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error fetching stream info: {e}")
            
        return title, stream_id, thumbnail_url

    def get_filename(title, stream_id, is_mkv=False):
        date_str = datetime.now().strftime("%Y%m%d")
        username = streamer_name
        title = safe_filename(title.strip())
        title = title[:50] if len(title) > 50 else title
        ext = "mkv" if is_mkv else "mp4"
        base_filename = f"[{date_str}] {title} [{username}][{stream_id}]"
        filename = f"{base_filename}.{ext}"
        full_path = os.path.join(SAVE_FOLDER, filename)
        counter = 2
        while os.path.exists(full_path):
            filename = f"{base_filename} ({counter}).{ext}"
            full_path = os.path.join(SAVE_FOLDER, filename)
            counter += 1
        return full_path

    def download_thumbnail(thumbnail_url):
        if not thumbnail_url or not requests:
            logger.warning("Cannot download thumbnail: unavailable")
            return None
        try:
            headers = {'User-Agent': DEFAULT_USER_AGENT}
            if TWITCASTING_COOKIES:
                headers['Cookie'] = TWITCASTING_COOKIES
            response = requests.get(thumbnail_url, headers=headers, timeout=5)
            response.raise_for_status()
            thumbnail_path = os.path.join(SAVE_FOLDER, "temp_thumbnail.jpg")
            with open(thumbnail_path, "wb") as f:
                f.write(response.content)
            if os.path.getsize(thumbnail_path) > 0:
                logger.info(f"Downloaded thumbnail to {thumbnail_path}")
                return thumbnail_path
            os.remove(thumbnail_path)
            return None
        except requests.RequestException as e:
            logger.warning(f"Failed to download thumbnail: {e}")
            return None

    def get_metadata(title):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "title": title,
            "artist": streamer_name,
            "date": timestamp.split()[0],
            "comment": f"Recorded from {STREAMER_URL} on {timestamp}"
        }

    def format_size(bytes_size):
        for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
            if bytes_size < 1024:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024
        return f"{bytes_size:.2f} PiB"

    def format_duration(seconds):
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes}m{seconds:02d}s"

    def monitor_file_progress(file_path, start_time, stop_event, progress_callback):
        last_size = 0
        progress_bar = None
        progress_counter = 0
        tqdm_lock = threading.Lock()
        max_file_access_retries = 5
        file_access_failures = 0
        file_creation_timeout = 60
        file_creation_start = time.time()

        if recorder.use_progress_bar and tqdm and not recorder.terminating:
            with tqdm_lock:
                try:
                    progress_bar = tqdm(
                        desc="Recording",
                        bar_format="{desc}: {postfix}",
                        postfix="Waiting for file creation",
                        leave=False,
                        dynamic_ncols=True
                    )
                except Exception as e:
                    logger.warning(f"Failed to initialize tqdm: {e}")
                    progress_bar = None
        else:
            logger.info("Progress bar disabled (tqdm unavailable, disabled, or terminating).")

        while not stop_event.is_set() and not recorder.terminating:
            try:
                if os.path.exists(file_path):
                    try:
                        current_size = os.path.getsize(file_path)
                        file_access_failures = 0
                        elapsed_time = time.time() - start_time
                        speed = (current_size - last_size) / 1024 / 5.0
                        total_size_str = format_size(current_size)
                        duration_str = format_duration(elapsed_time)
                        speed_str = f"{speed:.2f} KiB/s"
                        progress = f"Size: {total_size_str} ({duration_str} @ {speed_str})"
                        progress_callback(progress, progress_counter, progress_bar, tqdm_lock)
                        last_size = current_size
                    except OSError as e:
                        file_access_failures += 1
                        logger.debug(f"Error accessing file size {file_path}: {e} (Attempt {file_access_failures}/{max_file_access_retries})")
                        if file_access_failures >= max_file_access_retries:
                            logger.error(f"Max file access retries reached for {file_path}. Stopping progress updates.")
                            break
                        time.sleep(1)
                else:
                    elapsed = time.time() - file_creation_start
                    if elapsed > file_creation_timeout:
                        logger.error(f"File {file_path} not created after {file_creation_timeout} seconds. Stopping progress updates.")
                        break
                    progress = f"Waiting for file creation ({int(elapsed)}s)"
                    progress_callback(progress, progress_counter, progress_bar, tqdm_lock)
                progress_counter += 1
                check_disk_space(os.path.dirname(file_path))
            except Exception as e:
                logger.debug(f"Progress monitoring error: {e}")
            if stop_event.wait(timeout=5):
                break
        if progress_bar:
            with tqdm_lock:
                try:
                    progress_bar.close()
                    logger.debug("Progress bar closed successfully")
                except Exception as e:
                    logger.debug(f"Error closing progress bar: {e}")

    def print_progress(progress, counter, progress_bar, tqdm_lock):
        logger.debug(f"Progress update: {progress}")
        if progress_bar and not recorder.terminating:
            with tqdm_lock:
                try:
                    progress_bar.set_postfix_str(progress)
                    progress_bar.refresh()
                except Exception as e:
                    logger.debug(f"Error updating progress bar: {e}")
        else:
            sys.stderr.write(f"\rRecording: {progress.ljust(80)}")
            sys.stderr.flush()

    def convert_to_mkv_and_add_metadata(mp4_file, mkv_file, metadata, thumbnail_path=None):
        metadata_args = []
        for key, value in metadata.items():
            metadata_args.extend(["-metadata", f"{key}={value.replace(';', '')}"])
        cmd = [
            "ffmpeg", "-i", mp4_file, "-c", "copy", "-map", "0"
        ] + metadata_args
        if thumbnail_path:
            if os.path.exists(thumbnail_path):
                cmd.extend(["-attach", thumbnail_path, "-metadata:s:t", "mimetype=image/jpeg", "-metadata:s:t", "filename=thumbnail.jpg"])
            else:
                logger.warning(f"Thumbnail file {thumbnail_path} does not exist, skipping attachment")
        cmd.append(mkv_file)
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
            logger.info(f"Converted {mp4_file} to {mkv_file}")
            if os.path.exists(mkv_file) and os.path.getsize(mkv_file) > 0:
                os.remove(mp4_file)
                logger.info(f"Deleted original MP4 file: {mp4_file}")
            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
                logger.info(f"Deleted thumbnail: {thumbnail_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to convert to MKV: {e.stderr}")
        except Exception as e:
            logger.error(f"Error processing {mp4_file}: {e}")

    def cleanup_temp_files(recorder):
        with recorder.lock:
            if recorder.cleaned_up:
                logger.debug("Cleanup already performed")
                return
            logger.debug("Starting cleanup of temporary files")
            try:
                backup_folder = os.path.join(recorder.save_folder, "backup")
                os.makedirs(backup_folder, exist_ok=True)
                if recorder.current_thumbnail_path and os.path.exists(recorder.current_thumbnail_path):
                    backup_thumbnail_path = os.path.join(backup_folder, os.path.basename(recorder.current_thumbnail_path))
                    shutil.move(recorder.current_thumbnail_path, backup_thumbnail_path)
                    logger.info(f"Moved thumbnail to: {backup_thumbnail_path}")
                if recorder.current_mp4_file and os.path.exists(recorder.current_mp4_file):
                    if os.path.getsize(recorder.current_mp4_file) == 0:
                        os.remove(recorder.current_mp4_file)
                        logger.info(f"Deleted empty MP4: {recorder.current_mp4_file}")
                    else:
                        backup_mp4_path = os.path.join(backup_folder, os.path.basename(recorder.current_mp4_file))
                        shutil.move(recorder.current_mp4_file, backup_mp4_path)
                        logger.info(f"Moved partial MP4 to: {backup_mp4_path}")
            except Exception as e:
                logger.error(f"Error cleaning up: {e}")
            recorder.cleaned_up = True
            logger.debug("Cleanup completed")

    def force_kill_process(process):
        if not process:
            return
        try:
            pid = process.pid
            if psutil and psutil.pid_exists(pid):
                p = psutil.Process(pid)
                p.terminate()
                try:
                    p.wait(timeout=0.1)
                    logger.debug(f"Process {pid} terminated via psutil")
                except psutil.TimeoutExpired:
                    p.kill()
                    logger.warning(f"Process {pid} killed via psutil")
            else:
                process.terminate()
                try:
                    process.wait(timeout=0.1)
                    logger.debug(f"Process {pid} terminated")
                except subprocess.TimeoutExpired:
                    process.kill()
                    logger.warning(f"Process {pid} killed")
                    if sys.platform == "win32":
                        try:
                            os.kill(pid, signal.CTRL_C_EVENT)
                            logger.debug(f"Sent CTRL_C_EVENT to process {pid}")
                        except OSError as e:
                            logger.warning(f"Failed to send CTRL_C_EVENT: {e}")
        except psutil.NoSuchProcess:
            logger.warning(f"Process {pid} not found during termination")
        except Exception as e:
            logger.error(f"Error force-killing process {pid}: {e}")

    def signal_handler(sig, frame, recorder):
        start_time = time.time()
        with termination_lock:
            logger.debug("Signal handler started")
            if recorder.terminating:
                logger.warning("Received multiple Ctrl+C. Forcefully exiting...")
                if FAST_EXIT:
                    logger.debug("Fast exit triggered")
                    os._exit(1)
                sys.exit(1)
            recorder.terminating = True
            logger.info("Received Ctrl+C, stopping...")
            try:
                recorder.watchdog_stop_event.set()
                if recorder.stop_event:
                    recorder.stop_event.set()
                if recorder.progress_thread and recorder.progress_thread.is_alive():
                    logger.debug("Joining progress thread")
                    recorder.progress_thread.join(timeout=1.0)
                    if recorder.progress_thread.is_alive():
                        logger.warning("Progress thread did not exit cleanly")
                    else:
                        logger.debug("Progress thread joined")
                if recorder.process:
                    logger.debug("Terminating Streamlink subprocess")
                    force_kill_process(recorder.process)
                cleanup_temp_files(recorder)
                logger.info("Script stopped cleanly")
                sys.stderr.write("\n")
                sys.stderr.flush()
                logger.debug(f"Signal handler completed in {time.time() - start_time:.3f} seconds")
                if FAST_EXIT:
                    os._exit(0)
                sys.exit(0)
            except Exception as e:
                logger.error(f"Error in signal handler: {e}")
                sys.exit(1)

    def watchdog(recorder, timeout=3600):
        check_interval = 5
        last_size = 0
        no_progress_time = 0
        while not recorder.watchdog_stop_event.is_set():
            progress_detected = False
            if recorder.last_streamlink_check_success:
                no_progress_time = 0
                progress_detected = True
            elif recorder.current_mp4_file and os.path.exists(recorder.current_mp4_file):
                try:
                    current_size = os.path.getsize(recorder.current_mp4_file)
                    if current_size > last_size:
                        no_progress_time = 0
                        last_size = current_size
                        progress_detected = True
                    else:
                        no_progress_time += check_interval
                except Exception as e:
                    logger.debug(f"Watchdog error: {e}")
                    no_progress_time += check_interval
            else:
                no_progress_time = 0
                last_size = 0
                progress_detected = True
            if not progress_detected and no_progress_time >= timeout:
                logger.error(f"No progress for {timeout} seconds. Terminating.")
                os._exit(1)
            if recorder.watchdog_stop_event.wait(timeout=check_interval):
                break

    def record_stream(recorder):
        global HLS_URL
        while True:
            if recorder.terminating:
                break

            # If HLS_URL is provided or fetched, use it; otherwise, use WebSocket logic
            if HLS_URL:
                # Extract stream ID from HLS URL if possible
                stream_id = extract_stream_id_from_hls_url(HLS_URL)
                if stream_id:
                    logger.debug(f"Extracted stream ID from HLS URL: {stream_id}")
                else:
                    logger.warning("Could not extract stream ID from HLS URL, fetching from page")
                    stream_id = None

                # Fetch title and thumbnail, but use HLS stream ID if available
                title, _, thumbnail_url = fetch_stream_info()  # Ignore stream_id from page
                if not title:
                    logger.warning("Missing stream title, using default")
                    title = f"{streamer_name}'s HLS Stream"
                if not stream_id:
                    logger.warning("Using random stream ID due to missing ID in HLS URL and page")
                    stream_id = str(random.randint(1000000, 9999999))
                logger.info(f"Ready to record HLS stream - Title: '{title}', ID: {stream_id}")
                url = HLS_URL
            else:
                is_live, title, stream_id, thumbnail_url = is_stream_live(recorder)
                if not is_live:
                    logger.info(f"Stream offline. Checking in {recorder.check_interval} seconds...")
                    new_hls_url = fetch_hls_url(recorder.streamer_url, TWITCASTING_COOKIES)
                    if new_hls_url:
                        logger.info(f"Fetched new HLS URL: {new_hls_url}")
                        HLS_URL = new_hls_url
                        continue
                    time.sleep(recorder.check_interval)
                    continue
                if not title:
                    logger.warning("Missing stream title, using default")
                    title = f"{streamer_name}'s TwitCasting Stream"
                if not stream_id:
                    logger.error("Invalid stream ID received, cannot proceed with recording")
                    logger.info(f"Waiting {recorder.retry_delay} seconds before retrying...")
                    time.sleep(recorder.retry_delay)
                    continue
                logger.info(f"Ready to record stream - Title: '{title}', ID: {stream_id}")
                url = f"{recorder.streamer_url}/movie/{stream_id}"

            with recorder.lock:
                recorder.current_mp4_file = get_filename(title, stream_id, is_mkv=False)
                mkv_file = get_filename(title, stream_id, is_mkv=True)
                recorder.current_thumbnail_path = download_thumbnail(thumbnail_url)
            metadata = get_metadata(title)

            logger.info(f"Recording from {url} to {recorder.current_mp4_file}...")
            cmd = [
                "streamlink", url, recorder.quality, "-o", recorder.current_mp4_file, "--force",
                "--http-header", f"User-Agent={DEFAULT_USER_AGENT}",
                "--hls-live-restart", "--retry-streams", "30", "-v"
            ]
            if HLS_URL:
                cmd.extend(["--hls-playlist-reload-attempts", "5"])
            else:
                if PRIVATE_STREAM_PASSWORD:
                    cmd.extend(["--twitcasting-password", PRIVATE_STREAM_PASSWORD])
                if TWITCASTING_COOKIES:
                    for cookie in TWITCASTING_COOKIES.split(';'):
                        cookie = cookie.strip()
                        if cookie and '=' in cookie:
                            cmd.extend(["--http-cookie", cookie])
                        else:
                            logger.warning(f"Skipping invalid cookie: {cookie}")

            try:
                start_time = time.time()
                recorder.stop_event = threading.Event()
                recorder.progress_thread = threading.Thread(
                    target=monitor_file_progress,
                    args=(recorder.current_mp4_file, start_time, recorder.stop_event, print_progress)
                )
                recorder.progress_thread.start()
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                recorder.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8'
                )
                stderr_lines = []
                stdout_lines = []
                last_output_time = time.time()
                while recorder.process.poll() is None and not recorder.terminating:
                    try:
                        stdout_line = recorder.process.stdout.readline().strip()
                        if stdout_line:
                            stdout_lines.append(stdout_line)
                            logger.debug(f"Streamlink stdout: {stdout_line}")
                            last_output_time = time.time()
                        stderr_line = recorder.process.stderr.readline().strip()
                        if stderr_line:
                            stderr_lines.append(stderr_line)
                            logger.debug(f"Streamlink stderr: {stderr_line}")
                            last_output_time = time.time()
                        if time.time() - last_output_time > recorder.streamlink_timeout:
                            logger.warning(f"No output for {recorder.streamlink_timeout} seconds. Terminating.")
                            force_kill_process(recorder.process)
                            break
                        try:
                            if os.path.exists(recorder.current_mp4_file):
                                size = os.path.getsize(recorder.current_mp4_file)
                                logger.debug(f"File {recorder.current_mp4_file} size: {format_size(size)}")
                        except OSError as e:
                            logger.debug(f"Error checking file size in record_stream: {e}")
                        time.sleep(0.1)
                    except Exception as e:
                        logger.debug(f"Error reading output: {e}")
                recorder.stop_event.set()
                recorder.progress_thread.join(timeout=1.0)
                sys.stderr.write("\n")
                sys.stderr.flush()
                stdout, stderr = recorder.process.communicate(timeout=5)
                stdout_lines.extend(stdout.splitlines())
                stderr_lines.extend(stderr.splitlines())
                if recorder.process.returncode == 0:
                    logger.info("Recording stopped gracefully.")
                else:
                    logger.error(f"Recording failed: stdout={stdout_lines}, stderr={stderr_lines}")
                    if HLS_URL:
                        logger.info(f"HLS recording failed. Waiting {recorder.retry_delay} seconds before retrying...")
                        HLS_URL = None  # Reset HLS_URL to try fetching again
                        time.sleep(recorder.retry_delay)
                        continue
                    else:
                        logger.info(f"Retrying with alternate URL or waiting...")
                        continue
            except subprocess.SubprocessError as e:
                logger.error(f"Subprocess error: {e}")
                if recorder.process:
                    force_kill_process(recorder.process)
                if HLS_URL:
                    logger.info(f"HLS recording failed. Waiting {recorder.retry_delay} seconds before retrying...")
                    HLS_URL = None  # Reset HLS_URL to try fetching again
                    time.sleep(recorder.retry_delay)
                continue
            finally:
                if recorder.process and recorder.process.poll() is None:
                    force_kill_process(recorder.process)
            if recorder.terminating:
                break
            if os.path.exists(recorder.current_mp4_file) and os.path.getsize(recorder.current_mp4_file) > 0:
                convert_to_mkv_and_add_metadata(recorder.current_mp4_file, mkv_file, metadata, recorder.current_thumbnail_path)
            else:
                logger.warning(f"Recording file {recorder.current_mp4_file} empty or missing.")
            cleanup_temp_files(recorder)
            logger.info(f"Waiting {recorder.retry_delay} seconds before checking stream...")
            time.sleep(recorder.retry_delay)

    # Login if credentials provided
    if TWITCASTING_USERNAME and TWITCASTING_PASSWORD:
        cookies = login_to_twitcasting(TWITCASTING_USERNAME, TWITCASTING_PASSWORD)
        if cookies:
            TWITCASTING_COOKIES = ";".join(cookies)
            logger.info("Updated TWITCASTING_COOKIES with login session")

    # Initialize HLS_URL if not provided
    if not HLS_URL:
        HLS_URL = fetch_hls_url(STREAMER_URL, TWITCASTING_COOKIES)
        if HLS_URL:
            logger.info(f"Automatically fetched HLS URL: {HLS_URL}")
        else:
            logger.warning("Could not fetch HLS URL, falling back to WebSocket-based recording")

    # Validate HLS URL if provided
    if HLS_URL:
        if not re.match(r'^https?://.*\.(m3u8|mp4)$', HLS_URL):
            logger.error(f"Invalid HLS URL: {HLS_URL}. Must start with http(s):// and end with .m3u8 or .mp4.")
            sys.exit(1)
        logger.info(f"Using HLS URL: {HLS_URL}")

    # Setup signal handler
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, recorder))

    # Start watchdog (optional)
    watchdog_thread = None
    if not NO_WATCHDOG:
        watchdog_thread = threading.Thread(target=watchdog, args=(recorder, 3600))
        watchdog_thread.daemon = True
        watchdog_thread.start()

    try:
        record_stream(recorder)
    except KeyboardInterrupt:
        recorder.terminating = True
        logger.debug("Main block caught KeyboardInterrupt")
        cleanup_temp_files(recorder)
    finally:
        logger.debug("Entering finally block")
        if watchdog_thread and watchdog_thread.is_alive():
            recorder.watchdog_stop_event.set()
            join_start = time.time()
            watchdog_thread.join(timeout=0.1)
            logger.debug(f"Watchdog thread joined in {time.time() - join_start:.3f} seconds")
        logger.info("Script terminated.")
        sys.stderr.flush()
        logger.debug("Finally block completed")
