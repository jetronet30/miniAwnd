import cv2
from ultralytics import YOLO
import time
import os
from datetime import datetime

# image_saver იმპორტი (შეცვალე . თუ პაკეტშია, ან უბრალოდ image_saver თუ იმავე საქაღალდეშია)
from .image_saver import ImageSaver   # ან from .image_saver import ImageSaver

# ────────────────────────────────────────────────

model = YOLO("best.pt")

MIN_WIDTH = 250
MIN_HEIGHT = 50
MIN_CONFIDENCE = 0.80

SAVE_DIR = "nuber_sectors"
os.makedirs(SAVE_DIR, exist_ok=True)

image_saver = ImageSaver(SAVE_DIR)

camera_url = "rtsp://admin:admin@192.168.1.11:554"

# რამდენ ჯერზე ერთხელ შეინახოს დეტექტირებული ობიექტი
SAVE_EVERY_N_DETECTIONS = 1   # ← შეცვალე ეს რიცხვი
                              # 5  = ყოველ მე-5 დეტექციაზე
                              # 10 = ყოველ მე-10-ზე (ძალიან ცოტა)
                              # 3  = უფრო ხშირად

# ────────────────────────────────────────────────

cap = cv2.VideoCapture(camera_url, cv2.CAP_FFMPEG)

# RTSP-ისთვის ოპტიმალური პარამეტრები
cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)
cap.set(cv2.CAP_PROP_FPS, 15)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)

if not cap.isOpened():
    print("კამერა ვერ გაიხსნა!")
    exit()

print("იწყება. დააჭირე 'q'-ს გასაჩერებლად")

last_annotated = None
last_detect_time = time.time()
DETECTION_INTERVAL = 0.1          # დეტექცია ~1.25 fps-ზე (შეგიძლია 1.0–2.0-მდე გაზარდო)

save_counter = 0                  # ← ახალი კონტროლერი

while True:
    loop_start = time.time()

    ret, frame = cap.read()
    if not ret:
        print("ფრეიმი ვერ წაიკითხა → reconnect")
        cap.release()
        time.sleep(1)
        cap = cv2.VideoCapture(camera_url, cv2.CAP_FFMPEG)
        continue

    current_time = time.time()

    # დეტექცია ინტერვალით
    if current_time - last_detect_time >= DETECTION_INTERVAL:
        try:
            results = model(frame, conf=MIN_CONFIDENCE, verbose=False, imgsz=640)[0]
            annotated = frame.copy()

            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf)
                cls = int(box.cls)
                name = model.names[cls]

                w = x2 - x1
                h = y2 - y1

                cv2.putText(annotated, f"{name} {conf:.2f}", (x1, y1-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                cv2.putText(annotated, f"W:{w} H:{h}", (x1, y2+20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

                if h > MIN_HEIGHT and w > MIN_WIDTH:
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 3)
                    
                    # ← აქედან იწყება შენახვის კონტროლი
                    save_counter += 1
                    if save_counter % SAVE_EVERY_N_DETECTIONS == 0:
                        image_saver.save_crop(frame, x1, y1, x2, y2, name, conf)
                        print(f"შენახული (ყოველ {SAVE_EVERY_N_DETECTIONS}-ზე): {name} {conf:.2f}")
                    # else:
                    #     print(f"გამოტოვებული: {name}")

                else:
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)

            last_annotated = annotated
            last_detect_time = current_time

        except Exception as e:
            print(f"YOLO error: {e}")
            last_annotated = frame.copy()

    # ჩვენება
    display = last_annotated if last_annotated is not None else frame
    cv2.imshow("YOLO Camera + Detection", display)

    # გასვლა + FPS ლიმიტი
    key = cv2.waitKey(1)
    if key == ord('q'):
        break

    elapsed = time.time() - loop_start
    sleep_needed = max(0, 0.033 - elapsed)  # ~30 fps
    if sleep_needed > 0:
        time.sleep(sleep_needed)

# გაწმენდა
cap.release()
cv2.destroyAllWindows()
print("პროგრამა დასრულდა.")