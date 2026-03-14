import cv2
import os
import shutil
from datetime import datetime

class ImageSaver:
    def __init__(self, save_dir="number_sectors"):
        self.save_dir = save_dir
        self._setup_directory()
    
    def _setup_directory(self):
        """ფოლდერის გასუფთავება და შექმნა"""
        if os.path.exists(self.save_dir):
            print(f"იშლება ძველი ფოლდერი: {self.save_dir}")
            shutil.rmtree(self.save_dir)
        
        os.makedirs(self.save_dir, exist_ok=True)
        print(f"შეიქმნა ახალი ფოლდერი: {self.save_dir}")
    
    def save_crop(self, frame, x1, y1, x2, y2, name, confidence):
        """ინახავს ობიექტის crop-ს 384x384 ზომაზე"""
        crop = frame[y1:y2, x1:x2]
        
        if crop.size == 0:
            return None
        
        # რესაიზი 384x384-ზე
        #resized_crop = cv2.resize(crop, (384, 96), interpolation=cv2.INTER_AREA)
        
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{self.save_dir}/{name}_{timestamp}_{confidence:.2f}.png"
        cv2.imwrite(filename,crop)
        
        return filename
