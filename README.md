# Telegram File Downloader Bot

A Telegram bot built with Python and Flask that can download files from URLs and upload them back to Telegram. The bot can handle files up to 1.5GB in size and supports various file formats including .mp4, .m3u8, and .pdf.

## Features

- Welcome message with `/start` command
- File upload handling with `/upload` command
- Processes .txt files containing title:url pairs
- Downloads files from URLs (supports .mp4, .m3u8, .pdf, and more)
- Uploads files back to Telegram (private chats, groups, or channels)
- Supports files up to 1.5GB
- Uses N_m3u8DL-RE for efficient downloading of .m3u8, .mp4, and .mkv files
- Adds "Downloaded by Suraj" to PDF metadata and all file captions
- User authorization system with owner privileges

## Setup

### Local Development

1. Clone this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set your Telegram Bot Token as an environment variable:
   ```
   # On Windows
   set TELEGRAM_BOT_TOKEN=your_bot_token_here
   
   # On Linux/Mac
   export TELEGRAM_BOT_TOKEN=your_bot_token_here
   ```
4. Run the bot locally:
   ```
   python app.py
   ```

### Deployment on Render

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Use the following settings:
   - Environment: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
4. Add the environment variable `TELEGRAM_BOT_TOKEN` with your bot token
5. Deploy the service
6. Once deployed, set the webhook by visiting:
   ```
   https://your-render-url.onrender.com/set_webhook?url=https://your-render-url.onrender.com
   ```

### Deployment on Koyeb (Free Tier)

1. Sign up for a free Koyeb account at [koyeb.com](https://www.koyeb.com/)
2. Install the Koyeb CLI or use the Koyeb web dashboard
3. Connect your GitHub repository to Koyeb
4. Deploy using the provided Dockerfile and koyeb.yaml configuration:
   - The free tier includes 2 nano services with shared CPU and 512MB RAM
   - Koyeb will automatically build and deploy your application
5. Add the `TELEGRAM_BOT_TOKEN` secret in the Koyeb dashboard
6. Once deployed, set the webhook by visiting:
   ```
   https://your-koyeb-app-url.koyeb.app/set_webhook?url=https://your-koyeb-app-url.koyeb.app
   ```

## Usage

1. Start a chat with your bot and send `/start` to get a welcome message
2. Send `/upload` to be prompted to upload a .txt file
3. Upload a .txt file with each line in the format `title:url`
4. The bot will download each file and upload it back to the chat

## File Format

The .txt file should contain one URL per line in the following format:
```
title1:http://example.com/file1.mp4
title2:http://example.com/file2.pdf
title3:http://example.com/playlist.m3u8
```

## Notes

- For .m3u8 files, the bot will download all segments and combine them into a single MP4 file
- Files larger than 1.5GB will not be processed due to Telegram's file size limitations