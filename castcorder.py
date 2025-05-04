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

# Initial logging setup (console only, before streamer selection)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Try to import tqdm for progress bar, with fallback
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None
    logger.warning("tqdm not installed. Progress will be logged but not displayed as a progress bar. Install with: pip install tqdm")

# Custom StreamHandler to handle Unicode characters in console
class UnicodeSafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            stream.write(msg + self.terminator)
            self.flush()
        except UnicodeEncodeError:
            # Replace unencodable characters
            msg = self.format(record).encode('ascii', 'replace').decode('ascii')
            stream.write(msg + self.terminator)
            self.flush()

# Function to read usernames from a text file
def read_streamers(file_path="streamers.txt"):
    """Read a list of streamer usernames from a text file."""
    if not os.path.exists(file_path):
        logger.error(f"Streamers file '{file_path}' not found.")
        sys.exit(1)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Read lines, strip whitespace, and filter out empty lines
            streamers = [line.strip() for line in f if line.strip()]
        if not streamers:
            logger.error(f"Streamers file '{file_path}' is empty.")
            sys.exit(1)
        return streamers
    except Exception as e:
        logger.error(f"Error reading streamers file '{file_path}': {e}")
        sys.exit(1)

# Function to select a streamer
def select_streamer(streamers, streamer_arg=None):
    """Select a streamer from the list, either via argument or user input."""
    if streamer_arg and streamer_arg in streamers:
        return streamer_arg
    elif streamer_arg:
        logger.warning(f"Streamer '{streamer_arg}' not found in streamers.txt. Prompting for selection.")

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

# Configuration
QUALITY = "best"
BASE_SAVE_FOLDER = os.path.dirname(os.path.abspath(__file__))

# Read streamers and select one
streamers = read_streamers("streamers.txt")
streamer_arg = sys.argv[1] if len(sys.argv) > 1 else None
selected_streamer = select_streamer(streamers, streamer_arg)

# Define STREAMER_URL based on selected streamer
STREAMER_URL = f"https://twitcasting.tv/{selected_streamer}"

# Derive streamer-specific save folder and log file
streamer_name = STREAMER_URL.split('/')[-1]
SAVE_FOLDER = os.path.join(BASE_SAVE_FOLDER, streamer_name)
LOG_FILE = os.path.join(SAVE_FOLDER, f"{streamer_name}_twitcasting_recorder.log")

# Ensure streamer-specific save folder exists
if not os.path.exists(SAVE_FOLDER):
    os.makedirs(SAVE_FOLDER)

# Reconfigure logging to include file handler
logging.getLogger().handlers = []  # Clear existing handlers
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        UnicodeSafeStreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Log script version and Python version
SCRIPT_VERSION = "2025-05-04-v22"
logger.info(f"Running script version: {SCRIPT_VERSION}")
logger.info(f"Python version: {sys.version}")

# Set UTF-8 encoding for subprocesses
os.environ["PYTHONIOENCODING"] = "utf-8"

# Global variables for termination handling
terminating = False
process = None
stop_event = None
progress_thread = None
current_mp4_file = None
current_thumbnail_path = None

# Check for shadowing files
for shadow_file in ["requests.py", "bs4.py"]:
    if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), shadow_file)):
        logger.error(f"Found '{shadow_file}' in script directory, which shadows a required module. Please rename or remove it.")
        sys.exit(1)

# Add requests_lib to Python path
requests_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'requests_lib')
if os.path.exists(requests_lib_path):
    sys.path.insert(0, requests_lib_path)
    logger.info(f"Added {requests_lib_path} to sys.path")
else:
    logger.warning(f"requests_lib directory not found at {requests_lib_path}. Falling back to system requests.")

# Add bs4_lib to Python path
bs4_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bs4_lib')
if os.path.exists(bs4_lib_path):
    sys.path.insert(0, bs4_lib_path)
    logger.info(f"Added {bs4_lib_path} to sys.path")
else:
    logger.warning(f"bs4_lib directory not found at {bs4_lib_path}. Falling back to system beautifulsoup4.")

# Import requests
try:
    import requests
    logger.info(f"Successfully imported requests from {requests.__file__} (version {requests.__version__})")
