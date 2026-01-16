import cv2
import threading
import queue
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

class VideoRecorder:
    def __init__(self, output_dir: str, camera_name: str, 
                 resolution=(1280, 720), fps=15, codec='mp4v'):
        self.output_dir = Path(output_dir)
        self.camera_name = camera_name
        self.resolution = resolution
        self.fps = fps
        self.codec = codec
        
        # Recording state
        self.is_recording = False
        self.video_writer = None
        self.frame_queue = queue.Queue(maxsize=100)
        self.recording_thread = None
        self.last_video_path = None
        self.start_time = None
        
        # Video writer parameters
        self.fourcc = cv2.VideoWriter_fourcc(*codec)
        
    def start_recording(self, first_frame):
        """Start recording video"""
        if self.is_recording:
            return
        
        self.is_recording = True
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.last_video_path = self.output_dir / f"{self.camera_name}_{timestamp}.mp4"
        
        # Initialize video writer
        self.video_writer = cv2.VideoWriter(
            str(self.last_video_path),
            self.fourcc,
            self.fps,
            (first_frame.shape[1], first_frame.shape[0])
        )
        
        if not self.video_writer.isOpened():
            raise Exception(f"Failed to open video writer for {self.last_video_path}")
        
        # Start recording thread
        self.recording_thread = threading.Thread(target=self._recording_loop)
        self.recording_thread.start()
        
        # Add first frame
        self.add_frame(first_frame)
        
        self.start_time = time.time()
        
    def add_frame(self, frame):
        """Add frame to recording queue"""
        if self.is_recording and not self.frame_queue.full():
            self.frame_queue.put(frame.copy())
    
    def _recording_loop(self):
        """Main recording loop"""
        try:
            while self.is_recording or not self.frame_queue.empty():
                try:
                    # Get frame with timeout
                    frame = self.frame_queue.get(timeout=1.0)
                    self.video_writer.write(frame)
                    self.frame_queue.task_done()
                except queue.Empty:
                    continue
                    
        except Exception as e:
            print(f"Recording error: {e}")
        finally:
            if self.video_writer:
                self.video_writer.release()
    
    def stop_recording(self) -> Optional[Path]:
        """Stop recording and return video path"""
        if not self.is_recording:
            return None
        
        self.is_recording = False
        
        # Wait for recording thread to finish
        if self.recording_thread:
            self.recording_thread.join(timeout=5.0)
        
        # Clear queue
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
                self.frame_queue.task_done()
            except queue.Empty:
                break
        
        return self.last_video_path
    
    def get_last_duration(self) -> float:
        """Get duration of last recording in seconds"""
        if self.start_time:
            return time.time() - self.start_time
        return 0.0
    
    def is_recording(self) -> bool:
        return self.is_recording