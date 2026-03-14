import subprocess
import threading
import logging
import os
import time
from datetime import datetime
from typing import Optional

log = logging.getLogger("VIDEO_RECORDER")

class VideoRecorder:
    def __init__(
        self,
        rtsp_url: str,
        output_dir: str = "recordings",
        include_audio: bool = False
    ):
        self.rtsp_url = rtsp_url
        self.output_dir = output_dir
        self.include_audio = include_audio
        self.process: Optional[subprocess.Popen] = None
        self.recording_thread: Optional[threading.Thread] = None
        self.is_recording = False
        self.current_filename = None
        self.process_id = None

        os.makedirs(output_dir, exist_ok=True)
        log.info(f"VideoRecorder ინიციალიზებული RTSP: {rtsp_url}")

    def check_ffmpeg_available(self) -> bool:
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                log.info("FFmpeg ხელმისაწვდომია")
                return True
            return False
        except Exception as e:
            log.error(f"FFmpeg არ არის ხელმისაწვდომი: {e}")
            return False

    def start_recording(self, process_id: str) -> bool:
        if self.is_recording:
            log.warning("ჩაწერა უკვე მიმდინარეობს")
            return False

        if not self.check_ffmpeg_available():
            log.error("FFmpeg არ არის დაყენებული ან არ მუშაობს")
            return False

        self.process_id = process_id
        self.current_filename = f"{process_id}.mp4"
        output_path = os.path.join(self.output_dir, self.current_filename)

        ffmpeg_cmd = [
            "ffmpeg",
            "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            "-timeout", "20000000",
            "-fflags", "+genpts+discardcorrupt",
            "-use_wallclock_as_timestamps", "1",
            "-i", self.rtsp_url,
            "-c:v", "libx264",               # შენი მოთხოვნა — H.264
            "-preset", "veryfast",           # შენი მოთხოვნა
            "-crf", "23",                    # შენი მოთხოვნა
            "-pix_fmt", "yuv420p",           # შენი მოთხოვნა
            "-tag:v", "avc1",                # H.264-ისთვის სტანდარტული tag
            "-movflags", "+faststart",       # სწორი seeking-ისთვის
        ]

        if self.include_audio:
            ffmpeg_cmd.extend(["-c:a", "copy"])
        else:
            ffmpeg_cmd.append("-an")

        ffmpeg_cmd.extend(["-y", output_path])

        try:
            log.info(f"იწყება ჩაწერა → {self.current_filename}")
            log.debug(f"FFmpeg ბრძანება: {' '.join(ffmpeg_cmd)}")

            self.process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
            )

            self.is_recording = True
            self.recording_thread = threading.Thread(
                target=self._monitor_and_log,
                daemon=True
            )
            self.recording_thread.start()

            time.sleep(2.5)
            if self.process.poll() is not None:
                self._read_and_log_ffmpeg_output()
                log.error("FFmpeg ადრე გათიშა")
                self.is_recording = False
                return False

            log.info(f"ჩაწერა წარმატებით დაიწყო: {output_path}")
            return True

        except Exception as e:
            log.error(f"ჩაწერის დაწყების შეცდომა: {e}")
            self.is_recording = False
            return False

    def stop_recording(self) -> bool:
        if not self.is_recording or not self.process:
            return False

        log.info(f"ჩაწერის გაჩერება: {self.current_filename}")

        try:
            # Graceful stop
            if self.process.stdin:
                self.process.stdin.write('q\n')
                self.process.stdin.flush()
                time.sleep(2.0)

            self.process.terminate()
            try:
                stdout, stderr = self.process.communicate(timeout=15)
                if stderr:
                    log.warning("FFmpeg გაჩერებისას stderr:\n" + stderr.strip())
            except subprocess.TimeoutExpired:
                log.warning("FFmpeg არ გაითიშა gracefully → kill")
                self.process.kill()
                self.process.wait()

            self.process = None

            self.is_recording = False
            filename = self.current_filename
            self.current_filename = None
            self.process_id = None

            log.info(f"ჩაწერა წარმატებით შეწყდა: {filename}")
            return True

        except Exception as e:
            log.error(f"შეწყვეტის შეცდომა: {e}")
            return False

    def _monitor_and_log(self):
        while self.is_recording and self.process:
            return_code = self.process.poll()
            if return_code is not None:
                self._read_and_log_ffmpeg_output()
                if return_code != 0:
                    log.error(f"FFmpeg დასრულდა შეცდომით (კოდი: {return_code})")
                else:
                    log.info("FFmpeg ნორმალურად დასრულდა")
                self.is_recording = False
                break

            line = self.process.stderr.readline()
            if line:
                log.warning(f"FFmpeg: {line.strip()}")

            time.sleep(0.4)

    def _read_and_log_ffmpeg_output(self):
        if self.process:
            try:
                stderr = self.process.stderr.read()
                if stderr:
                    log.warning("FFmpeg ბოლო შეტყობინებები:\n" + stderr.strip())
            except:
                pass

    def get_status(self) -> dict:
        return {
            "is_recording": self.is_recording,
            "current_filename": self.current_filename,
            "process_id": self.process_id,
            "output_dir": self.output_dir,
            "file_size": self._get_current_file_size(),
        }

    def _get_current_file_size(self) -> str:
        if self.current_filename and self.is_recording:
            path = os.path.join(self.output_dir, self.current_filename)
            if os.path.exists(path):
                size_mb = os.path.getsize(path) / (1024 * 1024)
                return f"{size_mb:.2f} MB"
        return "0 MB"

    def get_recorded_files(self) -> list:
        try:
            files = []
            if os.path.exists(self.output_dir):
                for f in os.listdir(self.output_dir):
                    if f.endswith(".mp4"):
                        path = os.path.join(self.output_dir, f)
                        stat = os.stat(path)
                        files.append(
                            {
                                "filename": f,
                                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                                "created": datetime.fromtimestamp(
                                    stat.st_ctime
                                ).strftime("%Y-%m-%d %H:%M:%S"),
                            }
                        )
            return sorted(files, key=lambda x: x["created"], reverse=True)
        except Exception as e:
            log.error(f"ფაილების სიის შეცდომა: {e}")
            return []