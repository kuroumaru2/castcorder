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