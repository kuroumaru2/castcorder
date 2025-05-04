# Castcorder

**Castcorder** is a Python script designed to record live streams from [TwitCasting](https://twitcasting.tv/). It monitors specified streamers, records their live streams using [Streamlink](https://streamlink.github.io/), converts recordings to MKV format, and adds metadata. The script supports private streams with passwords and handles authentication via cookies.

## Features
- Monitor and record live streams from TwitCasting.
- Support for private streams with password authentication.
- Automatic conversion of recordings to MKV format.
- Metadata embedding (title, streamer name, timestamp, etc.).
- Thumbnail downloading and embedding (when available).
- Progress monitoring with optional progress bars (via `tqdm`).
- Robust error handling and logging.

## License
This project is released into the public domain under the [Unlicense](LICENSE). See the `LICENSE` file for details.

## Requirements
- Python 3.6 or higher
- [FFmpeg](https://ffmpeg.org/) (for MKV conversion)
- Required Python packages:
  - `streamlink`
  - `requests`
  - `beautifulsoup4`
  - `tqdm` (optional, for progress bars)

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/castcorder.git
   cd castcorder

## Usage 
 1. Create a streamers.txt file in the project directory and add one TwitCasting username per line (e.g., streamer1, streamer2).
	(Optional) Set environment variables for authentication:
    ```bash
    export TWITCASTING_USERNAME="your_username"
    export TWITCASTING_PASSWORD="your_password"
    export PRIVATE_STREAM_PASSWORD="stream_password"
    export TWITCASTING_COOKIES="cookie_name1=value1; cookie_name2=value2"

3. On Windows, use set instead of export:
   ```bash
   set TWITCASTING_USERNAME=your_username"
   set TWITCASTING_PASSWORD="your_password"
   set PRIVATE_STREAM_PASSWORD="stream_password"
   set TWITCASTING_COOKIES="cookie_name1=value1; cookie_name2=value2"

Note: Store these in a secure location (e.g., a .env file with python-dotenv or your system's environment variables). Never commit sensitive data to the repository.


## Run the script:
    python castcorder.py [username]

If [username] is provided, it will attempt to record that streamer (must be in streamers.txt).
If no username is provided, the script will prompt you to select a streamer from streamers.txt.

## Configuration
  Quality: Defaults to best. Modify the QUALITY variable in the script to change stream quality (e.g., 720p, audio_only).
  Save Folder: Recordings are saved to a subfolder named after the streamer (e.g., ./streamer_name/).
  Check Interval: The script checks for live streams every 15 seconds (CHECK_INTERVAL).
  Retry Delay: After a recording attempt, the script waits 15 seconds before retrying (RETRY_DELAY).

## The script will:
  Check if example_streamer is live.
  Record the stream to an MP4 file with a filename like [YYYYMMDD] Stream Title [example_streamer][stream_id].mp4.
  Convert the recording to MKV with metadata and an optional thumbnail.
  Save the recording to ./example_streamer/.
  Notes
  Ensure streamers.txt exists and contains valid TwitCasting usernames.
  Private streams require PRIVATE_STREAM_PASSWORD to be set.
  Authentication cookies (TWITCASTING_COOKIES) or login credentials (TWITCASTING_USERNAME and TWITCASTING_PASSWORD) may be needed for protected streams.
  The script logs activity to both the console and a file in the streamer's save folder (e.g., ./streamer_name/streamer_name_twitcasting_recorder.log).

## Troubleshooting
  "tqdm not installed": Install it with pip install tqdm for progress bars.
  "Streamlink check failed": Ensure Streamlink is installed (pip install streamlink) and FFmpeg is in your system PATH.
  "Recording file is empty": Check if the stream is live and accessible. Verify authentication settings.
  Shadowing files: Ensure no files like requests.py or bs4.py exist in the script directory, as they can conflict with Python modules.
  Contributing
  Contributions are welcome! Please open an issue or submit a pull request on GitHub.

## Disclaimer
  This script is provided for personal use. Ensure you comply with TwitCasting's terms of service and applicable laws when recording streams. The authors are not responsible for misuse of this software.


