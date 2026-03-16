import cv2
import time
import numpy as np


class CameraManager:
    """კამერის მართვის კლასი"""
    
    def __init__(self, camera_url, width=1280, height=720):
        self.camera_url = camera_url
        self.width = width
        self.height = height
        self.cap = cv2.VideoCapture()
        self.is_connected = False
        
        # კამერის პარამეტრები
        self.buffer_size = 3
        self.fps = 15
        self.open_timeout = 10000
        self.read_timeout = 5000
    
    def create_connection_screen(self):
        """ქმნის 'Connecting...' ეკრანს"""
        screen = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        cv2.putText(screen, "Connecting to camera...", (self.width//2 - 200, self.height//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
        cv2.putText(screen, self.camera_url, (self.width//2 - 250, self.height//2 + 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return screen
    
    def connect(self):
        """აკავშირებს კამერასთან"""
        try:
            self.cap = cv2.VideoCapture(self.camera_url, cv2.CAP_FFMPEG)
            
            if self.cap.isOpened():
                # ჯერ დავაყენოთ ფუნდამენტური პარამეტრები
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # მინიმალური ბაფერი
                self.cap.set(cv2.CAP_PROP_FPS, 15)
                self.cap.set(cv2.CAP_PROP_EXPOSURE,     -8)    # მნიშვნელობა -13 .. -1 .. 0 .. + სხვადასხვა კამერაზე განსხვავებულია
                self.cap.set(cv2.CAP_PROP_GAIN,          0)
                self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.open_timeout)
                self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout)
                
                # მნიშვნელოვანი: ჯერ წავიკითხოთ ერთი ფრეიმი რეალური რეზოლუციის დასადგენად
                ret, test_frame = self.cap.read()
                if ret and test_frame is not None:
                    # დავადგინოთ კამერის რეალური რეზოლუცია
                    actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    actual_fps = int(self.cap.get(cv2.CAP_PROP_FPS))
                    
                    print(f"კამერის რეალური პარამეტრები: {actual_width}x{actual_height} @ {actual_fps}fps")
                    
                    # თუ მაღალი რეზოლუციაა, დავაყენოთ 720p სტაბილურობისთვის
                    if actual_width > 1280 or actual_height > 720:
                        print("მაღალი რეზოლუცია აღმოჩნდა, დაყენება 720p-ზე სტაბილურობისთვის")
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                        self.width = 1280
                        self.height = 720
                    else:
                        # შევინარჩუნოთ კამერის რეალური რეზოლუცია
                        self.width = actual_width
                        self.height = actual_height
                
                self.is_connected = True
                print(f"კამერა დაკავშირებულია! რეზოლუცია: {self.width}x{self.height}")
                return True
            else:
                self.is_connected = False
                return False
                
        except Exception as e:
            print(f"კამერის დაკავშირების შეცდომა: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """ათიშავს კამერასთან კავშირს"""
        if self.cap.isOpened():
            self.cap.release()
        self.is_connected = False
        print("კამერა გათიშულია")
    
    def read_frame(self):
        """კითხულობს ფრეიმს კამერიდან"""
        if not self.is_connected or not self.cap.isOpened():
            return None, False
        
        ret, frame = self.cap.read()
        if not ret:
            self.is_connected = False
            print("ფრეიმი ვერ წაიკითხა")
            return None, False
        
        return frame, True
    
    def reconnect(self):
        """თავიდან აკავშირებს კამერას"""
        print("კამერა გათიშულია, ვცდილობთ დაკავშირებას...")
        self.disconnect()
        time.sleep(1)
        return self.connect()
    
    def get_status(self):
        """აბრუნებს კამერის სტატუსს"""
        return self.is_connected
    
    def release(self):
        """ათავისუფლებს რესურსებს"""
        self.disconnect()
