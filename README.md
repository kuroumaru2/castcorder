# Castcorder

A Python script to record live streams from TwitCasting, with support for automatic stream detection, HLS recording, metadata embedding, and thumbnail downloading.
This script monitors a specified TwitCasting streamer's channel, detects when the stream goes live, and records it to a local file in MKV format with embedded metadata and optional thumbnails. It uses tools like streamlink, ffmpeg, and yt-dlp to handle stream fetching and processing, with robust error handling and logging.


## Features:
1. Automatic Stream Detection: Continuously monitors a TwitCasting streamer's channel and starts recording when the stream is live.
2. HLS Recording: Records streams using HLS URLs fetched via yt-dlp or provided manually.
3. Metadata Embedding: Adds stream title, streamer name, timestamp, and comments to the recorded file.
4. Thumbnail Support: Optionally downloads and attaches stream thumbnails to the output file.
5. Progress Monitoring: Displays real-time recording progress with file size, duration, and speed (optional tqdm progress bar).
6. Robust Error Handling: Handles network issues, process termination, and file cleanup gracefully.
7. Configurable Options: Supports command-line arguments for streamer selection, quality, save folder, and more.
8. Watchdog Thread: Ensures the script terminates if no progress is detected for an extended period.
9. Logging: Detailed logging to both file and console for debugging and monitoring.

## Prerequisites
Before running the script, ensure the following dependencies are installed:

Required Software
1. Python 3.6+: The script is written in Python and requires a compatible version.
2. Streamlink: For stream detection and recording.

       pip install streamlink

3. FFmpeg: For converting recordings to MKV and embedding metadata.
  # Ubuntu/Debian
       sudo apt-get install ffmpeg
  # macOS (Homebrew)
       brew install ffmpeg
4. yt-dlp: For fetching HLS URLs from TwitCasting.

       pip install yt-dlp
## Dependencies
1. psutil: Enhances process termination (recommended).

        pip install psutil

2. tqdm: Displays a progress bar for recording (optional, may not work in all terminals).

        pip install tqdm

3. requests: Required for fetching stream metadata and thumbnails.

        pip install requests

4. beautifulsoup4: Required for parsing stream metadata from TwitCasting pages.

        pip install beautifulsoup4

## Installation:
1. Clone or download this repository.

        git clone https://github.com/kuroumaru2/castcorder.git
        cd castcorder.py

2. Install the required Python dependencies:

        pip install -r requirements.txt


Ensure streamlink, ffmpeg, and yt-dlp are installed and accessible in your system PATH.

## Usage:
Run the script from the command line with optional arguments to customize its behavior

Basic Command

    python castcorder.py

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
10. --hls-url <url>: Manually specify an HLS URL to record (e.g., https://example.com/stream.m3u8).


Example:
Record a specific streamer's channel with debug logging and a progress bar:


    python castcorder.py --streamer streamer1 --quality best --debug --progress-bar

## Environment Variables
1. TWITCASTING_USERNAME: TwitCasting login username.
2. TWITCASTING_PASSWORD: TwitCasting login password.
3. PRIVATE_STREAM_PASSWORD: Password for private streams.
4. TWITCASTING_COOKIES: Cookies for authenticated sessions.
5. CHECK_INTERVAL: Stream check interval in seconds (default: 15).
6. RETRY_DELAY: Delay between retries in seconds (default: 15).
7. STREAMLINK_TIMEOUT: Streamlink output timeout in seconds (default: 1800).
8. HLS_URL: Manually specify an HLS URL (same as --hls-url).

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
3. Thumbnails: Optionally saved and attached to MKV files if available.
4. Log file: [save_folder]/[streamer_name]/[streamer_name]_twitcasting_recorder.log
5. Backup Files: Temporary or incomplete files are moved to <save_folder>/backup/ during cleanup.
6. Temporary files (e.g., MP4, thumbnails) are cleaned up after conversion.

## Notes:
1. Ensure streamers.txt exists and is not empty.
2. The script checks for streamlink and ffmpeg at startup and exits if missing.
3. Progress bars may not display correctly in Windows CMD; use PowerShell or --progress-bar.
4. Use --debug for detailed logs to troubleshoot issues.
5. The watchdog thread terminates the script if no progress is detected for 1 hour (configurable).
6. Avoid naming files requests.py or bs4.py in the script directory to prevent module shadowing.
7. put `requests_lib` and `bs4_lib` in the same folder as the `castcorder.py` (optional)
8. if you have 2 version of Python installed, sometimes the system unable to find `requests_lib` and `bs4_lib`
9. Disk Space: The script checks for at least 100 MB of free disk space before recording.
10. Interrupt Handling: Press Ctrl+C to stop the script gracefully. Use --fast-exit for instant termination (may leave temporary files).
11. File Naming: Filenames are sanitized to avoid invalid characters and limited to 200 characters.

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
7. HLS URL fetch fails: Check your internet connection or provide a manual --hls-url. For private streams, ensure valid credentials are set.
8. Unicode errors: Ensure your terminal supports UTF-8 encoding.
9. Script hangs: Enable --debug to diagnose issues and check the log file.

## License:
This project is licensed under the MIT License. See LICENSE for details.

## Contributing:
Contributions are welcome! Submit issues or pull requests on GitHub.

## Acknowledgments:
Built with streamlink, ffmpeg, requests, beautifulsoup4, psutil, and tqdm.
Inspired by the need to archive TwitCasting streams reliably.
