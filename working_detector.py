import os
import json
import re
import torch
from datetime import datetime
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
import traceback


class WorkingNumberDetector:
    def __init__(self):
        print("🔍 მუშაობდან დეტექტორი")
        self.load_model()

    def load_model(self):
        try:
            model_id = "microsoft/trocr-large-printed"
            local_path = "./models/trocr-large-printed"

            print(f"მოდელის ჩატვირთვის მცდელობა: {local_path}")

            # ლოკალური მოდელის არსებობის შემოწმება (pytorch_model.bin ან model.safetensors)
            use_local = os.path.isdir(local_path) and (
                os.path.exists(os.path.join(local_path, "pytorch_model.bin")) or 
                os.path.exists(os.path.join(local_path, "model.safetensors"))
            )

            if use_local:
                print("ლოკალური მოდელი არსებობს → ცდა local_files_only=True-ით")
                self.processor = TrOCRProcessor.from_pretrained(
                    local_path,
                    local_files_only=True
                )
                self.model = VisionEncoderDecoderModel.from_pretrained(
                    local_path,
                    local_files_only=True,
                    torch_dtype=torch.float32,
                    low_cpu_mem_usage=False
                )
            else:
                print("ლოკალური მოდელი არ არის ან არასრული → ჩამოტვირთვა Hugging Face-დან")
                self.processor = TrOCRProcessor.from_pretrained(model_id)
                self.model = VisionEncoderDecoderModel.from_pretrained(
                    model_id,
                    torch_dtype=torch.float32,
                    low_cpu_mem_usage=False,
                    ignore_mismatched_sizes=True
                )
                # შენახვა ლოკალურად მომავალი გამოყენებისთვის
                os.makedirs(local_path, exist_ok=True)
                self.processor.save_pretrained(local_path)
                self.model.save_pretrained(local_path)
                print(f"მოდელი შენახულია: {local_path}")
                print("⚠️ შემდეგ გაშვებაზე გამოიყენება ლოკალური მოდელი")

            # მოდელის გადატანა CPU-ზე (მკაცრად)
            self.device = torch.device("cpu")
            print(f"მოდელი გადადის → {self.device}")
            self.model = self.model.to(self.device)
            self.model = self.model.float()  # float32 უზრუნველყოფა

            self.model.eval()
            torch.set_num_threads(8 if torch.get_num_threads() >= 8 else torch.get_num_threads())

            print(f"✅ TrOCR მზადაა: {self.device} | მოდელი: {model_id}")

        except Exception as e:
            print(f"❌ მოდელის ჩატვირთვის შეცდომა: {type(e).__name__}")
            traceback.print_exc()
            self.processor = None
            self.model = None
            self.device = None

    def extract_row_number(self, filename: str) -> int:
        match = re.match(r'^(\d+)_sector_', filename)
        return int(match.group(1)) if match else 0

    def recognize_number(self, image_path: str) -> str:
        if not self.processor or not self.model:
            return "მოდელი_არ_არის"

        try:
            image = Image.open(image_path).convert("RGB")
            image = image.resize((384, 96), Image.Resampling.LANCZOS)  # უკეთესი რესემპლინგი

            with torch.inference_mode(), torch.no_grad():
                pixel_values = self.processor(
                    image,
                    return_tensors="pt"
                ).pixel_values.to(self.device, non_blocking=True)

                # დამატებითი დაცვა — ხელახლა გადატანა generate-მდე
                self.model.to(self.device)

                generated_ids = self.model.generate(
                    pixel_values,
                    max_length=12,
                    num_beams=1,           # სწრაფად CPU-ზე
                    early_stopping=True
                )

                text = self.processor.batch_decode(
                    generated_ids,
                    skip_special_tokens=True
                )[0].strip()

                # ტექსტიდან ამოღება - პირველ ასოებს ვტოვებთ ლოკომოტივის დასადგენად
                num = "".join(c for c in text if c.isdigit() or c.isalpha())
                
                # ლოკომოტივის დადგენა - ფართო შემოწმება (VL, TE, TЭM და სხვა)
                is_locomotive = (text.startswith(('VL', 'TE', 'TЭM', 'T')) or 
                               'ЭM' in text or 'YM' in text or 
                               text.startswith('V') or text.startswith('T'))
                
                # თუ ლოკომოტივია, ვაბრუნებთ სრულ ტექსტს, თუ არა - მხოლოდ 8 ციფრს
                if is_locomotive:
                    return num
                elif len(num) == 8 and num.isdigit():
                    return num
                else:
                    return ""  # თუ სიგრძე არ ემთხვევა ან ციფრები არ არის, დავაბრუნოთ ცარიელი

        except Exception as e:
            print(f"რიცხვის ამოცნობის შეცდომა {os.path.basename(image_path)}: {str(e)}")
            # traceback.print_exc()  # გააქტიურე თუ გჭირდება სრული traceback
            return "შეცდომა"

    def process_sectors(self, sectors_dir: str = "number_sectors"):
        if not os.path.exists(sectors_dir):
            print(f"❌ დირექტორია არ არსებობს: {sectors_dir}")
            return None

        results = {
            "timestamp": datetime.now().isoformat(),
            "model": "trocr-large-printed",
            "device": str(self.device),
            "wagons": {}
        }
        processed_count = 0
        success_count = 0

        print(f"📁 დამუშავდება დირექტორია: {sectors_dir}")

        for filename in sorted(os.listdir(sectors_dir)):
            if not filename.lower().endswith('.png'):
                continue

            processed_count += 1
            row_num = self.extract_row_number(filename)

            # confidence-ის უსაფრთხო ამოღება
            try:
                parts = filename.split('_')
                conf_str = parts[-1].replace('.png', '')
                confidence = float(conf_str)
            except:
                confidence = 0.0

            image_path = os.path.join(sectors_dir, filename)
            recognized = self.recognize_number(image_path)

            # ლოკომოტივის დადგენა
            is_locomotive = recognized.startswith(('V', 'T')) if recognized else False

            # მხოლოდ წარმატებული შედეგების დამუშავება (არაცარიელი ნომრები)
            if recognized and recognized not in ["მოდელი_არ_არის", "შეცდომა", ""]:
                success_count += 1

                if row_num not in results["wagons"]:
                    results["wagons"][row_num] = []

                results["wagons"][row_num].append({
                    "filename": filename,
                    "confidence": confidence,
                    "recognized_number": recognized,
                    "source": "trocr-large-printed",
                    "is_locomotive": is_locomotive
                })

            if processed_count % 10 == 0 or processed_count == 1:
                print(f"→ დამუშავებული: {processed_count} | წარმატებული: {success_count}")

        # შედეგების შენახვა
        with open("detection_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print("\n" + "═" * 60)
        print(f"დასრულდა | სულ ფაილი: {processed_count}")
        if processed_count > 0:
            percentage = (success_count / processed_count) * 100
            print(f"წარმატებული ამოცნობა: {success_count} ({percentage:.1f}%)")
        else:
            print("წარმატებული ამოცნობა: 0 (0.0%)")
        print(f"ნაპოვნი უნიკალური რიგი: {len(results['wagons'])}")
        print("═" * 60)

        # ლოკომოტივის ლოგიკა: თუ პირველი ელემენტი ლოკომოტივია, ვაგონების რიგის ნომრებს ვაკლებთ 1-ს
        for row in list(results["wagons"].keys()):
            detections = results["wagons"][row]
            
            # შევამოწმოთ არის თუ არა პირველი ელემენტი ლოკომოტივი
            if detections and detections[0].get("is_locomotive", False):
                # წავშალოთ ეს რიგი და ვაგონებით შევცვალოთ ერთით ნაკლები რიგის ნომრით
                del results["wagons"][row]
                new_row = row - 1
                if new_row not in results["wagons"]:
                    results["wagons"][new_row] = []
                results["wagons"][new_row].extend(detections)
        
        # მოკლე შეჯამება
        for row in sorted(results["wagons"].keys()):
            dets = results["wagons"][row]
            good = [d for d in dets if d["recognized_number"].isnumeric() and len(d["recognized_number"]) >= 4]
            if good:
                print(f"რიგი {row:2d}: {len(good):2d} კარგი / {len(dets)} სულ")
                for d in good[:3]:
                    loco_text = " [ლოკომოტივი]" if d.get("is_locomotive", False) else ""
                    print(f"   → {d['recognized_number']:>8}  ({d['confidence']:.2f}){loco_text}")
                if len(good) > 3:
                    print(f"   ... და კიდევ {len(good)-3} კარგი")

        return results


if __name__ == "__main__":
    print("სკრიპტის გაშვება...")
    detector = WorkingNumberDetector()
    if hasattr(detector, 'process_sectors'):
        detector.process_sectors()
    else:
        print("CRITICAL: process_sectors მეთოდი არ არსებობს კლასში!")