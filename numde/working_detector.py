import os
import json
import re
import torch
from datetime import datetime
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
import traceback
from collections import Counter
import logging

log = logging.getLogger("WORKING_DETECTOR")


class WorkingNumberDetector:
    """მუშაობდან დეტექტორი - TrOCR-ზე დაფუძნებული ვაგონების ნომრების ამომცნობი სისტემა"""
    
    def __init__(self):
        log.info("🔍 მუშაობდან დეტექტორის ინიციალიზაცია")
        self.model_name = "microsoft/trocr-large-printed"
        self.local_path = "./models/trocr-large-printed"
        self.processor = None
        self.model = None
        self.device = None
        self.load_model()

    def load_model(self):
        """TrOCR მოდელის ჩატვირთვა ლოკალური კეშირებით"""
        try:
            use_local = os.path.isdir(self.local_path) and (
                os.path.exists(os.path.join(self.local_path, "pytorch_model.bin"))
                or os.path.exists(os.path.join(self.local_path, "model.safetensors"))
            )

            if use_local:
                log.info("ლოკალური მოდელი → local_files_only=True")
                self.processor = TrOCRProcessor.from_pretrained(self.local_path, local_files_only=True)
                self.model = VisionEncoderDecoderModel.from_pretrained(
                    self.local_path, local_files_only=True, torch_dtype=torch.float32, low_cpu_mem_usage=False
                )
            else:
                log.info("ჩამოტვირთვა Hugging Face-დან...")
                self.processor = TrOCRProcessor.from_pretrained(self.model_name)
                self.model = VisionEncoderDecoderModel.from_pretrained(
                    self.model_name, torch_dtype=torch.float32, low_cpu_mem_usage=False, ignore_mismatched_sizes=True
                )
                os.makedirs(self.local_path, exist_ok=True)
                self.processor.save_pretrained(self.local_path)
                self.model.save_pretrained(self.local_path)

            self.device = torch.device("cpu")
            self.model = self.model.to(self.device).float()
            self.model.eval()
            torch.set_num_threads(8 if torch.get_num_threads() >= 8 else torch.get_num_threads())

            log.info(f"✅ TrOCR მზადაა: {self.device}")

        except Exception as e:
            log.error(f"❌ მოდელის ჩატვირთვის შეცდომა: {type(e).__name__}")
            traceback.print_exc()
            self.processor = self.model = None

    def extract_row_number(self, filename: str) -> int:
        """ფაილის სახელიდან რიგის ნომრის ამოღება"""
        match = re.match(r"^(\d+)_sector_", filename)
        return int(match.group(1)) if match else 0

    def recognize_number(self, image_path: str) -> str:
        """ნომრის ამოცნობა TrOCR მოდელით"""
        if not self.processor or not self.model:
            return "მოდელი_არ_არის"

        try:
            image = Image.open(image_path).convert("RGB")
            
            with torch.inference_mode(), torch.no_grad():
                pixel_values = self.processor(image, return_tensors="pt").pixel_values.to(self.device)
                generated_ids = self.model.generate(
                    pixel_values, max_length=10, num_beams=1, early_stopping=True
                )
                text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()

                # ტექსტის გაწმენდა
                num = "".join(c for c in text if c.isdigit() or c.isalpha())
                
                # ლოკომოტივების დეტექცია
                is_loco = (
                    text.startswith(("VL", "TE", "TЭM", "T", "V"))
                    or "ЭM" in text.upper() or "YM" in text.upper()
                )

                if is_loco:
                    return num
                if len(num) == 8 and num.isdigit():
                    return num
                return ""
                
        except Exception as e:
            log.error(f"შეცდომა {os.path.basename(image_path)}: {str(e)}")
            return "შეცდომა"

    def process_sectors(self, sectors_dir: str = "number_sectors"):
        """სექტორების დამუშავება და შედეგების გენერაცია"""
        if not os.path.exists(sectors_dir):
            log.error(f"❌ დირექტორია არ არსებობს: {sectors_dir}")
            return None

        results = {
            "timestamp": datetime.now().isoformat(),
            "model": "trocr-large-printed",
            "device": str(self.device),
            "wagons": {}
        }
        processed_count = success_count = 0

        log.info(f"📁 დამუშავდება: {sectors_dir}")

        for filename in sorted(os.listdir(sectors_dir)):
            if not filename.lower().endswith(".png"):
                continue

            processed_count += 1
            row_num = self.extract_row_number(filename)

            try:
                confidence = float(filename.split("_")[-1].replace(".png", ""))
            except:
                confidence = 0.0

            image_path = os.path.join(sectors_dir, filename)
            recognized = self.recognize_number(image_path)
            is_locomotive = recognized.startswith(("V", "T")) if recognized else False

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
                log.info(f"→ დამუშავებული: {processed_count} | წარმატებული: {success_count}")

        # ლოკომოტივების ამოღება + რიგების გადანომვრა
        log.info("\n🔄 ლოკომოტივების ამოღება და საბოლოო დამუშავება...")

        if not results["wagons"]:
            log.info("→ არაფერი დამუშავდა")
            return

        sorted_rows = sorted(results["wagons"].keys())
        leading_loco_rows = [
            row for row in sorted_rows
            if results["wagons"][row] and results["wagons"][row][0].get("is_locomotive")
        ]

        new_wagons = {}
        new_row_idx = 1

        for old_row in sorted_rows:
            if old_row in leading_loco_rows:
                continue

            clean_entries = [
                e for e in results["wagons"][old_row]
                if not e.get("is_locomotive")
            ]

            if clean_entries:
                new_wagons[new_row_idx] = clean_entries
                new_row_idx += 1

        results["wagons"] = new_wagons

        # საბოლოო შედეგის გენერაცია
        final_results = {
            "total_wagons": len(new_wagons),
            "wagons": []
        }

        log.info("\n📊 საბოლოო შედეგი:")

        for row in sorted(new_wagons.keys()):
            entries = new_wagons[row]
            numbers = [e["recognized_number"] for e in entries if e["recognized_number"]]

            if not numbers:
                continue

            counter = Counter(numbers)
            if not counter:
                continue

            most_common_num, top_count = counter.most_common(1)[0]
            total = len(numbers)

            # ────────────────────────────────
            #      გაუმჯობესებული quality
            # ────────────────────────────────
            second_count = counter.most_common(2)[1][1] if len(counter) >= 2 else 0
            gap = top_count - second_count
            unique = len(counter)

            if top_count == total:
                quality_score = 98.0
            elif top_count >= total * 0.80 and top_count >= 4:
                quality_score = 90.0 + (gap * 2)
            elif top_count >= total * 0.65 and top_count >= 3:
                quality_score = 72.0 + (gap * 3)
            elif top_count >= 3:
                quality_score = 55.0 + (gap * 4)
            elif top_count == 2:
                quality_score = 38.0 + (gap * 5)
            else:
                quality_score = 18.0

            # ზედა ზღვარი და მინიმუმი
            quality_score = max(10.0, min(100.0, quality_score))

            # საშუალო ნდობა მხოლოდ საუკეთესოსთვის
            matching_confidences = [
                e["confidence"] for e in entries if e["recognized_number"] == most_common_num
            ]
            avg_confidence = sum(matching_confidences) / len(matching_confidences) if matching_confidences else 0

            final_results["wagons"].append({
                "row": row,
                "number": most_common_num,
                "quality": f"{quality_score:.1f}",
            })

            log.info(
                f"რიგი {row:2d}: {most_common_num}  |  "
                f"{top_count}/{total}  ({quality_score:.1f})  |  "
                f"საშ. ნდობა: {avg_confidence:.3f}"
            )

        # ფაილების შენახვა
        try:
            with open("detection_results.json", "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            with open("final_wagons.json", "w", encoding="utf-8") as f:
                json.dump(final_results, f, ensure_ascii=False, indent=2)

        except Exception as e:
            log.error(f"ფაილების შენახვის შეცდომა: {e}")

        return final_results


if __name__ == "__main__":
    log.info("სკრიპტის გაშვება...")
    detector = WorkingNumberDetector()
    detector.process_sectors()