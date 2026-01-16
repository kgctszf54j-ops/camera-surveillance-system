#!/usr/bin/env python3
"""
Main surveillance system controller
"""
import cv2
import time
import logging
import yaml
import signal
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
import threading
import queue

from motion_detector import MotionDetector
from recorder import VideoRecorder
from telegram_bot import TelegramBot
from video_processor import VideoProcessor

class SurveillanceSystem:
    def __init__(self, config_path: str = "config.yaml"):
        self.load_config(config_path)
        self.setup_logging()
        self.running = False
        
        # Initialize components
        self.motion_detectors = {}
        self.recorders = {}
        self.telegram_bot = TelegramBot(self.config['telegram'])
        self.video_processor = VideoProcessor(self.config['timestamp'])
        
        # Camera states
        self.camera_states = {}
        self.frame_queues = {}
        
    def load_config(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Create directories
        Path(self.config['recording']['output_dir']).mkdir(exist_ok=True)
        Path(self.config['system']['temp_dir']).mkdir(exist_ok=True)
        Path("logs").mkdir(exist_ok=True)
    
    def setup_logging(self):
        logging.basicConfig(
            level=getattr(logging, self.config['system']['log_level']),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config['system']['log_file']),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def initialize_camera(self, camera_id: str, camera_config: Dict):
        """Initialize a camera stream"""
        try:
            # Create motion detector for this camera
            roi = camera_config.get('roi', [0, 0, 1, 1])
            motion_detector = MotionDetector(
                roi_percentage=roi,
                threshold=camera_config.get('motion_threshold', 500),
                min_motion_frames=camera_config.get('min_motion_frames', 10)
            )
            
            # Create recorder for this camera
            recorder = VideoRecorder(
                output_dir=self.config['recording']['output_dir'],
                camera_name=camera_id,
                resolution=self.config['recording']['resolution'],
                fps=self.config['recording']['fps'],
                codec=self.config['recording']['video_codec']
            )
            
            # Initialize camera state
            self.camera_states[camera_id] = {
                'recording': False,
                'motion_start': None,
                'last_motion': None,
                'motion_count': 0,
                'cooldown_until': None
            }
            
            # Create frame queue
            self.frame_queues[camera_id] = queue.Queue(maxsize=100)
            
            self.motion_detectors[camera_id] = motion_detector
            self.recorders[camera_id] = recorder
            
            self.logger.info(f"Camera {camera_id} initialized")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize camera {camera_id}: {e}")
            return False
    
    def process_camera_stream(self, camera_id: str, camera_config: Dict):
        """Process stream from a single camera"""
        rtsp_url = camera_config['rtsp_url']
        camera_name = camera_config.get('name', camera_id)
        
        self.logger.info(f"Starting camera stream: {camera_name} ({rtsp_url})")
        
        # Open video capture
        if rtsp_url.isdigit():
            cap = cv2.VideoCapture(int(rtsp_url))
        else:
            cap = cv2.VideoCapture(rtsp_url)
        
        if not cap.isOpened():
            self.logger.error(f"Failed to open camera: {camera_id}")
            return
        
        # Set buffer size to minimize latency
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        frame_count = 0
        fps_update_interval = 30
        
        try:
            while self.running:
                ret, frame = cap.read()
                if not ret:
                    self.logger.warning(f"Failed to grab frame from {camera_id}")
                    time.sleep(1)
                    continue
                
                frame_count += 1
                
                # Resize frame if needed
                target_res = self.config['recording']['resolution']
                if frame.shape[:2] != target_res[::-1]:
                    frame = cv2.resize(frame, target_res)
                
                # Add timestamp overlay
                if self.config['timestamp']['enabled']:
                    frame = self.video_processor.add_timestamp(frame)
                
                # Check motion in ROI
                motion_detected = self.motion_detectors[camera_id].detect(frame)
                
                # Update camera state
                self.update_camera_state(camera_id, motion_detected, frame)
                
                # Update FPS display periodically
                if frame_count % fps_update_interval == 0:
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    self.logger.debug(f"Camera {camera_id} FPS: {fps:.1f}")
                
                # Small delay to prevent CPU overload
                time.sleep(0.01)
                
        except Exception as e:
            self.logger.error(f"Error processing camera {camera_id}: {e}")
        finally:
            cap.release()
            self.logger.info(f"Camera stream stopped: {camera_id}")
    
    def update_camera_state(self, camera_id: str, motion_detected: bool, frame):
        """Update camera state based on motion detection"""
        state = self.camera_states[camera_id]
        now = time.time()
        recorder = self.recorders[camera_id]
        
        if motion_detected:
            state['motion_count'] += 1
            state['last_motion'] = now
            
            # Start recording if not already
            if not state['recording'] and state['motion_count'] >= self.config['cameras'][camera_id]['min_motion_frames']:
                self.start_recording(camera_id, frame)
                state['recording'] = True
                state['motion_start'] = now
                state['cooldown_until'] = None
                
                # Send Telegram notification
                if self.config['telegram']['send_snapshot']:
                    self.send_motion_alert(camera_id, frame)
            
            # If already recording, add frame
            elif state['recording']:
                recorder.add_frame(frame)
        
        else:
            # No motion detected
            if state['recording']:
                # Check if we should stop recording
                time_since_motion = now - (state['last_motion'] or now)
                min_recording_time = self.config['cameras'][camera_id]['min_recording_time']
                
                if time_since_motion > self.config['cameras'][camera_id]['cooldown_time']:
                    # Ensure minimum recording time
                    if now - state['motion_start'] >= min_recording_time:
                        self.stop_recording(camera_id)
                        state['recording'] = False
                        state['motion_count'] = 0
                    else:
                        # Still add frame during minimum recording time
                        recorder.add_frame(frame)
                else:
                    # Still in cooldown period, keep recording
                    recorder.add_frame(frame)
    
    def start_recording(self, camera_id: str, first_frame):
        """Start recording video"""
        try:
            camera_name = self.config['cameras'][camera_id]['name']
            self.recorders[camera_id].start_recording(first_frame)
            self.logger.info(f"Started recording for {camera_name}")
        except Exception as e:
            self.logger.error(f"Failed to start recording for {camera_id}: {e}")
    
    def stop_recording(self, camera_id: str):
        """Stop recording and process video"""
        try:
            video_path = self.recorders[camera_id].stop_recording()
            if video_path:
                camera_name = self.config['cameras'][camera_id]['name']
                self.logger.info(f"Recording saved: {video_path}")
                
                # Send to Telegram
                if self.config['telegram']['send_video']:
                    self.telegram_bot.send_video(video_path, f"Motion detected: {camera_name}")
                
                # Log recording
                self.log_recging(camera_id, video_path)
                
        except Exception as e:
            self.logger.error(f"Failed to stop recording for {camera_id}: {e}")
    
    def send_motion_alert(self, camera_id: str, frame):
        """Send motion alert with snapshot to Telegram"""
        try:
            camera_name = self.config['cameras'][camera_id]['name']
            temp_path = Path(self.config['system']['temp_dir']) / f"motion_{camera_id}_{int(time.time())}.jpg"
            
            # Save snapshot
            cv2.imwrite(str(temp_path), frame)
            
            # Send to Telegram
            self.telegram_bot.send_photo(
                temp_path,
                f"🚨 Motion detected: {camera_name}\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            # Cleanup
            temp_path.unlink(missing_ok=True)
            
        except Exception as e:
            self.logger.error(f"Failed to send motion alert: {e}")
    
    def log_recging(self, camera_id: str, video_path: str):
        """Log recording to database or file"""
        log_entry = {
            'camera_id': camera_id,
            'camera_name': self.config['cameras'][camera_id]['name'],
            'video_path': str(video_path),
            'timestamp': datetime.now().isoformat(),
            'duration': self.recorders[camera_id].get_last_duration()
        }
        
        log_file = Path("logs") / "recordings.jsonl"
        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def start(self):
        """Start the surveillance system"""
        self.running = True
        self.logger.info("Starting surveillance system...")
        
        # Initialize all cameras
        for camera_id, camera_config in self.config['cameras'].items():
            if self.initialize_camera(camera_id, camera_config):
                # Start camera processing in separate thread
                thread = threading.Thread(
                    target=self.process_camera_stream,
                    args=(camera_id, camera_config),
                    daemon=True
                )
                thread.start()
        
        self.logger.info("Surveillance system started")
        
        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """Stop the surveillance system"""
        self.logger.info("Stopping surveillance system...")
        self.running = False
        
        # Stop all recorders
        for camera_id, recorder in self.recorders.items():
            if recorder.is_recording():
                recorder.stop_recording()
        
        time.sleep(2)  # Allow threads to finish
        self.logger.info("Surveillance system stopped")

def signal_handler(signum, frame):
    print("\nReceived shutdown signal")
    sys.exit(0)

if __name__ == "__main__":
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and run system
    system = SurveillanceSystem()
    system.start()