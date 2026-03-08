import socket
import threading
import logging
import time
import random
from typing import Optional, Callable

log = logging.getLogger("TCP_CLIENT")

class TCPClient:
    def __init__(self, host: str = "localhost", port: int = 9999):
        self.host = host
        self.port = port
        self.process_id = None
        self.socket: Optional[socket.socket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.detection_enabled = False
        self.on_detection_change: Optional[Callable[[bool], None]] = None

        # რეკონექტის პარამეტრები
        self.max_retries = 0          # 0 = უსასრულო
        self.base_delay = 1.0
        self.max_delay = 60.0

    def set_detection_callback(self, callback: Callable[[bool], None]):
        self.on_detection_change = callback
    
    def set_wagon_count_callback(self, callback):
        """ვაგონის რიცხვის callback-ის დაყენება"""
        self.wagon_count_callback = callback

    def start(self):
        if self.running:
            log.warning("TCP კლიენტი უკვე გაშვებულია")
            return

        self.running = True
        log.info(f"🚀 TCP კლიენტის გაშვება → {self.host}:{self.port}")

        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()
        log.info("🔌 ფონური ძაფი გაშვებულია")

    def stop(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.2)
        log.info("🛑 TCP კლიენტი გაჩერებულია")

    def _listen_loop(self):
        consecutive_failures = 0

        # საწყისი სერვერის ხელმისაწვდომობის ტესტი (არა კრიტიკული)
        self._check_server_once()

        while self.running:
            try:
                # ახალი სოკეტი ყოველ ჯერზე
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(6.0)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                log.info(f"🔗 ვცდილობთ დაკავშირებას {self.host}:{self.port} ...")
                self.socket.connect((self.host, self.port))

                log.info("✅ დაკავშირებულია")
                consecutive_failures = 0

                # მონაცემების მიღების ციკლი
                while self.running:
                    try:
                        data = self.socket.recv(4096).decode('utf-8', errors='replace').strip()
                        if not data:
                            # სერვერმა დაახურა კავშირი
                            raise ConnectionResetError("Empty response → server closed connection")
                        log.info(f"📨 მიღებული: {data}")
                        self._process_command(data)
                    except socket.timeout:
                        continue
                    except ConnectionResetError:
                        log.warning("🔌 სერვერმა გაწყვიტა კავშირი")
                        break
                    except Exception as e:
                        log.error(f"recv შეცდომა: {type(e).__name__} → {e}")
                        break

            except (ConnectionRefusedError, OSError) as e:
                consecutive_failures += 1
                msg = "Connection refused" if isinstance(e, ConnectionRefusedError) else str(e)
                log.warning(f"❌ კავშირი ვერ მოხერხდა ({consecutive_failures}×): {msg}")

            except Exception as e:
                consecutive_failures += 1
                log.error(f"მოულოდნელი შეცდომა კავშირისას: {type(e).__name__} → {e}")

            finally:
                if self.socket:
                    try:
                        self.socket.close()
                    except Exception:
                        pass
                    self.socket = None

            if not self.running:
                break

            # რეკონექტის დალოდება
            if self.max_retries > 0 and consecutive_failures > self.max_retries:
                log.error(f"❌ მაქსიმალური რეკონექტის რაოდენობა ამოიწურა ({self.max_retries})")
                self.running = False
                break

            delay = min(self.base_delay * (2 ** min(consecutive_failures, 10)), self.max_delay)
            jitter = random.uniform(0, 0.4 * delay)   # ±20% jitter
            total_delay = delay + jitter

            log.info(f"🔄 რეკონექტი {total_delay:.1f} წამში... (ჩავარდნები: {consecutive_failures})")
            time.sleep(total_delay)

    def _check_server_once(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            code = s.connect_ex((self.host, self.port))
            s.close()
            if code == 0:
                log.info(f"✅ სერვერი ჩანს ხელმისაწვდომად")
            else:
                log.warning(f"⚠️ სერვერი არ ჩანს (errno {code})")
        except Exception as e:
            log.debug(f"სერვერის საწყისი შემოწმება ვერ მოხერხდა: {e}")

    def _process_command(self, command: str):
        cmd = command.upper().strip()

        if cmd.startswith("ID="):
            rid = cmd[3:].strip()
            if rid:
                self.process_id = rid
                log.info(f"🆔 Process ID მიღებული: {rid}")
            return

        if cmd in ("START", "STOP"):
            if not self.process_id:
                log.warning(f"❌ {cmd} მიღებულია, მაგრამ ID ჯერ არ გვაქვს")
                return
            enabled = (cmd == "START")
            self._enable_detection(enabled)
            log.info(f"{'🎯' if enabled else '🛑'} დეტექცია {'ჩართული' if enabled else 'გამორთული'} (ID: {self.process_id})")
            return

        # START/ID=xxx, STOP/ID=xxx, STOP/id=xxx/w_c=5
        if cmd.startswith(("START/ID=", "START/id=", "STOP/ID=", "STOP/id=")):
            # პირველი დამუშავება START/ID=xxx ან STOP/ID=xxx
            prefix_len = 9 if cmd.startswith(("START/ID=", "START/id=")) else 8
            id_part = cmd[prefix_len:]  # ავიღოთ მხოლოდ ID-ს ნაწილი
            
            # შემოწმება /w_c=5 ან /W_C=5 პარამეტრისთვის
            if "/w_c=" in id_part or "/W_C=" in id_part:
                # გამოვიყოთ რომელისთვის დამთხვევა
                if "/W_C=" in id_part:
                    parts = id_part.split("/W_C=")
                else:
                    parts = id_part.split("/w_c=")
                
                if len(parts) >= 2:
                    received_id = parts[0].strip()
                    wagon_count = parts[1].strip()
                    
                    if not received_id or not wagon_count.isdigit():
                        log.warning("❌ არასწორი ფორმატი STOP/id=xxx/w_c=5")
                        return
                    
                    # ვაგონის რიცხვის განახლება
                    if hasattr(self, 'wagon_count_callback') and self.wagon_count_callback:
                        try:
                            self.wagon_count_callback(int(wagon_count))
                            log.info(f"🔢 ვაგონის რიცხვი განახლდა: {wagon_count}")
                        except Exception as e:
                            log.error(f"ვაგონის რიცხვის განახლების შეცდომა: {e}")
                    
                    # დეტექციის გამორთვა (STOP ბრძანება)
                    if cmd.startswith("STOP"):
                        old_id = self.process_id
                        if not self.process_id:
                            self.process_id = received_id
                            log.info(f"🆔 ავტომატურად დაყენდა Process ID: {received_id}")
                        
                        self._enable_detection(False)
                        log.info(f"🛑 დეტექცია გამორთული (ID: {self.process_id})")
                    return
            
            # ჩვეულებიანი START/ID=xxx და STOP/ID=xxx ბრძანებები
            received_id = id_part.strip()
            
            if not received_id:
                log.warning("❌ არასწორი ფორმატი START/ID=xxx ან STOP/ID=xxx")
                return

            enabled = cmd.startswith("START")

            old_id = self.process_id
            if not self.process_id:
                self.process_id = received_id
                log.info(f"🆔 ავტომატურად დაყენდა Process ID: {received_id}")

            if self.process_id == received_id:
                self._enable_detection(enabled)
                log.info(f"{'🎯' if enabled else '🛑'} დეტექცია {'ჩართული' if enabled else 'გამორთული'} (ID: {self.process_id})")
            else:
                log.info(f"🔄 ID შეიცვალა: {old_id or 'არ არის დაყენებული'} → {received_id}")
                self.process_id = received_id
                self._enable_detection(enabled)
                log.info(f"{'🎯' if enabled else '🛑'} დეტექცია {'ჩართული' if enabled else 'გამორთული'} (ახალი ID)")
            return

        log.warning(f"⚠️ უცნობი ბრძანება: {command}")

    def _enable_detection(self, enabled: bool):
        if self.detection_enabled == enabled:
            return
        self.detection_enabled = enabled
        status = "ჩართული" if enabled else "გამორთული"
        log.info(f"🎯 დეტექციის სტატუსი: {status}")
        if self.on_detection_change:
            try:
                self.on_detection_change(enabled)
            except Exception as e:
                log.error(f"Callback-ში შეცდომა: {e}")

    def get_process_id(self) -> str:
        return self.process_id or "არაა მიღებული"

    def is_detection_enabled(self) -> bool:
        return self.detection_enabled