except ImportError as e:
    logger.error(f"Failed to import requests: {e}")
    logger.warning("Proceeding without requests; thumbnail fetching and login will be skipped.")
    requests = None

# Import BeautifulSoup
try:
    from bs4 import BeautifulSoup
    logger.info(f"Successfully imported BeautifulSoup from {BeautifulSoup.__module__}")
except ImportError as e:
    logger.error(f"Failed to import BeautifulSoup: {e}")
    logger.warning("Proceeding without BeautifulSoup; thumbnail fetching and login will be skipped.")
    BeautifulSoup = None

# Configuration (continued)
CHECK_INTERVAL = 15
RETRY_DELAY = 15
STREAMLINK_TIMEOUT = 300  # Increased from 60 to 300 seconds

# TwitCasting login credentials and cookies
TWITCASTING_USERNAME = os.environ.get('TWITCASTING_USERNAME')
TWITCASTING_PASSWORD = os.environ.get('TWITCASTING_PASSWORD')
PRIVATE_STREAM_PASSWORD = os.environ.get('PRIVATE_STREAM_PASSWORD')
TWITCASTING_COOKIES = os.environ.get('TWITCASTING_COOKIES', '')

# Default user-agent
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36"

def login_to_twitcasting(username, password):
    """Authenticate with TwitCasting and return session cookies."""
    if not requests or not BeautifulSoup:
        logger.error("Cannot log in: requests or BeautifulSoup module is not available")
        return None
    login_url = "https://twitcasting.tv/index.php"
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
    except Exception as e:
        logger.error(f"Login error: {e}")
        return None

