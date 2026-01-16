import telegram
from telegram import InputFile
import asyncio
import logging
from pathlib import Path
from typing import Optional
import tempfile
import subprocess

class TelegramBot:
    def __init__(self, config: dict):
        self.bot_token = config['bot_token']
        self.chat_id = config['chat_id']
        self.max_video_size = config.get('max_video_size_mb', 50) * 1024 * 1024
        
        # Initialize bot
        self.bot = telegram.Bot(token=self.bot_token)
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
    
    def send_photo(self, image_path: Path, caption: str = ""):
        """Send photo to Telegram"""
        try:
            with open(image_path, 'rb') as photo:
                asyncio.run(self._send_photo_async(photo, caption))
            self.logger.info(f"Photo sent: {image_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send photo: {e}")
            return False
    
    def send_video(self, video_path: Path, caption: str = ""):
        """Send video to Telegram"""
        try:
            # Check file size
            file_size = video_path.stat().st_size
            
            if file_size > self.max_video_size:
                # Compress video
                compressed_path = self.compress_video(video_path)
                if compressed_path:
                    video_path = compressed_path
                else:
                    self.logger.warning("Video too large, sending as document")
                    return self.send_document(video_path, caption)
            
            with open(video_path, 'rb') as video:
                asyncio.run(self._send_video_async(video, caption))
            
            self.logger.info(f"Video sent: {video_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send video: {e}")
            return False
    
    def send_document(self, file_path: Path, caption: str = ""):
        """Send file as document (for large videos)"""
        try:
            with open(file_path, 'rb') as doc:
                asyncio.run(self._send_document_async(doc, caption))
            self.logger.info(f"Document sent: {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send document: {e}")
            return False
    
    def compress_video(self, video_path: Path) -> Optional[Path]:
        """Compress video using FFmpeg"""
        try:
            temp_dir = tempfile.gettempdir()
            output_path = Path(temp_dir) / f"compressed_{video_path.name}"
            
            # FFmpeg command to compress video
            cmd = [
                'ffmpeg', '-i', str(video_path),
                '-vcodec', 'libx264',
                '-crf', '28',  # Compression quality (lower = better)
                '-preset', 'fast',
                '-acodec', 'aac',
                str(output_path)
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            
            # Check if compressed file is small enough
            if output_path.stat().st_size < self.max_video_size:
                return output_path
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to compress video: {e}")
            return None
    
    async def _send_photo_async(self, photo, caption: str):
        """Async method to send photo"""
        await self.bot.send_photo(
            chat_id=self.chat_id,
            photo=photo,
            caption=caption,
            parse_mode='HTML'
        )
    
    async def _send_video_async(self, video, caption: str):
        """Async method to send video"""
        await self.bot.send_video(
            chat_id=self.chat_id,
            video=video,
            caption=caption,
            parse_mode='HTML',
            supports_streaming=True
        )
    
    async def _send_document_async(self, document, caption: str):
        """Async method to send document"""
        await self.bot.send_document(
            chat_id=self.chat_id,
            document=document,
            caption=caption,
            parse_mode='HTML'
        )