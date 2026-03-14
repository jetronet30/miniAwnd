import cv2
from ultralytics import YOLO
import time
import os
import numpy as np
import logging
from datetime import datetime
from threading import Thread

from .image_saver import ImageSaver
from .wagon_counter import WagonCounter
from .camera_manager import CameraManager
from .hls_streamer import HLSStreamer
from .hls_server import start_hls_server
from .tcp_client import TCPClient
from .video_recorder import VideoRecorder

# ლოგირების კონფიგურაცია
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger("MAIN")

# HTTP სერვერის ლოგების გათიშვა
logging.getLogger("http.server").setLevel(logging.WARNING)
logging.getLogger("socketserver").setLevel(logging.WARNING)

# ────────────────────────────────────────────────

model = YOLO("best.pt")

MIN_WIDTH = 400
MIN_HEIGHT = 100
MIN_CONFIDENCE = 0.5

SAVE_DIR = "number_sectors"
os.makedirs(SAVE_DIR, exist_ok=True)


#---------HLS-------------------------------------

HLS_DIR = "hls"
os.makedirs(HLS_DIR, exist_ok=True)

#-------------------------------------------------

image_saver = ImageSaver(SAVE_DIR)
wagon_counter = WagonCounter()

# გლობალური ცვლადები HLS thread-სთვის
running = True
latest_display_frame = None
frame_lock = Thread()

def hls_streaming_thread():
    """HLS სტრიმინგის ცალკე thread"""
    global latest_display_frame, running, camera_width, camera_height
    
    log.info("🎥 HLS სტრიმინგის thread დაიწყო")
    
    while running:
        try:
            if latest_display_frame is not None:
                success = hls_streamer.write_frame(latest_display_frame)
                if not success:
                    log.warning("❌ HLS ფრეიმის გაგზავნა ჩავარდა")
            else:
                # თუ კადრი არ არის, გავაგზავნით შავ ეკრანს კამერის რეალური რეზოლუციით
                black_frame = np.zeros((camera_height, camera_width, 3), dtype=np.uint8)
                hls_streamer.write_frame(black_frame)
            
            time.sleep(0.066)  # ~15 FPS - შეესაბამება HLS სტრიმის FPS-ს
            
        except Exception as e:
            log.error(f"HLS thread შეცდომა: {e}")
            time.sleep(0.1)
    
    log.info("🛑 HLS სტრიმინგის thread დასრულდა")

# HLS სტრიმერის შექმნა - ოპტიმალური პარამეტრებით
hls_streamer = HLSStreamer(HLS_DIR, segment_duration=2, output_name="wagon_stream")

CAMERA_URL = "rtsp://admin:@192.168.1.12:554"
DETECTION_INTERVAL = 0.1
SAVE_EVERY_N_DETECTIONS = 1

# TCP კლიენტის კონფიგურაცია
TCP_IDENTIFIER = 0
TCP_HOST = "192.168.1.30"
TCP_PORT = 45000
REAL_WAGON_COUNT = 0

# გლობალური ცვლადი დეტექციის სტატუსისთვის
detection_enabled = False

# ვიდეო რეკორდერის შექმნა
video_recorder = VideoRecorder(CAMERA_URL, "recordings")

# ფანჯრის ფიქსური ზომები
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
WINDOW_NAME = "YOLO Camera + Detection"

# კამერის მენეჯერის შექმნა
camera_manager = CameraManager(CAMERA_URL)

# პირველ რიგში დავაკავშირდეთ კამერას და დავადგინოთ რეზოლუცია
print("🔗 კამერის დაკავშირება...")
if camera_manager.connect():
    # კამერის რეალური რეზოლუციის გამოყენება
    camera_width = camera_manager.width
    camera_height = camera_manager.height
    connection_screen = camera_manager.create_connection_screen()
else:
    print("❌ კამერის დაკავშირება ჩავარდა, გამოიყენება ნაგულისხმევი პარამეტრები")
    camera_width, camera_height = 1280, 720
    connection_screen = camera_manager.create_connection_screen()

