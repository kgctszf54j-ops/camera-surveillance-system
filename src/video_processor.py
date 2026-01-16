import cv2
import numpy as np
from datetime import datetime
from typing import Tuple

class VideoProcessor:
    def __init__(self, timestamp_config: dict):
        self.config = timestamp_config
        self.setup_position()
    
    def setup_position(self):
        """Setup timestamp position based on config"""
        position = self.config.get('position', 'bottom-right')
        
        if position == 'top-left':
            self.position = (10, 30)
            self.anchor = cv2.FONT_HERSHEY_SIMPLEX
        elif position == 'top-right':
            self.position = (-10, 30)
            self.anchor = cv2.FONT_HERSHEY_SIMPLEX
            self.right_aligned = True
        elif position == 'bottom-left':
            self.position = (10, -10)
            self.anchor = cv2.FONT_HERSHEY_SIMPLEX
        elif position == 'bottom-right':
            self.position = (-10, -10)
            self.anchor = cv2.FONT_HERSHEY_SIMPLEX
            self.right_aligned = True
        else:
            self.position = (10, 30)
            self.anchor = cv2.FONT_HERSHEY_SIMPLEX
    
    def add_timestamp(self, frame):
        """Add timestamp overlay to frame"""
        if not self.config.get('enabled', True):
            return frame
        
        # Get current timestamp
        timestamp = datetime.now().strftime(self.config.get('format', '%Y-%m-%d %H:%M:%S'))
        
        # Get text size for right alignment
        if hasattr(self, 'right_aligned') and self.right_aligned:
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = self.config.get('font_scale', 0.7)
            thickness = self.config.get('thickness', 2)
            
            text_size = cv2.getTextSize(timestamp, font, font_scale, thickness)[0]
            position = (frame.shape[1] - text_size[0] + self.position[0], 
                       frame.shape[1] - self.position[1])
        else:
            position = self.position
        
        # Add text to frame
        cv2.putText(
            frame,
            timestamp,
            position,
            cv2.FONT_HERSHEY_SIMPLEX,
            self.config.get('font_scale', 0.7),
            self.config.get('color', (255, 255, 255)),
            self.config.get('thickness', 2),
            cv2.LINE_AA
        )
        
        return frame
    
    def draw_roi(self, frame, roi_percentage, color=(0, 0, 255), thickness=2):
        """Draw ROI rectangle on frame"""
        height, width = frame.shape[:2]
        x1 = int(roi_percentage[0] * width)
        y1 = int(roi_percentage[1] * height)
        x2 = int(roi_percentage[2] * width)
        y2 = int(roi_percentage[3] * height)
        
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        
        # Add label
        cv2.putText(
            frame,
            "ROI",
            (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA
        )
        
        return frame