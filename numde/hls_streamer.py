import cv2
import subprocess
import os
import time
import numpy as np
import glob
import logging
from threading import Thread

log = logging.getLogger("HLS_STREAMER")

class HLSStreamer:
    """HLS სტრიმინგის კლასი - ოპტიმიზირებული ვერსია"""
    
    def __init__(self, stream_dir="hls", segment_duration=2, output_name="stream"):
        self.stream_dir = stream_dir
        self.segment_duration = segment_duration
        self.output_name = output_name
        self.process = None
        self.is_streaming = False
        self.max_segments = 5  # მაქსიმუმ სეგმენტების რაოდენობა
        
        # HLS ფოლდერის შექმნა
        os.makedirs(self.stream_dir, exist_ok=True)
        
        # ფაილის გზები
        self.playlist_path = os.path.join(self.stream_dir, f"{self.output_name}.m3u8")
        self.segment_pattern = os.path.join(self.stream_dir, f"{self.output_name}_%Y%m%d_%H%M%S.ts")
        
        log.info(f"HLS სტრიმერი შექმნილი: {self.playlist_path}")
        log.info(f"მაქსიმუმ სეგმენტები: {self.max_segments}")
        
    def cleanup_old_segments(self):
        """ძველი სეგმენტების წაშლა - ინახავს მხოლოდ უახლესს"""
        try:
            # ვიპოვოთ ყველა .ts ფაილი
            ts_files = glob.glob(os.path.join(self.stream_dir, f"{self.output_name}_*.ts"))
            
            # დავლაგოთ შექმნის დროის მიხედვით
            ts_files.sort(key=os.path.getmtime, reverse=True)
            
            # თუ ფაილების რაოდენობა მეტია მაქსიმუმზე, წავშალოთ ძველები
            if len(ts_files) > self.max_segments:
                for old_file in ts_files[self.max_segments:]:
                    try:
                        os.remove(old_file)
                        log.debug(f"წაიშალა ძველი სეგმენტი: {old_file}")
                    except Exception as e:
                        log.warning(f"სეგმენტის წაშლის შეცდომა: {e}")
                        
        except Exception as e:
            log.error(f"ძველი სეგმენტების გასუფთავების შეცდომა: {e}")
        
    def start_stream(self, width=1280, height=720, fps=25):
        """იწყებს HLS სტრიმინგს - ოპტიმალური პარამეტრებით"""
        if self.is_streaming:
            log.warning("სტრიმი უკვე გაშვებულია")
            return False
            
        try:
            # FFmpeg ბრძანება - ციმციმის ასარიდაგან პარამეტრებით
            command = [
                'ffmpeg',
                '-loglevel', 'error',
                '-y',  # არსებული ფაილების გადაწერა
                '-re',  # real-time რეჟიმი
                '-fflags', 'nobuffer+genpts+discardcorrupt',
                '-flags', 'low_delay',
                '-thread_queue_size', '512',
                '-f', 'rawvideo',
                '-pix_fmt', 'yuv420p',  # YUV420P ფორმატი
                '-s', f'{width}x{height}',
                '-r', str(fps),
                '-i', '-',  # stdin შემოსვლა
                '-c:v', 'libx264',
                '-preset', 'ultrafast',  # ultrafast ციმციმისთვის
                '-tune', 'zerolatency',
                '-profile:v', 'baseline',  # baseline კომპატიბილურობისთვის
                '-level', '3.1',
                '-pix_fmt', 'yuv420p',
                '-bf', '0',  # B-frames გამორთულია
                '-g', str(fps * 2),  # 2 წამიანი GOP
                '-keyint_min', str(fps),
                '-sc_threshold', '0',
                '-b:v', '2500k',  # უფრო დაბალი bitrate
                '-maxrate', '2500k',
                '-bufsize', '5000k',
                '-x264opts', 'no-scenecut:me=dia:subme=1',
                '-threads', '2',
                '-f', 'hls',
                '-hls_time', str(self.segment_duration),
                '-hls_list_size', '3',  # უფრო მცირე ლისტი
                '-hls_flags', 'append_list+program_date_time+delete_segments',
                '-hls_delete_threshold', '1',
                '-hls_segment_type', 'mpegts',
                '-strftime', '1',
                '-hls_segment_filename', os.path.join(self.stream_dir, f"{self.output_name}_%Y%m%d_%H%M%S.ts"),
                self.playlist_path
            ]
            
            log.info(f"FFmpeg ბრძანება: {' '.join(command)}")
            
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # stderr კითხვის თრედი
            Thread(target=self._read_stderr, daemon=True).start()
            
            self.is_streaming = True
            log.info(f"✅ HLS სტრიმინგი დაიწყო: {self.playlist_path}")
            log.info(f"⚡ პარამეტრები: {width}x{height} @ {fps}fps, {self.segment_duration}წმ სეგმენტები")
            return True
            
        except Exception as e:
            log.error(f"❌ HLS სტრიმინგის გაშვების შეცდომა: {e}")
            return False
    
    def _read_stderr(self):
        """FFmpeg stderr-ის კითხვა ლოგირებისთვის"""
        try:
            while self.process and self.process.poll() is None:
                line = self.process.stderr.readline()
                if line:
                    log.info(f"FFmpeg: {line.decode('utf-8', errors='ignore').strip()}")
        except Exception as e:
            log.error(f"stderr კითხვის შეცდომა: {e}")
    
    def write_frame(self, frame):
        """წერს ფრეიმს სტრიმში - BGR → YUV420P კონვერტაციით"""
        if not self.is_streaming or self.process is None:
            return False
            
        try:
            if frame is not None:
                # BGR → YUV420P კონვერტაცია (სწორი მეთოდი)
                # ჯერ შევამოწმოთ ფრეიმის ზომები
                height, width = frame.shape[:2]
                
                # დავადგინოთ სწორი YUV420P ზომა (უნდა იყოს 2-ის ჯერადი)
                yuv_height = height - (height % 2)
                yuv_width = width - (width % 2)
                
                # ფრეიმის ზომის კორექტირება თუ საჭიროა
                if yuv_height != height or yuv_width != width:
                    frame = cv2.resize(frame, (yuv_width, yuv_height))
                
                # BGR → YUV420P კონვერტაცია
                yuv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
                self.process.stdin.write(yuv_frame.tobytes())
                self.process.stdin.flush()
                
                # ყოველ 10 ფრეიმზე ერთხელ გავასუფთავოთ ძველი სეგმენტები
                if hasattr(self, '_frame_count'):
                    self._frame_count += 1
                else:
                    self._frame_count = 1
                    
                if self._frame_count % 10 == 0:
                    self.cleanup_old_segments()
                    
            return True
        except BrokenPipeError:
            log.error("❌ HLS pipe გაწყდა - FFmpeg შეცდომა")
            self.stop_stream()
            return False
        except Exception as e:
            log.error(f"❌ ფრეიმის ჩაწერის შეცდომა: {e}")
            self.stop_stream()
            return False
    
    def stop_stream(self):
        """წყვეტს სტრიმინგს"""
        if self.process is not None:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                try:
                    self.process.kill()
                except:
                    pass
            finally:
                self.process = None
                
        self.is_streaming = False
        log.info("🛑 HLS სტრიმინგი გაჩერებულია")
    
    def get_playlist_url(self):
        """აბრუნებს playlist URL-ს"""
        return self.playlist_path
    
    def get_status(self):
        """აბრუნებს სტრიმის სტატუსს"""
        return self.is_streaming
    
    def __del__(self):
        """დესტრუქტორი"""
        self.stop_stream()
