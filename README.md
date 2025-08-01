# Castcorder

A Python script to record live streams from TwitCasting, with support for automatic stream detection, HLS recording, metadata embedding, and thumbnail downloading. This script monitors a specified TwitCasting streamer's channel, detects when the stream goes live, and records it to a local file in MKV format with embedded metadata and optional thumbnails. It uses `yt-dlp`, `ffmpeg`, and `ffprobe` for stream fetching, processing, and analysis, with robust error handling and logging.

## Features
- **Automatic Stream Detection**: Continuously monitors a TwitCasting streamer's channel and starts recording when the stream is live.
- **HLS Recording**: Records streams using HLS URLs fetched via `yt-dlp` or provided manually.
- **Metadata Embedding**: Adds stream title, streamer name, date, and stream ID to the recorded file.
- **Thumbnail Support**: Optionally downloads and attaches stream thumbnails to the output MKV file.
- **Progress Monitoring**: Displays real-time recording progress with file size, duration, and bitrate.
- **Robust Error Handling**: Handles network issues, process termination, and file cleanup gracefully.
- **Configurable Options**: Supports command-line arguments for streamer selection, quality, and more.
- **Logging**: Detailed logging to both file and console for debugging and monitoring.
- **Disk Space Check**: Ensures sufficient disk space before recording (minimum 5 GB).
- **Signal Handling**: Gracefully handles interruptions (Ctrl+C) with optional fast-exit mode.

## Prerequisites
Before running the script, ensure the following dependencies are installed:

## Required Software
1. **Python 3.6+**: The script requires a compatible Python version.
2. **FFmpeg**: For recording, repairing, converting streams to MKV, and analyzing stream duration (includes `ffmpeg` and `ffprobe`).
   - Ubuntu/Debian:

         sudo apt-get install ffmpeg
         sudo apt-get install ffprobe
     
   - macOS (Homebrew):

         brew install ffmpeg
     
   - Windows: Download from [FFmpeg website](https://ffmpeg.org/download.html) and add to PATH.
3. **yt-dlp**: For fetching HLS URLs and recording streams.

         pip install yt-dlp
   
## Python Dependencies
requests: For fetching stream metadata and thumbnails.

         pip install requests

beautifulsoup4: For parsing stream metadata from TwitCasting pages.

         pip install beautifulsoup4

psutil (optional): Enhances process termination handling.

         pip install psutil

## Installation
Clone or download this repository:

         git clone https://github.com/kuroumaru2/castcorder.git
         
         cd castcorder

Install Python dependencies:

         pip install -r requirements.txt
       
Ensure ffmpeg, ffprobe, and yt-dlp are installed and accessible in your system PATH.

## Usage
Run the script from the command line with optional arguments to customize its behavior.
Basic Command
         
         python castcorder.py
         
Command-Line Arguments

         --streamer <username>
Specify a streamer username (e.g., streamer1).

         --quality <quality>
Stream quality (default: best).

         --streamers-file <path>
Path to a file containing streamer usernames (default: streamers.txt in script directory).

         --debug
Enable verbose logging for debugging.

         --fast-exit
Skip cleanup on exit (e.g., Ctrl+C).

         --hls-url <url>
Manually specify an HLS URL to record (e.g., https://example.com/stream.m3u8).

Example:
Record a specific streamer's channel with debug logging:

         python castcorder.py --streamer streamer1 --quality best --debug

## Configuration
Environment Variables
Set these in your environment or in a config.ini file in the script directory:

         TWITCASTING_USERNAME: TwitCasting login username.
         TWITCASTING_PASSWORD: TwitCasting login password.
         PRIVATE_STREAM_PASSWORD: Password for private streams.
         CHECK_INTERVAL: Stream check interval in seconds (default: 15).
         RETRY_DELAY: Delay between retries in seconds (default: 15).
         HLS_URL: Manually specify an HLS URL.
         
Example:

         export TWITCASTING_USERNAME="your_username"
         export TWITCASTING_PASSWORD="your_password"
         python castcorder.py --streamer streamer1

Config File
Create a config.ini file in the script directory:
         
         ini
         [castcorder]
         check_interval = 15
         retry_delay = 15
         twitcasting_username = your_username
         twitcasting_password = your_password
         private_stream_password = your_private_stream_password
         hls_url = https://example.com/stream.m3u8
         
Streamers File
Create a streamers.txt file in the script directory with one username per line:

         streamer1
         streamer2
         streamer3
If --streamer is not provided, the script prompts to select a streamer from this list.

## Cookies
A cookies.txt file is required in the script directory for authenticated streams.

## Output
1. Recordings: Saved in [script_directory]/[streamer_name]/ as MKV files.
2. Filename Format: [<YYYYMMDD>] <title> [<username>][stream_id].mkv
3. Thumbnails: Attached to MKV files if available.
4. Log File: Saved as [script_directory]/[streamer_name]/twitcast_recorder_[streamer_name].log or twitcast_recorder_direct.log for direct HLS recordings.
5. Backup Files: Incomplete or failed files are moved to [script_directory]/[streamer_name]/backup/.

## Notes
1. Ensure streamers.txt exists and is not empty if using the streamers file.
2. The script checks for ffmpeg, ffprobe, and yt-dlp at startup and exits if missing.
3. Disk space is checked before recording (minimum 5 GB required).
4. Interrupt with Ctrl+C to stop gracefully. Use --fast-exit for instant termination (may leave temporary files).
5. Filenames are sanitized for file system compatibility and limited to 255 characters.
6. Avoid naming files requests.py or bs4.py in the script directory to prevent module shadowing.
7. If you have multiple Python versions installed, ensure pip installs packages for the correct version.

## Limitations
1. Requires internet access to fetch stream info and thumbnails.
2. Private streams require valid cookies or credentials.
3. Login may fail if CAPTCHA is required.
4. Unicode errors may occur in terminals without UTF-8 support.

## Troubleshooting
1. "FFmpeg or ffprobe not installed": Install ffmpeg (which includes ffprobe) and ensure it's in PATH.
3. "yt-dlp not installed": Install yt-dlp via pip.
4. "Stream offline": The stream is not live; the script will retry.
5. "Cookies file not found": Ensure cookies.txt exists in the script directory.
6. "Insufficient disk space": Free up at least 5 GB in the save directory.
7. "Login failed": Verify TWITCASTING_USERNAME, TWITCASTING_PASSWORD, or cookies.txt.
8. HLS URL fetch fails: Check internet connection, cookies, or provide a manual --hls-url.
9. Script hangs: Enable --debug and check the log file for details.
10. Duration parsing errors: Ensure ffprobe is installed and accessible.

## License
This project is licensed under the MIT License. See LICENSE for details.

## Contributing
Contributions are welcome! Submit issues or pull requests on GitHub.

## Acknowledgments
Built with yt-dlp, ffmpeg, ffprobe, requests, beautifulsoup4, and psutil.
Inspired by the need to reliably archive TwitCasting streams.
