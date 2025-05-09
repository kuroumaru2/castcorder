# Castcorder

**Castcorder** is a Python script designed to record live streams from [TwitCasting](https://twitcasting.tv/). It monitors specified streamers, records their live streams using [Streamlink](https://streamlink.github.io/), converts recordings to MKV format, and adds metadata. The script supports automatic retry, progress monitoring, graceful termination, private streams with passwords and handles authentication via cookies.

## Features:
1. Records TwitCasting streams using `streamlink` and converts to MKV with `ffmpeg`.
2. Supports stream quality selection (e.g., "best", "720p").
3. Automatically checks for live streams and retries if offline.
4. Generates safe filenames with stream title, date, and stream ID.
5. Downloads and attaches stream thumbnails (if available).
6. Adds metadata (title, artist, date, comment) to recordings.
7. Monitors disk space and file progress with optional `tqdm` progress bar.
8. Handles private streams with passwords and TwitCasting login credentials.
9. Graceful termination with cleanup on Ctrl+C.
10. Watchdog thread to detect stalled recordings.
11. Unicode-safe logging to file and console.

## Requirements:
1. **Python**: 3.6 or higher
2. 2. **Dependencies**:
  - `streamlink`: For stream recording.
  - `ffmpeg`: For video conversion and metadata embedding.
  - `requests` and `beautifulsoup4`: For fetching stream info and thumbnails.
  - `psutil` (optional): Enhanced process management.
  - `tqdm` (optional): Progress bar display.
3. **System**:
  - Works on Windows, Linux, and macOS.
  - Requires sufficient disk space (minimum 100 MB free).

## Install dependencies:
    pip install streamlink requests beautifulsoup4 psutil tqdm
Install streamlink and ffmpeg via your package manager (e.g., apt, brew, or download binaries).

## Installation:
Clone or download this repository.
Ensure streamlink and ffmpeg are installed and accessible in your PATH.
Install Python dependencies:

    pip install -r requirements.txt

(Create requirements.txt with requests, beautifulsoup4, psutil, tqdm if needed.)
Create a streamers.txt file with one TwitCasting username per line.

## Usage:
Run the script from the command line:

    python castcorder.py [options]

## Command-Line Arguments:
1. --streamer: Specify a streamer username (e.g., username).
2. --quality: Stream quality (default: best).
3. --save-folder: Base folder for recordings (default: script directory).
4. --streamers-file: Path to streamers.txt (default: streamers.txt).
5. --debug: Enable debug logging.
6. --progress-bar: Enable tqdm progress bar (may not work in CMD).
7. --timeout: Streamlink timeout in seconds (default: 1800).
8. --fast-exit: Force instant exit on Ctrl+C (skips cleanup).
9. --no-watchdog: Disable watchdog thread (for testing).

Example:

    python castcorder.py --streamer username --quality 720p --progress-bar

## Environment Variables
1. TWITCASTING_USERNAME: TwitCasting login username.
2. TWITCASTING_PASSWORD: TwitCasting login password.
3. PRIVATE_STREAM_PASSWORD: Password for private streams.
4. TWITCASTING_COOKIES: Cookies for authenticated sessions.
5. CHECK_INTERVAL: Stream check interval in seconds (default: 15).
6. RETRY_DELAY: Delay between retries in seconds (default: 15).
7. STREAMLINK_TIMEOUT: Streamlink output timeout in seconds (default: 1800).

Example:

    export TWITCASTING_USERNAME="your_username"
    export TWITCASTING_PASSWORD="your_password"
    python twitcasting_recorder.py

## Streamers File:
Create a streamers.txt file in the script directory with one username per line:
    
     streamer1
     streamer2
     streamer3

If --streamer is not provided, the script prompts to select a streamer from this list.

##Output:
1. Recordings are saved in [save_folder]/[streamer_name]/ as MKV files.
2. Filename format: `[<date>] <title> [<username>][<stream_id>].mkv`
3. Log file: [save_folder]/[streamer_name]/[streamer_name]_twitcasting_recorder.log
4. Temporary files (e.g., MP4, thumbnails) are cleaned up after conversion.

## Notes:
1. Ensure streamers.txt exists and is not empty.
2. The script checks for streamlink and ffmpeg at startup and exits if missing.
3. Progress bars may not display correctly in Windows CMD; use PowerShell or --progress-bar.
4. Use --debug for detailed logs to troubleshoot issues.
5. The watchdog thread terminates the script if no progress is detected for 1 hour (configurable).
6. Avoid naming files requests.py or bs4.py in the script directory to prevent module shadowing.
7. put `requests_lib` and `bs4_lib` in the same folder as the `castcorder.py` (optional)
8. if you have 2 version of Python installed, sometimes the system unable to find `requests_lib` and `bs4_lib`

## Limitations:
1. Requires internet access to fetch stream info and thumbnails.
2. Private streams require valid credentials or cookies.
3. Progress bar requires tqdm and a compatible terminal.
4. Login may fail if CAPTCHA is required.

## Troubleshooting:
1. "Streamlink not installed": Install streamlink and ensure it's in PATH.
2. "FFmpeg not installed": Install ffmpeg and ensure it's in PATH.
3. "Stream offline": The stream is not live; the script will retry.
4. "Insufficient disk space": Free up space in the save folder.
5. "Login failed": Check TWITCASTING_USERNAME and TWITCASTING_PASSWORD.
6. Progress bar issues: Disable with --progress-bar or use a different terminal.

## License:
This project is licensed under the MIT License. See LICENSE for details.

## Contributing:
Contributions are welcome! Submit issues or pull requests on GitHub.

## Acknowledgments:
Built with streamlink, ffmpeg, requests, beautifulsoup4, psutil, and tqdm.
Inspired by the need to archive TwitCasting streams reliably.
