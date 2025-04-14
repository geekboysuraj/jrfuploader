import os
import logging
import requests
import tempfile
import re
import subprocess
import json
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
                file_path = download_file(url, title, file_extension, temp_dir)
            
            if not file_path or not os.path.exists(file_path):
                bot.send_message(message.chat.id, f"Failed to download: {title}")
                return
            
            # Get file size
            file_size = os.path.getsize(file_path)
            if file_size > 1.5 * 1024 * 1024 * 1024:  # 1.5GB
                bot.send_message(message.chat.id, 
                                f"File {title} is too large ({file_size/(1024*1024*1024):.2f}GB). Maximum size is 1.5GB.")
                return
            
            # Add "Downloaded by Suraj" to PDF files
            if file_extension.lower() == '.pdf':
                file_path = add_text_to_pdf(file_path, temp_dir)
            
            # Send status message
            status_msg = bot.send_message(message.chat.id, f"Uploading {title}{file_extension}...")
            
            # Create caption with "Downloaded by Suraj"
            caption = f"{title}\n\nDownloaded by Suraj"
            
            # Upload the file to Telegram
            with open(file_path, 'rb') as file:
                bot.send_document(
                    message.chat.id,
                    file,
                    caption=caption,
                    reply_to_message_id=message.message_id
                )
            
            # Delete status message
            bot.delete_message(message.chat.id, status_msg.message_id)
            
    except Exception as e:
        logger.error(f"Error downloading/uploading {title}: {str(e)}")
        bot.send_message(message.chat.id, f"Error processing: {title}\nError: {str(e)}")

# Function to download a file
def download_file(url, title, file_extension, temp_dir):
    try:
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        
        file_path = os.path.join(temp_dir, f"{title}{file_extension}")
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        return file_path
    except Exception as e:
        logger.error(f"Error downloading file {url}: {str(e)}")
        return None

# Function to download with N_m3u8DL-RE
def download_with_n_m3u8dl(url, title, file_extension, temp_dir):
    try:
        # Sanitize title for filename
        safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)
        output_file = os.path.join(temp_dir, f"{safe_title}{file_extension}")
        
        # Prepare N_m3u8DL-RE command
        cmd = [
            "N_m3u8DL-RE",
            "--save-dir", temp_dir,
            "--save-name", safe_title,
            "--thread-count", "16",
            "--auto-select", "true",
            url
        ]
        
        # Run N_m3u8DL-RE
        logger.info(f"Running N_m3u8DL-RE for {url}")
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            logger.error(f"N_m3u8DL-RE error: {process.stderr}")
            # Fallback to old method if N_m3u8DL-RE fails
            if url.endswith('.m3u8'):
                return download_m3u8_fallback(url, title, temp_dir)
            else:
                return download_file(url, title, file_extension, temp_dir)
        
        # Find the downloaded file
        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            if os.path.isfile(file_path) and safe_title in file:
                return file_path
        
        # If file not found, return the expected path
        if os.path.exists(output_file):
            return output_file
        
        # Fallback
        logger.warning(f"N_m3u8DL-RE didn't create expected file, falling back to standard method")
        if url.endswith('.m3u8'):
            return download_m3u8_fallback(url, title, temp_dir)
        else:
            return download_file(url, title, file_extension, temp_dir)
    except Exception as e:
        logger.error(f"Error using N_m3u8DL-RE for {url}: {str(e)}")
        # Fallback to old method
        if url.endswith('.m3u8'):
            return download_m3u8_fallback(url, title, temp_dir)
        else:
            return download_file(url, title, file_extension, temp_dir)

# Function to download m3u8 files (fallback method)
def download_m3u8_fallback(url, title, temp_dir):
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
        
        # Download each segment
        segment_files = []
        for i, segment in enumerate(m3u8_obj.segments):
            segment_url = segment.uri
            if not segment_url.startswith('http'):
                segment_url = f"{base_url}/{segment_url}"
            
            segment_file = os.path.join(segments_dir, f"segment_{i:05d}.ts")
            download_file(segment_url, f"segment_{i:05d}", ".ts", segments_dir)
            segment_files.append(segment_file)
        
        # Concatenate segments
        with open(output_file, 'wb') as outfile:
            for segment_file in segment_files:
                if os.path.exists(segment_file):
                    with open(segment_file, 'rb') as infile:
                        outfile.write(infile.read())
        
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
    # For local development, remove any existing webhook and use polling
    bot.remove_webhook()
    bot.polling()
    
    # For production, use the webhook
    # port = int(os.environ.get("PORT", 5000))
    # app.run(host="0.0.0.0", port=port)