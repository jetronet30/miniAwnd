import socket
import threading
import logging
import time
import re
import random
from typing import Optional, Callable

log = logging.getLogger("TCP_CLIENT")


class TCPClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 45000, identifier: int = 2):
        self.host = host
        self.port = port
        self.identifier = identifier
        self.process_id: Optional[str] = None
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.detection_enabled = False
        self.on_detection_change: Optional[Callable[[bool], None]] = None
        self.on_wagon_count_change: Optional[Callable[[int], None]] = None

        # რეკონექტის პარამეტრები
        self.max_retries = 0          # 0 = უსასრულო
        self.base_delay = 1.5
        self.max_delay = 45.0

    def set_detection_callback(self, callback: Callable[[bool], None]):
        self.on_detection_change = callback

    def set_wagon_count_callback(self, callback: Callable[[int], None]):
        self.on_wagon_count_change = callback

    def start(self):
        if self.running:
            log.warning("TCP კლიენტი უკვე გაშვებულია")
            return

        self.running = True
        log.info(f"TCP client starting → {self.host}:{self.port}  (identifier: {self.identifier})")

        self.thread = threading.Thread(target=self._connection_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        log.info("TCP client stopped")

    def _connection_loop(self):
        consecutive_failures = 0

        while self.running:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(5.0)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                log.info(f"Connecting to {self.host}:{self.port} ...")
                self.socket.connect((self.host, self.port))
                log.info("Connected successfully")
                consecutive_failures = 0

                while self.running:
                    try:
                        raw = self.socket.recv(4096).decode('utf-8', errors='replace').strip()
                        if not raw:
                            raise ConnectionResetError("Server closed connection")

                        for line in raw.splitlines():
                            line = line.strip()
                            if line:
                                log.info(f"← {line}")
                                self._process_message(line)

                    except socket.timeout:
                        continue
                    except ConnectionResetError:
                        log.warning("Connection reset by peer")
                        break
                    except Exception as e:
                        log.error(f"Receive error: {type(e).__name__} → {e}")
                        break

            except Exception as e:
                consecutive_failures += 1
                log.warning(f"Connection failed ({consecutive_failures}x): {type(e).__name__} → {e}")

            finally:
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None

            if not self.running:
                break

            # exponential backoff + jitter
            delay = min(self.base_delay * (2 ** min(consecutive_failures, 8)), self.max_delay)
            jitter = random.uniform(-0.3 * delay, 0.3 * delay)
            total_delay = max(0.3, delay + jitter)

            log.info(f"Reconnect in {total_delay:.1f}s ...")
            time.sleep(total_delay)

    def _process_message(self, msg: str):
        """ძირითადი პარსერი – case-insensitive + მოქნილი ფორმატი"""
        original = msg
        msg = msg.upper().strip()

        # 1. მარტივი ID=xxx
        if msg.startswith("ID="):
            pid = original[3:].strip()
            if pid:
                self.process_id = pid
                log.info(f"Process ID set: {pid}")
            return

        # ====================== START / STOP ======================
        pattern = r'^(\d+)_(START|STOP)(?:/ID=([^/]+))?(?:/(?:W_C|w_c)=(\d+))?$'
        match = re.match(pattern, msg, re.IGNORECASE)

        if match:
            target_id_str, action, received_id, wagon_count_str = match.groups()

            try:
                target_id = int(target_id_str)
            except:
                log.warning(f"Invalid identifier prefix: {target_id_str}")
                return

            if target_id != self.identifier:
                return

            enabled = (action == "START")

            # ID განახლება (თუ მოცემულია)
            if received_id:
                received_id = received_id.strip()
                if received_id:
                    old_id = self.process_id
                    self.process_id = received_id
                    if old_id and old_id != received_id:
                        log.info(f"Process ID changed: {old_id} → {received_id}")

            # wagon count განახლება STOP-ის დროს
            if wagon_count_str and action == "STOP":
                try:
                    wc = int(wagon_count_str)
                    if self.on_wagon_count_change:
                        self.on_wagon_count_change(wc)
                    log.info(f"Real wagon count updated via TCP: {wc}")
                except ValueError:
                    log.warning(f"Invalid wagon count: {wagon_count_str}")

            self._set_detection(enabled)

            log.info(f"[{self.identifier}] Detection {'ENABLED' if enabled else 'DISABLED'}"
                     f"  (ID: {self.process_id or '?'})")
            return

        # ====================== ABORT ======================
        # მხოლოდ მარტივი ფორმატი: 0_ABORT
        abort_pattern = r'^(\d+)_ABORT(?:/ID=([^/]+))?$'
        abort_match = re.match(abort_pattern, msg, re.IGNORECASE)

        if abort_match:
            target_id_str = abort_match.group(1)
            try:
                target_id = int(target_id_str)
            except:
                return

            if target_id != self.identifier:
                return

            # ABORT ზუსტად იგივეს აკეთებს რაც STOP
            self._set_detection(False)
            
            log.info(f"[{self.identifier}] Detection ABORTED by server command")
            return

        # უცნობი ბრძანება
        log.warning(f"Unknown command format: {original}")

    def _set_detection(self, enabled: bool):
        if self.detection_enabled == enabled:
            return

        self.detection_enabled = enabled
        log.info(f"Detection → {'ON' if enabled else 'OFF'}")

        if self.on_detection_change:
            try:
                self.on_detection_change(enabled)
            except Exception as e:
                log.error(f"Error in detection callback: {e}")

    def get_process_id(self) -> str:
        return self.process_id if self.process_id else "არაა მიღებული"

    def is_detection_enabled(self) -> bool:
        return self.detection_enabled

    def send_results_to_server(self, results_data: dict):
        """გზავნის OCR შედეგებს სერვერზე"""
        if not self.socket or not self.process_id:
            log.warning("Cannot send results - no connection or process ID")
            return False

        try:
            import json
            results_json = json.dumps(results_data, ensure_ascii=False)
            message = f"ID={self.process_id}|{results_json}"
            
            self.socket.send(message.encode('utf-8'))
            log.info(f"Results sent for ID {self.process_id}")
            return True
            
        except Exception as e:
            log.error(f"Failed to send results: {e}")
            return False