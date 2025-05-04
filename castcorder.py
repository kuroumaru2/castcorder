#!/usr/bin/env python3
"""
Castcorder: A Python script to record live streams from TwitCasting.

This script monitors specified TwitCasting streamers, records their live streams
using Streamlink, converts recordings to MKV format, and adds metadata.
It supports private streams with passwords and handles cookies for authentication.

License: This is free and unencumbered software released into the public domain
under the Unlicense (see LICENSE file).

Dependencies:
- streamlink
- tqdm (optional, for progress bars)
- requests (optional, for stream info fetching)
- beautifulsoup4 (optional, for stream info fetching)
- ffmpeg (for MKV conversion)

See README.md for setup and usage instructions.
"""

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

# Try to import tqdm for progress bar, with fallback
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None
    logging.warning("tqdm not installed. Progress will be logged but not displayed as a progress bar. Install with: pip install tqdm")

# Custom StreamHandler to handle Unicode characters in console
class UnicodeSafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            stream.write(msg + self.terminator)
            self.flush()
        except UnicodeEncodeError:
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

# Log script version and Python version
SCRIPT_VERSION = "2025-05-04-v21"
logger = logging.getLogger(__name__)
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

# Add requests_lib and bs4_lib to Python path (unchanged)
# ...

# Import requests and BeautifulSoup (unchanged)
# ...

# Configuration (continued)
CHECK_INTERVAL = 15
RETRY_DELAY = 15

# TwitCasting login credentials and cookies (unchanged)
TWITCASTING_USERNAME = os.environ.get('TWITCASTING_USERNAME')
TWITCASTING_PASSWORD = os.environ.get('TWITCASTING_PASSWORD')
PRIVATE_STREAM_PASSWORD = os.environ.get('PRIVATE_STREAM_PASSWORD')
TWITCASTING_COOKIES = os.environ.get('TWITCASTING_COOKIES', '')

# Default user-agent (unchanged)
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36"

def login_to_twitcasting(username, password):
    # Unchanged
    # ...

def get_filename(title, stream_id, streamer_name, is_mkv=False):
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
    
    counter = 2
    while os.path.exists(full_path):
        filename = f"{base_filename} ({counter}).{ext}"
        full_path = os.path.join(SAVE_FOLDER, filename)
        counter += 1
    
    if counter > 2:
        logger.info(f"Using numbered filename: {filename}")
    return full_path