def is_stream_live():
    """Check if the stream is live using Streamlink first, then page scraping."""
    # First, try Streamlink check (more reliable for live streams)
    try:
        cmd = ["streamlink", "--json", STREAMER_URL, QUALITY, "--http-header", f"User-Agent={DEFAULT_USER_AGENT}", "-v"]
        if PRIVATE_STREAM_PASSWORD:
            cmd.extend(["--twitcasting-password", PRIVATE_STREAM_PASSWORD])
        if TWITCASTING_COOKIES:
            for cookie in TWITCASTING_COOKIES.split(';'):
                if cookie.strip():
                    cmd.extend(["--http-cookie", cookie.strip()])
        logger.debug(f"Running Streamlink live check command: {' '.join(cmd)}")
        result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, encoding='utf-8', timeout=30)
        stream_data = json.loads(result)
        live = "error" not in stream_data
        logger.info(f"Streamlink check: {'Live' if live else 'Offline'}")
        if live:
            return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Streamlink check failed: {e.output}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in Streamlink output: {e}")
    except subprocess.TimeoutExpired:
        logger.error("Streamlink check timed out after 30 seconds")
    except Exception as e:
        logger.error(f"Unexpected error in Streamlink check: {e}")

    # Fallback to page scraping if Streamlink fails
    if not requests or not BeautifulSoup:
        logger.warning("Cannot check live status via page scraping: requests or BeautifulSoup module is not available")
        return False

    try:
        headers = {'User-Agent': DEFAULT_USER_AGENT}
        if TWITCASTING_COOKIES:
            headers['Cookie'] = TWITCASTING_COOKIES
        response = requests.get(STREAMER_URL, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Check for movie link
        movie_link = soup.find("a", href=re.compile(r'/movie/\d+'))
        if movie_link:
            logger.debug(f"Found movie link: {movie_link.get('href')}")
            # Check for live indicators (broaden search)
            live_indicators = [
                soup.find("span", class_=re.compile(r'live|broadcasting|streaming', re.I)),
                "live" in movie_link.text.lower(),
                soup.find(string=re.compile(r'live|broadcasting|streaming', re.I))
            ]
            if any(live_indicators):
                logger.info("Stream is live based on page scrape")
                if not PRIVATE_STREAM_PASSWORD:
                    logger.warning("Stream is live but PRIVATE_STREAM_PASSWORD is not set. Recording may fail if password is required.")
                return True
            else:
                logger.debug("No live indicators found in page scrape")
        else:
            logger.debug("No movie link found in page scrape")

        logger.info("No live stream detected on page")
        return False
    except Exception as e:
        logger.error(f"Page scrape live check failed: {e}")
        return False

def fetch_stream_info():
    """Fetch stream title, stream ID, and thumbnail URL."""
    title = None
    stream_id = None
    thumbnail_url = None

    if not requests or not BeautifulSoup:
        logger.warning("Cannot fetch stream info: requests or BeautifulSoup module is not available")
        title = f"{streamer_name}'s TwitCasting Stream"
        stream_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return title, stream_id, thumbnail_url

    try:
        headers = {'User-Agent': DEFAULT_USER_AGENT}
        if TWITCASTING_COOKIES:
            headers['Cookie'] = TWITCASTING_COOKIES
        response = requests.get(STREAMER_URL, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract title
        og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            logger.info(f"Found title: {title}")

        # Extract stream ID from movie link
        movie_link = soup.find("a", href=re.compile(r'/movie/\d+'))
        if movie_link and movie_link.get("href"):
            stream_id_match = re.search(r'/movie/(\d+)', movie_link["href"])
            if stream_id_match:
                stream_id = stream_id_match.group(1)
                movie_url = f"{STREAMER_URL}/movie/{stream_id}"
                logger.info(f"Found stream ID: {stream_id}, Movie URL: {movie_url}")
        else:
            logger.debug("No movie link found on main page, checking alternative selectors")

        # Try alternative selectors for stream ID
        if not stream_id:
            # Check meta tags or other links
            meta_movie = soup.find("meta", attrs={"content": re.compile(r'/movie/\d+')})
            if meta_movie:
                stream_id_match = re.search(r'/movie/(\d+)', meta_movie["content"])
                if stream_id_match:
                    stream_id = stream_id_match.group(1)
                    logger.info(f"Found stream ID from meta tag: {stream_id}")

        # Fallback: Check the movie page if stream is live
        if not stream_id and is_stream_live():
            movie_url = f"{STREAMER_URL}/movie"
            try:
                response = requests.get(movie_url, headers=headers, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                movie_link = soup.find("a", href=re.compile(r'/movie/\d+'))
                if movie_link:
                    stream_id_match = re.search(r'/movie/(\d+)', movie_link["href"])
                    if stream_id_match:
                        stream_id = stream_id_match.group(1)
                        logger.info(f"Found stream ID from movie page: {stream_id}")
            except Exception as e:
                logger.debug(f"Failed to fetch movie page for stream ID: {e}")

        # Extract thumbnail URL
        og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        if og_image and og_image.get("content"):
            thumbnail_url = og_image["content"]
            logger.info(f"Found thumbnail URL: {thumbnail_url}")

    except Exception as e:
        logger.warning(f"Failed to fetch stream info from page: {e}")

    if not title:
        title = f"{streamer_name}'s TwitCasting Stream"
    if not stream_id:
        stream_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        logger.warning("Using timestamp as fallback stream ID")

    return title, stream_id, thumbnail_url

def get_filename(title, stream_id, is_mkv=False):
    """Generate a unique filename with format [YYYYMMDD] title [username][stream_id] [(n)]."""
    date_str = datetime.now().strftime("%Y%m%d")
    username = streamer_name
    title = re.sub(r'[<>:"/\\|?*]', '', title).strip()
    title = re.sub(r'\s+', ' ', title)
    title = title[:50] if len(title) > 50 else title
    ext = "mkv" if is_mkv else "mp4"
    base_filename = f"[{date_str}] {title} [{username}][{stream_id}]"
    filename = f"{base_filename}.{ext}"
    full_path = os.path.join(SAVE_FOLDER, filename)
    
    # Check for existing files and append (n) if needed
    counter = 2
    while os.path.exists(full_path):
        filename = f"{base_filename} ({counter}).{ext}"
        full_path = os.path.join(SAVE_FOLDER, filename)
        counter += 1
    
    if counter > 2:
        logger.info(f"Using numbered filename: {filename}")
    return full_path

def download_thumbnail(thumbnail_url):
    """Download the thumbnail image to a temporary file."""
    if not thumbnail_url or not requests:
        logger.warning("Cannot download thumbnail: requests module is not available or no thumbnail URL")
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
        else:
            os.remove(thumbnail_path)
            return None
    except Exception as e:
        logger.warning(f"Failed to download thumbnail: {e}")
        return None

def get_metadata(title):
    """Generate metadata for the recording."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = {
        "title": title,
        "artist": streamer_name,
        "date": timestamp.split()[0],
        "comment": f"Recorded from {STREAMER_URL} on {timestamp}"
    }
    return metadata

def format_size(bytes_size):
    """Convert bytes to human-readable size."""
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} PiB"

def format_duration(seconds):
    """Convert seconds to human-readable duration."""
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    return f"{minutes}m{seconds:02d}s"

def monitor_file_progress(file_path, start_time, stop_event, progress_callback):
    """Monitor file size and call progress_callback."""
    global terminating
    last_size = 0
    progress_bar = None
    progress_counter = 0
    tqdm_lock = threading.Lock()

    try:
        if tqdm is not None and not terminating:
            with tqdm_lock:
                progress_bar = tqdm(
                    desc="Recording",
                    unit="it",
                    leave=False,
                    dynamic_ncols=True,
                    disable=None
                )
        else:
            logger.info("tqdm not installed or terminating. Progress will be logged to file.")

        while not stop_event.is_set() and not terminating:
            try:
                if os.path.exists(file_path):
                    current_size = os.path.getsize(file_path)
                    elapsed_time = time.time() - start_time
                    if elapsed_time > 0:
                        speed = (current_size - last_size) / 1024 / 1.0
                        total_size_str = format_size(current_size)
                        duration_str = format_duration(elapsed_time)
                        speed_str = f"{speed:.2f} KiB/s"
                        progress = f"Size: {total_size_str} ({duration_str} @ {speed_str})"
                        progress_callback(progress, progress_counter, progress_bar, tqdm_lock)
                        last_size = current_size
                    else:
                        progress = f"Size: 0.00 B (0m00s @ 0.00 KiB/s)"
                        progress_callback(progress, progress_counter, progress_bar, tqdm_lock)
                    progress_counter += 1
                else:
                    progress = f"Waiting for {os.path.basename(file_path)}..."
                    progress_callback(progress, progress_counter, progress_bar, tqdm_lock)
                    progress_counter += 1
            except Exception as e:
                logger.debug(f"Progress monitoring error: {e}")
            time.sleep(1)
    finally:
        if progress_bar is not None:
            with tqdm_lock:
                try:
                    progress_bar.close()
                    logger.debug("Progress bar closed successfully")
                except Exception as e:
                    logger.debug(f"Error closing progress bar: {e}")

def print_progress(progress, counter, progress_bar, tqdm_lock):
    """Update progress display in place using tqdm."""
    global terminating
    logger.debug(progress)
    if progress_bar is not None and not terminating:
        with tqdm_lock:
            try:
                progress_bar.n = counter
                progress_bar.set_postfix_str(progress)
                progress_bar.refresh()
            except Exception as e:
                logger.debug(f"Error updating progress bar: {e}")
    elif tqdm is None:
        sys.stdout.write(f"\r{progress:<100}")
        sys.stdout.flush()

def convert_to_mkv_and_add_metadata(mp4_file, mkv_file, metadata, thumbnail_path=None):
    """Convert MP4 to MKV, add metadata, embed thumbnail."""
    metadata_args = []
    for key, value in metadata.items():
        metadata_args.extend(["-metadata", f"{key}={value.replace(';', '')}"])
    cmd = [
        "ffmpeg", "-i", mp4_file, "-c", "copy", "-map", "0"
    ] + metadata_args

    if thumbnail_path:
        cmd.extend(["-attach", thumbnail_path, "-metadata:s:t", "mimetype=image/jpeg", "-metadata:s:t", "filename=thumbnail.jpg"])

    cmd.append(mkv_file)

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        logger.info(f"Converted {mp4_file} to {mkv_file} with metadata and thumbnail")
        if os.path.exists(mkv_file) and os.path.getsize(mkv_file) > 0:
            os.remove(mp4_file)
            logger.info(f"Deleted original MP4 file: {mp4_file}")
        else:
            logger.warning(f"MKV file {mkv_file} is empty or missing. Keeping MP4 file.")
        if thumbnail_path and os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)
            logger.info(f"Deleted thumbnail: {thumbnail_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to convert to MKV or add metadata/thumbnail: {e.stderr}")
    except Exception as e:
        logger.error(f"Error processing {mp4_file}: {e}")

def cleanup_temp_files():
    """Delete temporary files during termination."""
    global current_mp4_file, current_thumbnail_path
    try:
        if not current_thumbnail_path or not os.path.exists(current_thumbnail_path):
            logger.info("No temporary thumbnail to delete")
        elif current_thumbnail_path and os.path.exists(current_thumbnail_path):
            os.remove(current_thumbnail_path)
            logger.info(f"Deleted temporary thumbnail: {current_thumbnail_path}")
        if not current_mp4_file or not os.path.exists(current_mp4_file):
            logger.info("No temporary MP4 file to delete")
        elif current_mp4_file and os.path.exists(current_mp4_file) and os.path.getsize(current_mp4_file) == 0:
            os.remove(current_mp4_file)
            logger.info(f"Deleted empty MP4 file: {current_mp4_file}")
    except Exception as e:
        logger.error(f"Error cleaning up temporary files: {e}")

def signal_handler(sig, frame):
    """Handle SIGINT (Ctrl+C)."""
    global terminating, process, stop_event, progress_thread
    if terminating:
        logger.warning("Received multiple Ctrl+C. Forcefully exiting...")
        cleanup_temp_files()
        os._exit(1)

    terminating = True
    logger.info("Received Ctrl+C, stopping script...")

    if stop_event:
        stop_event.set()
        logger.info("Signaled progress thread to stop")

    if progress_thread and progress_thread.is_alive():
        progress_thread.join(timeout=2)
        logger.info("Progress thread stopped")
    sys.stdout.write("\n")
    sys.stdout.flush()

    if process:
        process.terminate()
        try:
            process.wait(timeout=2)
            logger.info("Streamlink subprocess terminated gracefully")
        except subprocess.TimeoutExpired:
            process.kill()
            logger.warning("Streamlink subprocess killed after timeout")

    cleanup_temp_files()
    logger.info("Script stopped cleanly")
    sys.exit(0)

def record_stream():
    """Record the stream, convert to MKV, add metadata/thumbnail."""
    global process, stop_event, progress_thread, current_mp4_file, current_thumbnail_path
    while True:
        if terminating:
            logger.info("Terminating record_stream due to SIGINT")
            break

        if not is_stream_live():
            logger.info(f"Stream is offline. Checking again in {CHECK_INTERVAL} seconds...")
            time.sleep(CHECK_INTERVAL)
            continue

        title, stream_id, thumbnail_url = fetch_stream_info()
        current_mp4_file = get_filename(title, stream_id, is_mkv=False)
        mkv_file = get_filename(title, stream_id, is_mkv=True)
        current_thumbnail_path = download_thumbnail(thumbnail_url)
        metadata = get_metadata(title)
        movie_url = f"{STREAMER_URL}/movie/{stream_id}"

        for url in [STREAMER_URL, movie_url]:
            if terminating:
                logger.info("Stopping recording attempt due to SIGINT")
                break

            logger.info(f"Stream is live! Attempting to record from {url} to {current_mp4_file}...")
            cmd = [
                "streamlink", url, QUALITY, "-o", current_mp4_file, "--force",
                "--http-header", f"User-Agent={DEFAULT_USER_AGENT}",
                "--hls-live-restart", "--retry-streams", "30", "-v"
            ]
            if PRIVATE_STREAM_PASSWORD:
                cmd.extend(["--twitcasting-password", PRIVATE_STREAM_PASSWORD])
            if TWITCASTING_COOKIES:
                for cookie in TWITCASTING_COOKIES.split(';'):
                    if cookie.strip():
                        cmd.extend(["--http-cookie", cookie.strip()])
            logger.debug(f"Running Streamlink command: {' '.join(cmd)}")

            try:
                start_time = time.time()
                stop_event = threading.Event()
                progress_thread = threading.Thread(
                    target=monitor_file_progress,
                    args=(current_mp4_file, start_time, stop_event, print_progress)
                )
                progress_thread.start()

                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                    env=env
                )

                stderr_lines = []
                stdout_lines = []
                timeout = STREAMLINK_TIMEOUT  # Use configurable timeout
                start_time = time.time()
                while process.poll() is None and not terminating:
                    try:
                        stdout_line = process.stdout.readline()
                        if stdout_line:
                            try:
                                line = stdout_line.decode('utf-8', errors='replace').strip()
                                stdout_lines.append(line)
                                logger.debug(f"Streamlink stdout: {line}")
                            except UnicodeDecodeError:
                                logger.debug("Non-decodable stdout output detected")
                    except Exception as e:
                        logger.debug(f"Error reading stdout: {e}")
                    try:
                        stderr_line = process.stderr.readline()
                        if stderr_line:
                            try:
                                line = stderr_line.decode('utf-8', errors='replace').strip()
                                stderr_lines.append(line)
                                logger.debug(f"Streamlink stderr: {line}")
                            except UnicodeDecodeError:
                                logger.debug("Non-decodable stderr output detected")
                    except Exception as e:
                        logger.debug(f"Error reading stderr: {e}")
                    if time.time() - start_time > timeout:
                        logger.warning(f"Streamlink timed out after {timeout} seconds. Terminating process.")
                        process.terminate()
                        process.wait(timeout=2)
                        break
                    time.sleep(0.1)

                stop_event.set()
                progress_thread.join(timeout=2)
                print()

                try:
                    stdout, stderr = process.communicate(timeout=10)
                    if stdout:
                        stdout_lines.extend(stdout.decode('utf-8', errors='replace').splitlines())
                    if stderr:
                        stderr_lines.extend(stderr.decode('utf-8', errors='replace').splitlines())
                except subprocess.TimeoutExpired:
                    logger.error("Timeout while capturing remaining Streamlink output.")
                    process.kill()

                for line in stdout_lines:
                    logger.debug(f"Streamlink final stdout: {line}")
                for line in stderr_lines:
                    logger.debug(f"Streamlink final stderr: {line}")

                if process.returncode == 0:
                    logger.info("Recording stopped gracefully.")
                    break
                else:
                    logger.error(f"Recording failed with {url}: stdout={stdout_lines}, stderr={stderr_lines}")
                    if url == movie_url:
                        logger.error("Both URLs failed. Retrying after delay.")
                    continue

            except subprocess.SubprocessError as e:
                logger.error(f"Subprocess error during recording with {url}: {e}")
                stop_event.set()
                progress_thread.join(timeout=2)
                print()
                if process:
                    process.terminate()
                    process.wait(timeout=2)
                if url == movie_url:
                    logger.error("Both URLs failed. Retrying after delay.")
                continue
            except Exception as e:
                logger.error(f"Unexpected error during recording with {url}: {e}")
                stop_event.set()
                progress_thread.join(timeout=2)
                print()
                if process:
                    process.terminate()
                    process.wait(timeout=2)
                if url == movie_url:
                    logger.error("Both URLs failed. Retrying after delay.")
                continue

        if terminating:
            logger.info("Skipping MKV conversion due to termination")
            break

        if os.path.exists(current_mp4_file) and os.path.getsize(current_mp4_file) > 0:
            convert_to_mkv_and_add_metadata(current_mp4_file, mkv_file, metadata, current_thumbnail_path)
        else:
            logger.warning(f"Recording file {current_mp4_file} is empty or missing. Skipping MKV conversion.")

        cleanup_temp_files()
        logger.info(f"Waiting {RETRY_DELAY} seconds before checking stream status...")
        time.sleep(RETRY_DELAY)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.info(f"Starting TwitCasting stream recorder for {STREAMER_URL}")
    cookies = None
    if TWITCASTING_USERNAME and TWITCASTING_PASSWORD:
        cookies = login_to_twitcasting(TWITCASTING_USERNAME, TWITCASTING_PASSWORD)
        if cookies:
            TWITCASTING_COOKIES = ";".join(cookies)
            logger.info(f"Updated TWITCASTING_COOKIES with login session")
        else:
            logger.error("Failed to log in. Proceeding without authentication.")
    try:
        record_stream()
    except KeyboardInterrupt:
        logger.info("Stopped by user via KeyboardInterrupt")
        terminating = True
        if stop_event:
            stop_event.set()
        if progress_thread and progress_thread.is_alive():
            progress_thread.join(timeout=2)
        if process:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        cleanup_temp_files()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Script terminated.")
        cleanup_temp_files()
