import cv2
import numpy as np
from typing import Tuple, Optional

class MotionDetector:
    def __init__(self, roi_percentage=[0, 0, 1, 1], threshold=500, min_motion_frames=10):
        """
        Initialize motion detector
        
        Args:
            roi_percentage: [x1, y1, x2, y2] as percentage of frame (0-1)
            threshold: Motion detection sensitivity
            min_motion_frames: Minimum consecutive frames with motion
        """
        self.roi_percentage = roi_percentage
        self.threshold = threshold
        self.min_motion_frames = min_motion_frames
        
        # Background subtractor
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500,
            varThreshold=16,
            detectShadows=False
        )
        
        # Motion tracking
        self.motion_frames = 0
        self.no_motion_frames = 0
        self.last_frame = None
        
        # Kernel for morphological operations
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    
    def get_roi_mask(self, frame_shape):
        """Create ROI mask based on percentage coordinates"""
        height, width = frame_shape[:2]
        x1 = int(self.roi_percentage[0] * width)
        y1 = int(self.roi_percentage[1] * height)
        x2 = int(self.roi_percentage[2] * width)
        y2 = int(self.roi_percentage[3] * height)
        
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[y1:y2, x1:x2] = 255
        
        return mask, (x1, y1, x2, y2)
    
    def detect(self, frame) -> bool:
        """
        Detect motion in the frame
        
        Returns:
            bool: True if motion detected, False otherwise
        """
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Apply Gaussian blur to reduce noise
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        
        # Get ROI mask
        roi_mask, roi_coords = self.get_roi_mask(frame.shape)
        
        # Apply background subtraction
        fg_mask = self.bg_subtractor.apply(gray)
        
        # Apply ROI mask
        fg_mask = cv2.bitwise_and(fg_mask, fg_mask, mask=roi_mask)
        
        # Threshold and clean up mask
        _, thresh = cv2.threshold(fg_mask, 25, 255, cv2.THRESH_BINARY)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, self.kernel)
        thresh = cv2.dilate(thresh, None, iterations=2)
        
        # Find contours
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        motion_detected = False
        
        for contour in contours:
            if cv2.contourArea(contour) < self.threshold:
                continue
            
            motion_detected = True
            
            # Draw bounding box for debugging (optional)
            (x, y, w, h) = cv2.boundingRect(contour)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        
        # Draw ROI rectangle
        x1, y1, x2, y2 = roi_coords
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
        
        # Update motion tracking
        if motion_detected:
            self.motion_frames += 1
            self.no_motion_frames = 0
        else:
            self.no_motion_frames += 1
            if self.no_motion_frames > 5:
                self.motion_frames = 0
        
        # Require consecutive motion frames to confirm detection
        return self.motion_frames >= self.min_motion_frames
    
    def reset(self):
        """Reset motion detection state"""
        self.motion_frames = 0
        self.no_motion_frames = 0