def fetch_stream_info(streamer_url):
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
        response = requests.get(streamer_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            logger.info(f"Found title: {title}")

        movie_link = soup.find("a", href=re.compile(r'/movie/\d+'))
        if movie_link and movie_link.get("href"):
            stream_id_match = re.search(r'/movie/(\d+)', movie_link["href"])
            if stream_id_match:
                stream_id = stream_id_match.group(1)
                movie_url = f"{streamer_url}/movie/{stream_id}"
                logger.info(f"Found stream ID: {stream_id}, Movie URL: {movie_url}")

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

def is_stream_live(streamer_url):
    """Check if the stream is live by scraping the page."""
    if not requests or not BeautifulSoup:
        logger.warning("Cannot check live status: requests or BeautifulSoup module is not available")
        return False

    try:
        headers = {'User-Agent': DEFAULT_USER_AGENT}
        response = requests.get(streamer_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        movie_link = soup.find("a", href=re.compile(r'/movie/\d+'))
        if movie_link:
            live_indicator = soup.find("span", class_=re.compile(r'live|broadcasting', re.I))
            if live_indicator or "live" in movie_link.text.lower():
                logger.info("Stream is live based on page scrape")
                if not PRIVATE_STREAM_PASSWORD:
                    logger.warning("Stream is live but PRIVATE_STREAM_PASSWORD is not set. Recording may fail if password is required.")
                return True

        logger.info("No live stream detected on page")
        return False
    except Exception as e:
        logger.error(f"Live check failed: {e}")

    try:
        cmd = ["streamlink", "--json", streamer_url, QUALITY, "--http-header", f"User-Agent={DEFAULT_USER_AGENT}", "-v"]
        if PRIVATE_STREAM_PASSWORD:
            cmd.extend(["--twitcasting-password", PRIVATE_STREAM_PASSWORD])
        if TWITCASTING_COOKIES:
            for cookie in TWITCASTING_COOKIES.split(';'):
                if cookie.strip():
                    cmd.extend(["--http-cookie", cookie.strip()])
        logger.debug(f"Running Streamlink live check command: {' '.join(cmd)}")
        result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        stream_data = json.loads(result)
        live = "error" not in stream_data
        logger.info(f"Streamlink check: {'Live' if live else 'Offline'}")
        return live
    except subprocess.CalledProcessError as e:
        logger.error(f"Streamlink check failed: {e.output}")
        return False
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return False

def download_thumbnail(thumbnail_url):
    # Unchanged
    # ...

def get_metadata(title, streamer_name):
    """Generate metadata for the recording."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = {
        "title": title,
        "artist": streamer_name,
        "date": timestamp.split()[0],
        "comment": f"Recorded from https://twitcasting.tv/{streamer_name} on {timestamp}"
    }
    return metadata

def format_size(bytes_size):
    # Unchanged
    # ...

def format_duration(seconds):
    # Unchanged
    # ...

def monitor_file_progress(file_path, start_time, stop_event, progress_callback):
    # Unchanged
    # ...

def print_progress(progress, counter, progress_bar, tqdm_lock):
    # Unchanged
    # ...

def convert_to_mkv_and_add_metadata(mp4_file, mkv_file, metadata, thumbnail_path=None):
    # Unchanged
    # ...

def cleanup_temp_files():
    # Unchanged
    # ...

def signal_handler(sig, frame):
    # Unchanged
    # ...

def record_stream(streamer_name, streamer_url):
    """Record the stream, convert to MKV, add metadata/thumbnail."""
    global process, stop_event, progress_thread, current_mp4_file, current_thumbnail_path
    while True:
        if terminating:
            logger.info("Terminating record_stream due to SIGINT")
            break

        if not is_stream_live(streamer_url):
            logger.info(f"Stream is offline. Checking again in {CHECK_INTERVAL} seconds...")
            time.sleep(CHECK_INTERVAL)
            continue

        title, stream_id, thumbnail_url = fetch_stream_info(streamer_url)
        current_mp4_file = get_filename(title, stream_id, streamer_name, is_mkv=False)
        mkv_file = get_filename(title, stream_id, streamer_name, is_mkv=True)
        current_thumbnail_path = download_thumbnail(thumbnail_url)
        metadata = get_metadata(title, streamer_name)
        movie_url = f"{streamer_url}/movie/{stream_id}"

        for url in [streamer_url, movie_url]:
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
                timeout = 60
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
    # Configure logging before reading streamers
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            UnicodeSafeStreamHandler()
        ]
    )

    # Read streamers from file
    streamers = read_streamers("streamers.txt")

    # Get streamer from command-line argument or prompt
    streamer_arg = None
    if len(sys.argv) > 1:
        streamer_arg = sys.argv[1]
    streamer_name = select_streamer(streamers, streamer_arg)

    # Set up streamer-specific configuration
    STREAMER_URL = f"https://twitcasting.tv/{streamer_name}"
    SAVE_FOLDER = os.path.join(BASE_SAVE_FOLDER, streamer_name)
    LOG_FILE = os.path.join(SAVE_FOLDER, f"{streamer_name}_twitcasting_recorder.log")

    # Ensure streamer-specific save folder exists
    if not os.path.exists(SAVE_FOLDER):
        os.makedirs(SAVE_FOLDER)

    # Reconfigure logging to include file handler
    logging.getLogger('').handlers = []  # Clear existing handlers
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            UnicodeSafeStreamHandler()
        ]
    )

    signal.signal(signal.SIGINT, signal_handler)
    
    logger.info(f"Starting TwitCasting stream recorder for {STREAMER_URL}")
    cookies = None
    if TWITCASTING_USERNAME and TWITCASTING_PASSWORD:
        cookies = login_to_twitcasting(TWITCASTING_USERNAME, TWITCASTING_PASSWORD)
        if not cookies:
            logger.error("Failed to log in. Proceeding without authentication.")
    try:
        record_stream(streamer_name, STREAMER_URL)
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