# OpenCV ფანჯრის შექმნა ფიქსური ზომით
cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
cv2.resizeWindow(WINDOW_NAME, WINDOW_WIDTH, WINDOW_HEIGHT)
cv2.moveWindow(WINDOW_NAME, 100, 100)  # პოზიციის დაყენება

def on_detection_change(enabled: bool):
    global detection_enabled
    detection_enabled = enabled
    status = "ჩართული" if enabled else "გამორთული"
    log.info(f"🎯 დეტექციის სტატუსი შეიცვალა: {status}")
    
    # ვიდეოს ჩაწერის მართვა
    if enabled:
        # ჩავრთოთ ჩაწერა დეტექციის დაწყებისას
        process_id = tcp_client.get_process_id()
        if process_id and process_id != "არაა მიღებული":
            video_recorder.start_recording(process_id)
            log.info(f"🎥 ვიდეოს ჩაწერა დაიწყო ID-ით: {process_id}")
    else:
        # გავაჩეროთ ჩაწერა
        if video_recorder.get_status()["is_recording"]:
            video_recorder.stop_recording()
            log.info("🛑 ვიდეოს ჩაწერა გაჩერდა")
    
    # მხოლოდ დეტექციის დაწყებისას განვასუფთავთ
    if enabled:
        # ვაგონის ნომრის განულება
        wagon_counter.reset()
        log.info("🧹 ვაგონის ნომერი განულდა")
        
        # number_sectors ფაილების წაშლა
        try:
            import shutil
            import time
            
            # ჯერ დავხუროთ ყველა ფაილი დირექტორიაში
            if os.path.exists(SAVE_DIR):
                for filename in os.listdir(SAVE_DIR):
                    file_path = os.path.join(SAVE_DIR, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.chmod(file_path, 0o777)  # წვდომის უფლებების შეცვლა
                            os.unlink(file_path)  # ფაილის წაშლა
                    except Exception as file_error:
                        log.warning(f"ფაილის წაშლის შეცდომა {filename}: {file_error}")
                
                # მოვიცადოთ ცოტა და წავშალოთ დირექტორია
                time.sleep(0.1)
                shutil.rmtree(SAVE_DIR, ignore_errors=True)
                
                # ხელახლა შევქმნათ დირექტორია
                os.makedirs(SAVE_DIR, exist_ok=True)
                log.info(f"🗑️ {SAVE_DIR} დირექტორია გასუფთავდა")
            else:
                os.makedirs(SAVE_DIR, exist_ok=True)
                log.info(f"📁 {SAVE_DIR} დირექტორია შეიქმნა")
                
        except Exception as e:
            log.error(f"ფაილების წაშლის შეცდომა: {e}")
            # სცადოთ მაინც დირექტორიის შექმნა
            try:
                os.makedirs(SAVE_DIR, exist_ok=True)
            except:
                pass

def on_wagon_count_change(wagon_count: int):
    """ვაგონის რიცხვის შეცვლილება"""
    global REAL_WAGON_COUNT
    REAL_WAGON_COUNT = wagon_count
    log.info(f"🔢 REAL_WAGON_COUNT განახლდა: {wagon_count}")

tcp_client = TCPClient(TCP_HOST, TCP_PORT)
tcp_client.set_detection_callback(on_detection_change)
tcp_client.set_wagon_count_callback(on_wagon_count_change)
tcp_client.start()

print("იწყება. დააჭირე 'q'-ს გასაჩერებლად")
print(f"HLS სტრიმი ხელმისაწვდომია: {hls_streamer.get_playlist_url()}")

# HLS სტრიმის გაშვება - კამერის რეალური რეზოლუციით
# პირველ რიგში ვიღებთ კამერის რეზოლუციას
camera_width, camera_height = 1280, 720  # ნაგულისხმევი, შეიცვლება კამერის დაკავშირებისას

try:
    # კამერის რეზოლუციის ავტომატური დადგენა
    test_frame, _ = camera_manager.read_frame()
    if test_frame is not None:
        camera_height, camera_width = test_frame.shape[:2]
        log.info(f"🎥 კამერის რეზოლუცია: {camera_width}x{camera_height}")
    else:
        log.warning("⚠️ ვერ მოხერხდა კამერის რეზოლუციის დადგენა, გამოიყენება ნაგულისხმევი")
except Exception as e:
    log.warning(f"კამერის რეზოლუციის შეცდომა: {e}")

stream_started = hls_streamer.start_stream(width=camera_width, height=camera_height, fps=15)
print(f"HLS სტრიმის სტატუსი: {stream_started}")
if stream_started:
    print(f"🎥 HLS სტრიმი გაშვებულია: {camera_width}x{camera_height} @ 15fps")

# HLS thread-ის გაშვება
if stream_started:
    hls_thread = Thread(target=hls_streaming_thread, daemon=True)
    hls_thread.start()
    print("✅ HLS thread გაშვებულია")
    
    # HLS სერვერის გაშვება ცალკე thread-ში
    server_thread = start_hls_server()
    print("🌐 HLS სერვერის გაშვება დაიწყო")
    print("📺 სტრიმის ნახვა: http://localhost:8080/")
else:
    print("❌ HLS სტრიმი არ გაიშვა")
    hls_thread = None

# ────────────── მარტივი რიგითი ნუმერაცია ──────────────

last_annotated = None
last_detect_time = time.time()

save_counter = 0

def resize_frame_to_window(frame):
    """ფრეიმის ზომის შეცვლა ფანჯრის ფიქსური ზომისთვის"""
    try:
        # შევინარჩუნოთ ასპექტის პროპორცია უკეთესი ხარისხისთვის
        h, w = frame.shape[:2]
        aspect_ratio = w / h
        
        if aspect_ratio > WINDOW_WIDTH / WINDOW_HEIGHT:
            # ფართო ფრეიმი - შევზღუდოთ სიგანე
            new_w = WINDOW_WIDTH
            new_h = int(WINDOW_WIDTH / aspect_ratio)
        else:
            # მაღალი ფრეიმი - შევზღუდოთ სიმაღლე
            new_h = WINDOW_HEIGHT
            new_w = int(WINDOW_HEIGHT * aspect_ratio)
        
        # რეზიზირება და შავი ზოლების დამატება თუ სჭირდება
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        
        # შავი ფონზე ცენტრირება
        final_frame = np.zeros((WINDOW_HEIGHT, WINDOW_WIDTH, 3), dtype=np.uint8)
        y_offset = (WINDOW_HEIGHT - new_h) // 2
        x_offset = (WINDOW_WIDTH - new_w) // 2
        final_frame[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
        
        return final_frame
    except Exception as e:
        print(f"ფრეიმის რეზიზირების შეცდომა: {e}")
        return cv2.resize(frame, (WINDOW_WIDTH, WINDOW_HEIGHT))

while True:
    loop_start = time.time()
    
    # ვამოწმებთ კამერის სტატუსს
    if not camera_manager.get_status():
        if not camera_manager.reconnect():
            # ეკრანის ჩვენება დაკავშირების მცდელობისას
            cv2.imshow(WINDOW_NAME, resize_frame_to_window(connection_screen))
            key = cv2.waitKey(1)
            if key == ord('q'):
                break
            continue

    # ფრეიმის კითხვა
    frame, success = camera_manager.read_frame()
    if not success:
        # ეკრანის ჩვენება რეკონექტის მცდელობისას
        cv2.imshow(WINDOW_NAME, resize_frame_to_window(connection_screen))
        key = cv2.waitKey(1)
        if key == ord('q'):
            break
        continue

    current_time = time.time()

    if current_time - last_detect_time >= DETECTION_INTERVAL and detection_enabled:
        try:
            results = model(frame, conf=MIN_CONFIDENCE, verbose=False, imgsz=640)[0]
            annotated = frame.copy()

            current_detected = False

            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf)
                cls = int(box.cls)
                name = model.names[cls]

                w = x2 - x1
                h = y2 - y1

                cv2.putText(annotated, f"{name} {conf:.2f}", (x1 + 100, y1-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                cv2.putText(annotated, f"W:{w} H:{h}", (x1, y2+20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 0, 0), 2)
                if h > MIN_HEIGHT and w > MIN_WIDTH:
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 3)
                    
                    current_detected = True

                    # ვაგონის ნომრის მიღება WagonCounter-იდან
                    current_number = wagon_counter.update_detection(True)

                    # ახლა ვხატავთ და ვინახავთ უკვე სწორ ნომერს
                    cv2.putText(annotated, f"{current_number}", (x1 , y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)

                    save_counter += 1
                    if save_counter % SAVE_EVERY_N_DETECTIONS == 0:
                        # ფაილის სახელშიაც სწორი ნომერი
                        image_saver.save_crop(frame, x1, y1, x2, y2, f"{current_number}_{name}", conf)
                        print(f"შენახული (ყოველ {SAVE_EVERY_N_DETECTIONS}-ზე): {name} {conf:.2f}  → #{current_number}")

            # დეტექციის სტატუსის განახლება WagonCounter-ში
            wagon_counter.update_detection(current_detected)

            last_annotated = annotated
            last_detect_time = current_time

        except Exception as e:
            print(f"YOLO error: {e}")
            last_annotated = frame.copy()
    
    # თუ დეტექცია გამორთულია, უნდა განვაახლდეთ უბრალო ფრეიმი
    elif not detection_enabled and last_annotated is not None:
        # გავასუფთაოთ ძველი ანოტაციები, რომ ვიდეო არ გაყინულიყო
        last_annotated = None

    # ეკრანის არჩევა: თუ კამერა დაკავშირებულია - ნორმალური ეკრანი, თუ არა - connecting ეკრანი
    if camera_manager.get_status():
        display = last_annotated if last_annotated is not None else frame
        
        # დეტექციის სტატუსის ჩვენება ეკრანზე
        status_text = "DETECTION: ON" if detection_enabled else "DETECTION: OFF"
        status_color = (0, 255, 0) if detection_enabled else (0, 0, 255)
        cv2.putText(display, status_text, (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, status_color, 2)
        cv2.putText(display, f"Process ID: {tcp_client.get_process_id()}", (10, 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(display, f"Real Wagon Count: {REAL_WAGON_COUNT}", (10, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        # ვიდეოს ჩაწერის სტატუსის ჩვენება
        recording_status = video_recorder.get_status()
        if recording_status["is_recording"]:
            rec_text = f"REC: {recording_status['current_filename']}"
            rec_color = (0, 0, 255)  # წითელი ჩაწერისთვის
            cv2.putText(display, rec_text, (10, 120), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, rec_color, 2)
            # წითელი წრე ჩაწერის ინდიკატორად
            cv2.circle(display, (display.shape[1] - 30, 30), 8, rec_color, -1)
        else:
            rec_text = "REC: OFF"
            rec_color = (100, 100, 100)  # ნაცრისფერი გამორთულისთვის
            cv2.putText(display, rec_text, (10, 120), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, rec_color, 2)
        
        # ფრეიმის გადაცემა HLS thread-სთვის (არა პირდაპირ სტრიმში)
        latest_display_frame = display.copy()
    else:
        display = connection_screen
        latest_display_frame = display.copy()
        
    cv2.imshow(WINDOW_NAME, resize_frame_to_window(display))

    key = cv2.waitKey(1)
    if key == ord('q'):
        running = False  # HLS thread-ის გათიშვა
        break

    elapsed = time.time() - loop_start
    sleep_needed = max(0, 0.033 - elapsed)
    if sleep_needed > 0:
        time.sleep(sleep_needed)

camera_manager.release()
cv2.destroyAllWindows()

# HLS სტრიმის გაჩერება
hls_streamer.stop_stream()

# TCP კლიენტის გათიშვა
tcp_client.stop()

# ვიდეო რეკორდერის გათიშვა
if video_recorder.get_status()["is_recording"]:
    video_recorder.stop_recording()
    log.info("🛑 ვიდეოს ჩაწერა გაჩერდა პროგრამის დასრულებისას")

print("პროგრამა დასრულდა.")