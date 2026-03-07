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
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)
                self.cap.set(cv2.CAP_PROP_FPS, self.fps)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.open_timeout)
                self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout)
                
                self.is_connected = True
                print("კამერა დაკავშირებულია!")
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
