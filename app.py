import os
import logging
import requests
import tempfile
import re
import subprocess
import json
import time
import threading
from flask import Flask, request, jsonify
import telebot
from telebot.types import Message
from urllib.parse import urlparse
import m3u8
import shutil
from PyPDF2 import PdfReader, PdfWriter
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Get environment variables
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN environment variable is not set!")
    TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"  # Placeholder for local development

# Initialize the Telegram bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Load authorized users from file
def load_authorized_users():
    try:
        with open('authorized_users.txt', 'r') as f:
            lines = f.readlines()
        
        authorized = {}
        owner_id = None
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            if ':' in line:
                user_id, name = line.split(':', 1)
                user_id = user_id.strip()
                name = name.strip()
                
                if not owner_id:  # First user is the owner
                    owner_id = user_id
                    
                authorized[user_id] = name
        
        return authorized, owner_id
    except Exception as e:
        logger.error(f"Error loading authorized users: {str(e)}")
        return {}, None

# Save authorized users to file
def save_authorized_users(authorized_users, owner_id):
    try:
        lines = ["# Telegram Bot Authorized Users\n# Format: user_id:name\n# The first user is the owner\n"]
        
        # Add owner first
        if owner_id and owner_id in authorized_users:
            lines.append(f"{owner_id}:{authorized_users[owner_id]}\n")
        
        # Add other authorized users
        for user_id, name in authorized_users.items():
            if user_id != owner_id:
                lines.append(f"{user_id}:{name}\n")
        
        with open('authorized_users.txt', 'w') as f:
            f.writelines(lines)
            
        return True
    except Exception as e:
        logger.error(f"Error saving authorized users: {str(e)}")
        return False

# Check if user is authorized
def is_authorized(user_id):
    authorized_users, owner_id = load_authorized_users()
    return str(user_id) in authorized_users

# Check if user is the owner
def is_owner(user_id):
    authorized_users, owner_id = load_authorized_users()
    return str(user_id) == owner_id

# Welcome message handler
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Welcome to the File Downloader Bot! 📥\n\n"
                         "I can download files from URLs and send them back to you.\n"
                         "Use /upload to send me a .txt file with title:url pairs.\n\n"
                         "Note: Only authorized users can use the upload command.")

# Upload command handler
@bot.message_handler(commands=['upload'])
def request_file(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "You don't have access to use this command. Please contact the bot owner.")
        return
        
    bot.reply_to(message, "Please send me a .txt file containing title:url pairs.\n"
                         "Each line should be in the format: title:url")

# File handler
@bot.message_handler(content_types=['document'])
def handle_document(message):
    try:
        # Check if the file is a text file
        file_info = bot.get_file(message.document.file_id)
        if not message.document.file_name.endswith('.txt'):
            bot.reply_to(message, "Please send a .txt file.")
            return

        # Download the file from Telegram
        file_content = bot.download_file(file_info.file_path)
        file_text = file_content.decode('utf-8')
        
        # Process the file content
        lines = file_text.strip().split('\n')
        bot.reply_to(message, f"Processing {len(lines)} URLs. This may take some time...")
        
        # Process each line
        for line in lines:
            try:
                if ':' not in line:
                    continue
                    
                title, url = line.split(':', 1)
                title = title.strip()
                url = url.strip()
                
                if not title or not url:
                    continue
                    
                # Download and upload the file
                download_and_upload(message, title, url)
                
            except Exception as e:
                logger.error(f"Error processing line '{line}': {str(e)}")
                bot.send_message(message.chat.id, f"Error processing: {title}\nError: {str(e)}")
        
        bot.send_message(message.chat.id, "All files have been processed!")
        
    except Exception as e:
        logger.error(f"Error handling document: {str(e)}")
        bot.reply_to(message, f"An error occurred: {str(e)}")

