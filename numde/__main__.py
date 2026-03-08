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

# ლოგირების კონფიგურაცია
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger("MAIN")

# ────────────────────────────────────────────────

model = YOLO("best.pt")

MIN_WIDTH = 250
MIN_HEIGHT = 50
MIN_CONFIDENCE = 0.80

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
    global latest_display_frame, running
    
    log.info("🎥 HLS სტრიმინგის thread დაიწყო")
    
    while running:
        try:
            if latest_display_frame is not None:
                success = hls_streamer.write_frame(latest_display_frame)
                if not success:
                    log.warning("❌ HLS ფრეიმის გაგზავნა ჩავარდა")
            else:
                # თუ კადრი არ არის, გავაგზავნით შავ ეკრანს
                black_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                hls_streamer.write_frame(black_frame)
            
            time.sleep(0.033)  # ~30 FPS
            
        except Exception as e:
            log.error(f"HLS thread შეცდომა: {e}")
            time.sleep(0.1)
    
    log.info("🛑 HLS სტრიმინგის thread დასრულდა")

# HLS სტრიმერის შექმნა - ოპტიმალური პარამეტრებით
hls_streamer = HLSStreamer(HLS_DIR, segment_duration=2, output_name="wagon_stream")

CAMERA_URL = "rtsp://admin:admin@192.168.1.11:554"
DETECTION_INTERVAL = 0.1
SAVE_EVERY_N_DETECTIONS = 1

# კამერის მენეჯერის შექმნა
camera_manager = CameraManager(CAMERA_URL)
connection_screen = camera_manager.create_connection_screen()

print("იწყება. დააჭირე 'q'-ს გასაჩერებლად")
print(f"HLS სტრიმი ხელმისაწვდომია: {hls_streamer.get_playlist_url()}")

# HLS სტრიმის გაშვება
stream_started = hls_streamer.start_stream(width=1280, height=720, fps=15)
print(f"HLS სტრიმის სტატუსი: {stream_started}")

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

while True:
    loop_start = time.time()
    
    # ვამოწმებთ კამერის სტატუსს
    if not camera_manager.get_status():
        if not camera_manager.reconnect():
            # ეკრანის ჩვენება დაკავშირების მცდელობისას
            cv2.imshow("YOLO Camera + Detection", connection_screen)
            key = cv2.waitKey(1)
            if key == ord('q'):
                break
            continue

    # ფრეიმის კითხვა
    frame, success = camera_manager.read_frame()
    if not success:
        # ეკრანის ჩვენება რეკონექტის მცდელობისას
        cv2.imshow("YOLO Camera + Detection", connection_screen)
        key = cv2.waitKey(1)
        if key == ord('q'):
            break
        continue

    current_time = time.time()

    if current_time - last_detect_time >= DETECTION_INTERVAL:
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

    # ეკრანის არჩევა: თუ კამერა დაკავშირებულია - ნორმალური ეკრანი, თუ არა - connecting ეკრანი
    if camera_manager.get_status():
        display = last_annotated if last_annotated is not None else frame
        # ფრეიმის გადაცემა HLS thread-სთვის (არა პირდაპირ სტრიმში)
        latest_display_frame = display.copy()
    else:
        display = connection_screen
        latest_display_frame = display.copy()
        
    cv2.imshow("YOLO Camera + Detection", display)

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

print("პროგრამა დასრულდა.")