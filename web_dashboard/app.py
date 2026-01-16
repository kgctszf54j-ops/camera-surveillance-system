from flask import Flask, render_template, send_file, jsonify, request, send_from_directory
from flask_socketio import SocketIO
import os
from pathlib import Path
from datetime import datetime, timedelta
import json
import subprocess
import threading
from typing import List, Dict
import cv2
import base64

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
RECORDINGS_DIR = Path("../recordings")
CONFIG_FILE = Path("../src/config.yaml")
LOGS_DIR = Path("../logs")

class VideoDashboard:
    def __init__(self):
        self.recordings_cache = {}
        self.cache_timeout = 300  # 5 minutes
        self.last_cache_update = 0
    
    def get_recordings(self, date_filter=None, camera_filter=None) -> List[Dict]:
        """Get list of recordings with metadata"""
        current_time = datetime.now().timestamp()
        
        # Use cache if recent
        if current_time - self.last_cache_update < self.cache_timeout:
            cache_key = f"{date_filter}_{camera_filter}"
            if cache_key in self.recordings_cache:
                return self.recordings_cache[cache_key]
        
        recordings = []
        
        for video_file in RECORDINGS_DIR.glob("*.mp4"):
            try:
                # Get file metadata
                stat = video_file.stat()
                created = datetime.fromtimestamp(stat.st_ctime)
                
                # Parse filename for camera name
                filename = video_file.stem
                if '_' in filename:
                    camera_name = filename.split('_')[0]
                else:
                    camera_name = "Unknown"
                
                # Apply filters
                if date_filter and created.date() != date_filter:
                    continue
                
                if camera_filter and camera_filter != camera_name:
                    continue
                
                # Get video duration using OpenCV
                duration = self.get_video_duration(video_file)
                
                recording = {
                    'filename': video_file.name,
                    'path': str(video_file),
                    'camera': camera_name,
                    'created': created.isoformat(),
                    'size': stat.st_size,
                    'duration': duration,
                    'thumbnail': self.generate_thumbnail(video_file)
                }
                
                recordings.append(recording)
                
            except Exception as e:
                print(f"Error processing {video_file}: {e}")
        
        # Sort by creation time (newest first)
        recordings.sort(key=lambda x: x['created'], reverse=True)
        
        # Update cache
        cache_key = f"{date_filter}_{camera_filter}"
        self.recordings_cache[cache_key] = recordings
        self.last_cache_update = current_time
        
        return recordings
    
    def get_video_duration(self, video_path: Path) -> float:
        """Get duration of video file"""
        try:
            cap = cv2.VideoCapture(str(video_path))
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = frame_count / fps if fps > 0 else 0
            cap.release()
            return round(duration, 2)
        except:
            return 0
    
    def generate_thumbnail(self, video_path: Path) -> str:
        """Generate base64 thumbnail from video"""
        try:
            cap = cv2.VideoCapture(str(video_path))
            
            # Get frame at 10% of video
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_pos = int(total_frames * 0.1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            
            ret, frame = cap.read()
            cap.release()
            
            if ret:
                # Resize thumbnail
                frame = cv2.resize(frame, (320, 180))
                
                # Encode as JPEG
                _, buffer = cv2.imencode('.jpg', frame)
                thumbnail_base64 = base64.b64encode(buffer).decode('utf-8')
                
                return f"data:image/jpeg;base64,{thumbnail_base64}"
        except:
            pass
        
        return ""
    
    def get_system_stats(self) -> Dict:
        """Get system statistics"""
        total_size = sum(f.stat().st_size for f in RECORDINGS_DIR.glob('*') if f.is_file())
        file_count = len(list(RECORDINGS_DIR.glob('*.mp4')))
        
        # Get disk usage
        total, used, free = shutil.disk_usage(RECORDINGS_DIR)
        
        return {
            'total_recordings': file_count,
            'total_size_gb': round(total_size / (1024**3), 2),
            'disk_usage': {
                'total_gb': round(total / (1024**3), 2),
                'used_gb': round(used / (1024**3), 2),
                'free_gb': round(free / (1024**3), 2),
                'percent_used': round((used / total) * 100, 1)
            },
            'last_update': datetime.now().isoformat()
        }

dashboard = VideoDashboard()

@app.route('/api/video-info/<filename>')
def get_video_info(filename):
    """Get detailed video information"""
    video_path = RECORDINGS_DIR / filename
    
    if not video_path.exists():
        return jsonify({'error': 'File not found'}), 404
    
    try:
        # Get basic file info
        stat = video_path.stat()
        
        # Get video metadata using OpenCV
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = frame_count / fps if fps > 0 else 0
        cap.release()
        
        # Parse filename for camera name
        if '_' in filename:
            camera_name = filename.split('_')[0]
        else:
            camera_name = "Unknown"
        
        # Try to load motion events from log
        motion_events = 0
        motion_log = LOGS_DIR / "recordings.jsonl"
        if motion_log.exists():
            with open(motion_log, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get('video_path', '').endswith(filename):
                            motion_events = data.get('motion_count', 0)
                            break
                    except:
                        pass
        
        return jsonify({
            'filename': filename,
            'camera': camera_name,
            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'size': stat.st_size,
            'duration': duration,
            'resolution': f"{width}x{height}",
            'framerate': round(fps, 2),
            'frame_count': frame_count,
            'motion_events': motion_events,
            'codec': 'H.264'  # Would need proper detection
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/motion-events/<filename>')
def get_motion_events(filename):
    """Get motion events for a video"""
    # In a real system, this would come from a database
    # For now, generate sample events
    try:
        video_path = RECORDINGS_DIR / filename
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0
        cap.release()
        
        # Generate sample motion events (every 30 seconds)
        events = []
        for i in range(int(duration // 30)):
            timestamp = i * 30 + 5  # Start at 5 seconds
            if timestamp < duration:
                events.append({
                    'timestamp': timestamp,
                    'duration': 10,
                    'intensity': 0.7 + (i * 0.05)
                })
        
        return jsonify(events)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/snapshots/<filename>')
def get_snapshots(filename):
    """Get snapshots for a video"""
    # In a real system, this would come from a database
    # For now, generate sample snapshots
    snapshots = []
    
    try:
        video_path = RECORDINGS_DIR / filename
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Generate snapshots at 25%, 50%, 75% of video
        for percentage in [0.25, 0.5, 0.75]:
            frame_pos = int(frame_count * percentage)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            
            if ret:
                # Resize for thumbnail
                frame = cv2.resize(frame, (320, 180))
                
                # Convert to base64
                _, buffer = cv2.imencode('.jpg', frame)
                thumbnail_base64 = base64.b64encode(buffer).decode('utf-8')
                
                snapshots.append({
                    'timestamp': (frame_pos / fps) if fps > 0 else 0,
                    'thumbnail': f"data:image/jpeg;base64,{thumbnail_base64}",
                    'frame': frame_pos
                })
        
        cap.release()
        return jsonify(snapshots)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/save-snapshot', methods=['POST'])
def save_snapshot():
    """Save a snapshot from the player"""
    try:
        data = request.json
        filename = data.get('video')
        snapshot_data = data.get('snapshot')
        timestamp = data.get('timestamp')
        
        # Save the snapshot to disk
        # (In production, you'd want to save properly, not just in memory)
        
        return jsonify({
            'success': True,
            'message': 'Snapshot saved',
            'timestamp': timestamp
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/create-clip', methods=['POST'])
def create_clip():
    """Create a clip from a video"""
    try:
        data = request.json
        filename = data.get('video')
        start_time = data.get('start')
        end_time = data.get('end')
        
        video_path = RECORDINGS_DIR / filename
        
        if not video_path.exists():
            return jsonify({'error': 'File not found'}), 404
        
        # Generate output filename
        clip_filename = f"clip_{int(time.time())}_{filename}"
        clip_path = RECORDINGS_DIR / clip_filename
        
        # Use ffmpeg to create clip
        import subprocess
        cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-ss', str(start_time),
            '-to', str(end_time),
            '-c', 'copy',
            str(clip_path)
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        return jsonify({
            'success': True,
            'filename': clip_filename,
            'path': str(clip_path)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Update the main route to support player.html
@app.route('/player')
def player():
    """Render the video player page"""
    return render_template('player.html')


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/api/recordings')
def api_recordings():
    """API endpoint to get recordings"""
    date_filter = request.args.get('date')
    camera_filter = request.args.get('camera')
    
    if date_filter:
        date_filter = datetime.strptime(date_filter, '%Y-%m-%d').date()
    
    recordings = dashboard.get_recordings(date_filter, camera_filter)
    return jsonify(recordings)

@app.route('/api/play/<filename>')
def play_video(filename):
    """Stream video file"""
    video_path = RECORDINGS_DIR / filename
    
    if not video_path.exists():
        return "File not found", 404
    
    # Use Flask's send_file for streaming
    return send_file(
        video_path,
        mimetype='video/mp4',
        conditional=True,
        as_attachment=False
    )

@app.route('/api/download/<filename>')
def download_video(filename):
    """Download video file"""
    video_path = RECORDINGS_DIR / filename
    
    if not video_path.exists():
        return "File not found", 404
    
    return send_file(
        video_path,
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/delete/<filename>', methods=['DELETE'])
def delete_video(filename):
    """Delete recording"""
    video_path = RECORDINGS_DIR / filename
    
    if not video_path.exists():
        return jsonify({'error': 'File not found'}), 404
    
    try:
        video_path.unlink()
        # Clear cache
        dashboard.recordings_cache.clear()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def api_stats():
    """Get system statistics"""
    stats = dashboard.get_system_stats()
    return jsonify(stats)

@app.route('/api/cameras')
def api_cameras():
    """Get list of cameras from config"""
    try:
        import yaml
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f)
        
        cameras = []
        for cam_id, cam_config in config.get('cameras', {}).items():
            cameras.append({
                'id': cam_id,
                'name': cam_config.get('name', cam_id),
                'status': 'online'  # This would need actual status checking
            })
        
        return jsonify(cameras)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/live/<camera_id>')
def live_stream(camera_id):
    """Proxy for live stream (simplified)"""
    # In production, this would stream from the camera
    # For now, return latest recording
    recordings = dashboard.get_recordings(camera_filter=camera_id)
    if recordings:
        return jsonify({'url': f'/api/play/{recordings[0]["filename"]}'})
    return jsonify({'error': 'No recordings'}), 404

@app.route('/api/search')
def search_recordings():
    """Search recordings by date/time range"""
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    try:
        start_dt = datetime.fromisoformat(start_date) if start_date else None
        end_dt = datetime.fromisoformat(end_date) if end_date else None
        
        all_recordings = dashboard.get_recordings()
        filtered = []
        
        for rec in all_recordings:
            created = datetime.fromisoformat(rec['created'])
            
            if start_dt and created < start_dt:
                continue
            if end_dt and created > end_dt:
                continue
            
            filtered.append(rec)
        
        return jsonify(filtered)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@socketio.on('connect')
def handle_connect():
    print('Client connected')
    socketio.emit('status', {'message': 'Connected to dashboard'})

@socketio.on('request_update')
def handle_update():
    """Handle real-time updates"""
    stats = dashboard.get_system_stats()
    socketio.emit('stats_update', stats)

if __name__ == '__main__':
    # Ensure recordings directory exists
    RECORDINGS_DIR.mkdir(exist_ok=True)
    
    print(f"Dashboard starting on http://localhost:5000")
    print(f"Recordings directory: {RECORDINGS_DIR}")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)