# Authorize user command (owner only)
@bot.message_handler(commands=['authorize'])
def authorize_user(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Only the bot owner can authorize users.")
        return
    
    # Check if the message is a reply to another message
    if not message.reply_to_message:
        bot.reply_to(message, "Please reply to a message from the user you want to authorize.")
        return
    
    # Get the user to authorize
    user_to_authorize = message.reply_to_message.from_user
    user_id = str(user_to_authorize.id)
    user_name = user_to_authorize.first_name
    
    # Load authorized users
    authorized_users, owner_id = load_authorized_users()
    
    # Check if user is already authorized
    if user_id in authorized_users:
        bot.reply_to(message, f"{user_name} is already authorized.")
        return
    
    # Add user to authorized users
    authorized_users[user_id] = user_name
    
    # Save authorized users
    if save_authorized_users(authorized_users, owner_id):
        bot.reply_to(message, f"{user_name} has been authorized to use the bot.")
    else:
        bot.reply_to(message, "Failed to authorize user. Please try again.")

# Revoke user command (owner only)
@bot.message_handler(commands=['revoke'])
def revoke_user(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Only the bot owner can revoke user access.")
        return
    
    # Check if the message is a reply to another message
    if not message.reply_to_message:
        bot.reply_to(message, "Please reply to a message from the user you want to revoke access from.")
        return
    
    # Get the user to revoke
    user_to_revoke = message.reply_to_message.from_user
    user_id = str(user_to_revoke.id)
    user_name = user_to_revoke.first_name
    
    # Load authorized users
    authorized_users, owner_id = load_authorized_users()
    
    # Check if user is the owner
    if user_id == owner_id:
        bot.reply_to(message, "You cannot revoke access from the owner.")
        return
    
    # Check if user is authorized
    if user_id not in authorized_users:
        bot.reply_to(message, f"{user_name} is not authorized.")
        return
    
    # Remove user from authorized users
    del authorized_users[user_id]
    
    # Save authorized users
    if save_authorized_users(authorized_users, owner_id):
        bot.reply_to(message, f"{user_name}'s access has been revoked.")
    else:
        bot.reply_to(message, "Failed to revoke user access. Please try again.")

# List authorized users command (owner only)
@bot.message_handler(commands=['list_users'])
def list_users(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Only the bot owner can list authorized users.")
        return
    
    # Load authorized users
    authorized_users, owner_id = load_authorized_users()
    
    if not authorized_users:
        bot.reply_to(message, "No authorized users found.")
        return
    
    # Create message
    msg = "Authorized Users:\n\n"
    
    for user_id, name in authorized_users.items():
        if user_id == owner_id:
            msg += f"👑 {name} (Owner) - ID: {user_id}\n"
        else:
            msg += f"👤 {name} - ID: {user_id}\n"
    
    bot.reply_to(message, msg)

# Function to download and upload files
def download_and_upload(message, title, url):
    try:
        # Create a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = None
            file_extension = get_file_extension(url)
            
            # Handle different file types
            if '.m3u8' in url or file_extension.lower() in ['.mp4', '.mkv']:
                file_path = download_with_n_m3u8dl(url, title, file_extension, temp_dir)
            else:
                file_path = download_file(url, title, file_extension, temp_dir, message, message.chat.id)
            
            if not file_path or not os.path.exists(file_path):
                bot.send_message(message.chat.id, f"Failed to download: {title}")
                return
            
            # Get file size
            file_size = os.path.getsize(file_path)
            if file_size > 1.5 * 1024 * 1024 * 1024:  # 1.5GB
                bot.send_message(message.chat.id, 
                                f"File {title} is too large ({file_size/(1024*1024*1024):.2f}GB). Maximum size is 1.5GB.")
                return
            
            # Warn user if file is large but under limit
            if file_size > 200 * 1024 * 1024:  # 200MB
                bot.send_message(message.chat.id,
                               f"File {title} is large ({file_size/(1024*1024):.2f}MB). It will be uploaded in chunks to avoid Telegram API limitations.")

            
            # Add "Downloaded by Suraj" to PDF files
            if file_extension.lower() == '.pdf':
                file_path = add_text_to_pdf(file_path, temp_dir)
            
            # Send status message with initial progress bar
            progress_bar = generate_progress_bar(0)
            status_msg = bot.send_message(message.chat.id, f"Uploading {title}{file_extension}... 0%\n{progress_bar}")
            
            # Create caption with "Downloaded by Suraj"
            caption = f"{title}\n\nDownloaded by Suraj"
            
            # Upload the file to Telegram with progress tracking
            # Since Telegram API doesn't provide direct upload progress,
            # we'll simulate progress based on file size
            file_size_mb = file_size / (1024 * 1024)
            estimated_upload_time = file_size_mb * 0.1  # Rough estimate: 0.1 seconds per MB
            upload_steps = min(20, int(file_size_mb))  # Max 20 steps for large files
            if upload_steps < 5:
                upload_steps = 5  # Minimum 5 steps for small files
            
            # Calculate sleep time between progress updates
            sleep_time = estimated_upload_time / upload_steps
            
            # Start upload in a separate thread to avoid blocking
            def upload_with_progress():
                try:
                    # Simulate upload progress
                    for i in range(1, upload_steps):
                        percentage = int((i / upload_steps) * 90)  # Go up to 90%
                        progress_bar = generate_progress_bar(percentage)
                        bot.edit_message_text(
                            f"Uploading {title}{file_extension}... {percentage}%\n{progress_bar}", 
                            message.chat.id, 
                            status_msg.message_id
                        )
                        time.sleep(sleep_time)
                    
                    # Actual upload
                    with open(file_path, 'rb') as file:
                        # Show 95% before actual upload
                        progress_bar = generate_progress_bar(95)
                        bot.edit_message_text(
                            f"Uploading {title}{file_extension}... 95%\n{progress_bar}", 
                            message.chat.id, 
                            status_msg.message_id
                        )
                        
                        # Check file size for chunked upload
                        file_size = os.path.getsize(file_path)
                        
                        if file_size > 45 * 1024 * 1024:  # 45MB - Below Telegram Bot API limit (50MB)
                            # Use the dedicated chunked upload function
                            file.seek(0)
                            upload_in_chunks(file, file_path, title, file_extension, message, status_msg, caption)
                        else:
                            # Standard upload for files under 45MB
                            try:
                                bot.send_document(
                                    message.chat.id,
                                    file,
                                    caption=caption,
                                    reply_to_message_id=message.message_id
                                )
                            except Exception as doc_error:
                                # If we get a 413 error, fall back to chunked upload
                                if "413" in str(doc_error) and "Request Entity Too Large" in str(doc_error):
                                    logger.warning(f"413 error encountered for {title}, switching to chunked upload")
                                    file.seek(0)
                                    upload_in_chunks(file, file_path, title, file_extension, message, status_msg, caption)
                                else:
                                    # Re-raise other errors
                                    raise doc_error
                    
                    # Show 100% when complete
                    progress_bar = generate_progress_bar(100)
                    bot.edit_message_text(
                        f"Upload complete: {title}{file_extension} ✅\n{progress_bar}", 
                        message.chat.id, 
                        status_msg.message_id
                    )
                    
                    # Delete status message after a short delay
                    time.sleep(3)
                    bot.delete_message(message.chat.id, status_msg.message_id)
                except Exception as e:
                    logger.error(f"Error in upload thread: {str(e)}")
                    try:
                        # Check for 413 error specifically
                        if "413" in str(e) and "Request Entity Too Large" in str(e):
                            bot.edit_message_text(
                                f"Error uploading {title}{file_extension}: File too large for Telegram API (413 error).\nRetrying with chunked upload...", 
                                message.chat.id, 
                                status_msg.message_id
                            )
                            # Retry with forced chunked upload
                            with open(file_path, 'rb') as retry_file:
                                upload_in_chunks(retry_file, file_path, title, file_extension, message, status_msg, caption)
                        else:
                            bot.edit_message_text(
                                f"Error uploading {title}{file_extension}: {str(e)}", 
                                message.chat.id, 
                                status_msg.message_id
                            )
                    except Exception as retry_error:
                        logger.error(f"Error in retry upload: {str(retry_error)}")
                        try:
                            bot.edit_message_text(
                                f"Failed to upload {title}{file_extension} after multiple attempts: {str(retry_error)}", 
                                message.chat.id, 
                                status_msg.message_id
                            )
                        except:
                            pass
            
            # Start upload thread
            import threading
            upload_thread = threading.Thread(target=upload_with_progress)
            upload_thread.start()
            
            # Wait for thread to complete (optional, can be removed if you want non-blocking behavior)
            upload_thread.join()
            
    except Exception as e:
        logger.error(f"Error downloading/uploading {title}: {str(e)}")
        bot.send_message(message.chat.id, f"Error processing: {title}\nError: {str(e)}")

# Function to download a file
def download_file(url, title, file_extension, temp_dir, message=None, chat_id=None):
    try:
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        
        file_path = os.path.join(temp_dir, f"{title}{file_extension}")
        
        # Get total file size if available
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        last_percentage = 0
        status_msg = None
        
        if message and chat_id and total_size > 0:
            status_msg = bot.send_message(chat_id, f"Downloading {title}{file_extension}... 0%")
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update progress every 5%
                    if total_size > 0 and message and chat_id:
                        current_percentage = int((downloaded / total_size) * 100)
                        if current_percentage >= last_percentage + 5 or current_percentage == 100:
                            progress_bar = generate_progress_bar(current_percentage)
                            bot.edit_message_text(
                                f"Downloading {title}{file_extension}... {current_percentage}%\n{progress_bar}", 
                                chat_id, 
                                status_msg.message_id
                            )
                            last_percentage = current_percentage
        
        # Delete status message if download completed
        if status_msg:
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except:
                pass
                
        return file_path
    except Exception as e:
        logger.error(f"Error downloading file {url}: {str(e)}")
        return None

# Function to upload file in chunks
def upload_in_chunks(file, file_path, title, file_extension, message, status_msg, caption):
    try:
        file_size = os.path.getsize(file_path)
        
        # Update status message
        progress_bar = generate_progress_bar(10)
        bot.edit_message_text(
            f"Using chunked upload for {title}{file_extension}... 10%\n{progress_bar}", 
            message.chat.id, 
            status_msg.message_id
        )
        
        # Calculate optimal chunk size (max 50MB per chunk)
        max_chunk_size = 45 * 1024 * 1024  # 45MB to be safe
        total_chunks = (file_size + max_chunk_size - 1) // max_chunk_size
        
        # Send chunks
        file.seek(0)
        for chunk_num in range(1, total_chunks + 1):
            # Read chunk
            chunk_data = file.read(max_chunk_size)
            
            # Create appropriate caption
            if total_chunks == 1:
                chunk_caption = caption
            elif chunk_num == total_chunks:
                chunk_caption = f"{title} (Part {chunk_num}/{total_chunks} - Final)\n\nDownloaded by Suraj"
            else:
                chunk_caption = f"{title} (Part {chunk_num}/{total_chunks})\n\nDownloaded by Suraj"
            
            # Send chunk
            bot.send_document(
                message.chat.id,
                chunk_data,
                caption=chunk_caption,
                reply_to_message_id=message.message_id
            )
            
            # Update progress
            progress = min(10 + (chunk_num / total_chunks) * 90, 100)
            progress_bar = generate_progress_bar(int(progress))
            bot.edit_message_text(
                f"Uploading {title}{file_extension}... {int(progress)}%\n{progress_bar}", 
                message.chat.id, 
                status_msg.message_id
            )
            
            # Small delay between chunks to avoid rate limiting
            time.sleep(2)
        
        return True
    except Exception as e:
        logger.error(f"Error in chunked upload: {str(e)}")
        raise Exception(f"Chunked upload failed: {str(e)}")

# Function to generate a progress bar
def generate_progress_bar(percentage, length=20):
    filled_length = int(length * percentage // 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"[{bar}] {percentage}%"

# Function to download with N_m3u8DL-RE
def download_with_n_m3u8dl(url, title, file_extension, temp_dir, message=None, chat_id=None):
    try:
        # Sanitize title for filename
        safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)
        output_file = os.path.join(temp_dir, f"{safe_title}{file_extension}")
        
        # Prepare N_m3u8DL-RE command with .exe extension for Windows
        cmd = [
            "N_m3u8DL-RE.exe",
            "--save-dir", temp_dir,
            "--save-name", safe_title,
            "--thread-count", "16",
            "--auto-select", "true",
            url
        ]
        
        # Send initial status message if message and chat_id are provided
        status_msg = None
        if message and chat_id:
            progress_bar = generate_progress_bar(0)
            status_msg = bot.send_message(chat_id, f"Preparing to download {title} with N_m3u8DL-RE... 0%\n{progress_bar}")
            
        # Run N_m3u8DL-RE with progress updates
        logger.info(f"Running N_m3u8DL-RE for {url}")
        
        # Start process with pipe for output
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
        
        # Track progress
        progress_pattern = re.compile(r'(\d+\.?\d*)%')
        last_percentage = 0
        
        # Read output line by line
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
                
            # Try to extract progress percentage
            match = progress_pattern.search(line)
            if match and status_msg:
                try:
                    current_percentage = float(match.group(1))
                    if int(current_percentage) >= last_percentage + 5 or current_percentage >= 99.5:
                        progress_bar = generate_progress_bar(int(current_percentage))
                        bot.edit_message_text(
                            f"Downloading {title} with N_m3u8DL-RE... {int(current_percentage)}%\n{progress_bar}", 
                            chat_id, 
                            status_msg.message_id
                        )
                        last_percentage = int(current_percentage)
                except Exception as e:
                    logger.error(f"Error updating progress: {str(e)}")
        
        # Wait for process to complete
        process.wait()
        
        # Delete status message if download completed
        if status_msg:
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except:
                pass
        
        if process.returncode != 0:
            logger.error(f"N_m3u8DL-RE error: {process.stderr}")
            # Fallback to yt-dlp if N_m3u8DL-RE fails for m3u8 files
            if url.endswith('.m3u8'):
                return download_with_ytdlp(url, title, temp_dir, message, chat_id)
            else:
                return download_file(url, title, file_extension, temp_dir, message, chat_id)
        
        # Find the downloaded file
        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            if os.path.isfile(file_path) and safe_title in file:
                return file_path
        
        # If file not found, return the expected path
        if os.path.exists(output_file):
            return output_file
        
        # Fallback
        logger.warning(f"N_m3u8DL-RE didn't create expected file, falling back to yt-dlp")
        if url.endswith('.m3u8'):
            return download_with_ytdlp(url, title, temp_dir, message, chat_id)
        else:
            return download_file(url, title, file_extension, temp_dir, message, chat_id)
    except Exception as e:
        logger.error(f"Error using N_m3u8DL-RE for {url}: {str(e)}")
        # Fallback to yt-dlp
        if url.endswith('.m3u8'):
            return download_with_ytdlp(url, title, temp_dir, message, chat_id)
        else:
            return download_file(url, title, file_extension, temp_dir, message, chat_id)

# Function to download m3u8 files using yt-dlp (preferred fallback)
def download_with_ytdlp(url, title, temp_dir, message=None, chat_id=None):
    try:
        # Sanitize title for filename
        safe_title = re.sub(r'[\/*?:"<>|]', "_", title)
        output_file = os.path.join(temp_dir, f"{safe_title}.mp4")
        
        # Send initial status message if message and chat_id are provided
        status_msg = None
        if message and chat_id:
            progress_bar = generate_progress_bar(0)
            status_msg = bot.send_message(chat_id, f"Downloading {title} with yt-dlp... 0%\n{progress_bar}")
        
        # Prepare yt-dlp command
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--format", "best",
            "--output", output_file,
            "--no-warnings",
            url
        ]
        
        # Run yt-dlp with progress updates
        logger.info(f"Running yt-dlp for {url}")
        
        # Start process with pipe for output
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
        
        # Track progress
        progress_pattern = re.compile(r'(\d+\.?\d*)%')
        last_percentage = 0
        
        # Read output line by line
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
                
            # Try to extract progress percentage
            match = progress_pattern.search(line)
            if match and status_msg:
                try:
                    current_percentage = float(match.group(1))
                    if int(current_percentage) >= last_percentage + 5 or current_percentage >= 99.5:
                        progress_bar = generate_progress_bar(int(current_percentage))
                        bot.edit_message_text(
                            f"Downloading {title} with yt-dlp... {int(current_percentage)}%\n{progress_bar}", 
                            chat_id, 
                            status_msg.message_id
                        )
                        last_percentage = int(current_percentage)
                except Exception as e:
                    logger.error(f"Error updating progress: {str(e)}")
        
        # Wait for process to complete
        process.wait()
        
        # Delete status message if download completed
        if status_msg:
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except:
                pass
        
        if process.returncode != 0:
            logger.error(f"yt-dlp error: {process.stderr}")
            # Fallback to original m3u8 method if yt-dlp fails
            return download_m3u8_fallback(url, title, temp_dir, message, chat_id)
        
        if os.path.exists(output_file):
            return output_file
        else:
            # Fallback to original m3u8 method if file not found
            return download_m3u8_fallback(url, title, temp_dir, message, chat_id)
    except Exception as e:
        logger.error(f"Error using yt-dlp for {url}: {str(e)}")
        # Fallback to original m3u8 method
        return download_m3u8_fallback(url, title, temp_dir, message, chat_id)

# Function to download m3u8 files (original fallback method)
def download_m3u8_fallback(url, title, temp_dir, message=None, chat_id=None):
    try:
        # Parse the m3u8 file
        m3u8_obj = m3u8.load(url)
        
        if m3u8_obj.is_variant:
            # Get the highest quality stream
            playlist = sorted(m3u8_obj.playlists, key=lambda x: x.stream_info.bandwidth, reverse=True)[0]
            playlist_url = playlist.uri
            
            # Handle relative URLs
            if not playlist_url.startswith('http'):
                base_url = url.rsplit('/', 1)[0]
                playlist_url = f"{base_url}/{playlist_url}"
            
            # Load the actual playlist
            m3u8_obj = m3u8.load(playlist_url)
        
        # Create output file
        output_file = os.path.join(temp_dir, f"{title}.mp4")
        
        # Download all segments
        segments_dir = os.path.join(temp_dir, "segments")
        os.makedirs(segments_dir, exist_ok=True)
        
        base_url = url.rsplit('/', 1)[0] if '/' in url else ''
        
        # Send initial status message if message and chat_id are provided
        status_msg = None
        if message and chat_id:
            progress_bar = generate_progress_bar(0)
            status_msg = bot.send_message(chat_id, f"Downloading m3u8 segments for {title}... 0%\n{progress_bar}")
        
        # Download each segment
        segment_files = []
        total_segments = len(m3u8_obj.segments)
        
        for i, segment in enumerate(m3u8_obj.segments):
            segment_url = segment.uri
            if not segment_url.startswith('http'):
                segment_url = f"{base_url}/{segment_url}"
            
            segment_file = os.path.join(segments_dir, f"segment_{i:05d}.ts")
            download_file(segment_url, f"segment_{i:05d}", ".ts", segments_dir)
            segment_files.append(segment_file)
            
            # Update progress every 5% or for every 10 segments
            if message and chat_id and (i % 10 == 0 or i == total_segments - 1):
                percentage = int((i + 1) / total_segments * 100)
                progress_bar = generate_progress_bar(percentage)
                try:
                    bot.edit_message_text(
                        f"Downloading m3u8 segments for {title}... {percentage}%\n{progress_bar}\nSegment {i+1}/{total_segments}", 
                        chat_id, 
                        status_msg.message_id
                    )
                except Exception as e:
                    logger.error(f"Error updating m3u8 progress: {str(e)}")
        
        # Update status message for concatenation phase
        if status_msg:
            try:
                bot.edit_message_text(
                    f"Combining segments for {title}... Please wait.", 
                    chat_id, 
                    status_msg.message_id
                )
            except:
                pass
                
        # Concatenate segments
        with open(output_file, 'wb') as outfile:
            for segment_file in segment_files:
                if os.path.exists(segment_file):
                    with open(segment_file, 'rb') as infile:
                        outfile.write(infile.read())
        
        # Delete status message if download completed
        if status_msg:
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except:
                pass
        
        return output_file
    except Exception as e:
        logger.error(f"Error downloading m3u8 {url}: {str(e)}")
        return None

# Function to add text to PDF
def add_text_to_pdf(pdf_path, temp_dir):
    try:
        # Create a new PDF path
        filename = os.path.basename(pdf_path)
        new_pdf_path = os.path.join(temp_dir, f"modified_{filename}")
        
        # Open the PDF
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        
        # Copy all pages
        for page in reader.pages:
            writer.add_page(page)
        
        # Add metadata
        writer.add_metadata({
            "/Producer": "Telegram Bot",
            "/CreationDate": datetime.now().strftime("D:%Y%m%d%H%M%S"),
            "/ModDate": datetime.now().strftime("D:%Y%m%d%H%M%S"),
            "/Custom": "Downloaded by Suraj"
        })
        
        # Write the modified PDF
        with open(new_pdf_path, "wb") as f:
            writer.write(f)
        
        return new_pdf_path
    except Exception as e:
        logger.error(f"Error adding text to PDF: {str(e)}")
        return pdf_path  # Return original if modification fails

# Function to get file extension from URL
def get_file_extension(url):
    parsed_url = urlparse(url)
    path = parsed_url.path
    
    # Extract extension from path
    _, ext = os.path.splitext(path)
    
    # If no extension or not a common file type, try to determine from URL
    if not ext or ext == '.':
        if 'm3u8' in url:
            return '.mp4'  # m3u8 will be converted to mp4
        elif re.search(r'\.(mp4|pdf|zip|rar|jpg|jpeg|png|gif)([?#].*)?$', url, re.IGNORECASE):
            match = re.search(r'\.(mp4|pdf|zip|rar|jpg|jpeg|png|gif)([?#].*)?$', url, re.IGNORECASE)
            return f'.{match.group(1).lower()}'
        else:
            return ''  # Default empty extension
    
    return ext

# Webhook route for Telegram
@app.route(f'/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return jsonify({'status': 'ok'})
    else:
        return jsonify({'status': 'error', 'message': 'Invalid content type'})

# Health check route
@app.route('/')
def index():
    return jsonify({'status': 'ok', 'message': 'Bot is running'})

# Set webhook route
@app.route('/set_webhook')
def set_webhook():
    url = request.args.get('url')
    if not url:
        return jsonify({'status': 'error', 'message': 'URL parameter is required'})
    
    webhook_url = f"{url}/{TELEGRAM_BOT_TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(webhook_url)
    return jsonify({'status': 'ok', 'message': f'Webhook set to {webhook_url}'})

# Remove webhook route
@app.route('/remove_webhook')
def remove_webhook():
    bot.remove_webhook()
    return jsonify({'status': 'ok', 'message': 'Webhook removed'})

if __name__ == '__main__':
    # Check if running in production or development
    if os.environ.get('FLASK_ENV') == 'development':
        # For local development, remove any existing webhook and use polling
        bot.remove_webhook()
        bot.polling()
    else:
        # For production, use the webhook
        port = int(os.environ.get("PORT", 10000))
        app.run(host="0.0.0.0", port=port)