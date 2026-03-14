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

            use_local = os.path.isdir(local_path) and (
                os.path.exists(os.path.join(local_path, "pytorch_model.bin"))
                or os.path.exists(os.path.join(local_path, "model.safetensors"))
            )

            if use_local:
                print("ლოკალური მოდელი არსებობს → local_files_only=True")
                self.processor = TrOCRProcessor.from_pretrained(
                    local_path, local_files_only=True
                )
                self.model = VisionEncoderDecoderModel.from_pretrained(
                    local_path,
                    local_files_only=True,
                    torch_dtype=torch.float32,
                    low_cpu_mem_usage=False,
                )
            else:
                print("ლოკალური მოდელი არ არის → ჩამოტვირთვა Hugging Face-დან")
                self.processor = TrOCRProcessor.from_pretrained(model_id)
                self.model = VisionEncoderDecoderModel.from_pretrained(
                    model_id,
                    torch_dtype=torch.float32,
                    low_cpu_mem_usage=False,
                    ignore_mismatched_sizes=True,
                )
                os.makedirs(local_path, exist_ok=True)
                self.processor.save_pretrained(local_path)
                self.model.save_pretrained(local_path)
                print(f"მოდელი შენახულია: {local_path}")

            self.device = torch.device("cpu")
            print(f"მოდელი გადადის → {self.device}")
            self.model = self.model.to(self.device)
            self.model = self.model.float()

            self.model.eval()
            torch.set_num_threads(
                8 if torch.get_num_threads() >= 8 else torch.get_num_threads()
            )

            print(f"✅ TrOCR მზადაა: {self.device} | მოდელი: {model_id}")

        except Exception as e:
            print(f"❌ მოდელის ჩატვირთვის შეცდომა: {type(e).__name__}")
            traceback.print_exc()
            self.processor = None
            self.model = None
            self.device = None

    def extract_row_number(self, filename: str) -> int:
        match = re.match(r"^(\d+)_sector_", filename)
        return int(match.group(1)) if match else 0

    def recognize_number(self, image_path: str) -> str:
        if not self.processor or not self.model:
            return "მოდელი_არ_არის"

        try:
            image = Image.open(image_path).convert("RGB")

            with torch.inference_mode(), torch.no_grad():
                pixel_values = self.processor(
                    image, return_tensors="pt"
                ).pixel_values.to(self.device, non_blocking=True)

                generated_ids = self.model.generate(
                    pixel_values,
                    max_length=10,
                    num_beams=1,
                    early_stopping=True,
                    num_return_sequences=1,
                )

                text = self.processor.batch_decode(
                    generated_ids, skip_special_tokens=True
                )[0].strip()

                num = "".join(c for c in text if c.isdigit() or c.isalpha())

                is_locomotive = (
                    text.startswith(("VL", "TE", "TЭM", "T", "V"))
                    or "ЭM" in text.upper()
                    or "YM" in text.upper()
                )

                if is_locomotive:
                    return num
                elif len(num) == 8 and num.isdigit():
                    return num
                else:
                    return ""

        except Exception as e:
            print(f"შეცდომა {os.path.basename(image_path)}: {str(e)}")
            return "შეცდომა"

    def process_sectors(self, sectors_dir: str = "number_sectors"):
        if not os.path.exists(sectors_dir):
            print(f"❌ დირექტორია არ არსებობს: {sectors_dir}")
            return None

        results = {
            "timestamp": datetime.now().isoformat(),
            "model": "trocr-large-printed",
            "device": str(self.device),
            "wagons": {},
        }
        processed_count = 0
        success_count = 0

        print(f"📁 დამუშავდება: {sectors_dir}")

        for filename in sorted(os.listdir(sectors_dir)):
            if not filename.lower().endswith(".png"):
                continue

            processed_count += 1
            row_num = self.extract_row_number(filename)

            try:
                parts = filename.split("_")
                conf_str = parts[-1].replace(".png", "")
                confidence = float(conf_str)
            except:
                confidence = 0.0

            image_path = os.path.join(sectors_dir, filename)
            recognized = self.recognize_number(image_path)

            is_locomotive = recognized.startswith(("V", "T")) if recognized else False

            if recognized and recognized not in ["მოდელი_არ_არის", "შეცდომა", ""]:
                success_count += 1

                if row_num not in results["wagons"]:
                    results["wagons"][row_num] = []

                results["wagons"][row_num].append(
                    {
                        "filename": filename,
                        "confidence": confidence,
                        "recognized_number": recognized,
                        "source": "trocr-large-printed",
                        "is_locomotive": is_locomotive,
                    }
                )

            if processed_count % 10 == 0 or processed_count == 1:
                print(f"→ დამუშავებული: {processed_count} | წარმატებული: {success_count}")

        # ლოკომოტივების გაფილტვრა + რიგების გადანომვრა 1-დან
        print("\n🔄 ლოკომოტივების ამოღება და რიგების გადანომვრა 1-დან...")

        if not results["wagons"]:
            print("→ არაფერი დამუშავდა")
        else:
            sorted_rows = sorted(results["wagons"].keys())

            leading_loco_rows = []
            for row in sorted_rows:
                dets = results["wagons"][row]
                if dets and dets[0].get("is_locomotive", False):
                    leading_loco_rows.append(row)
                else:
                    break  # პირველი არალოკომოტივი რიგის შემდეგ წყვეტა

            print(f"წინა ლოკომოტივის რიგ(ებ)ი: {leading_loco_rows}")

            new_wagons = {}
            new_row_idx = 1

            for old_row in sorted_rows:
                if old_row in leading_loco_rows:
                    continue

                # რიგში მხოლოდ არალოკომოტივი ჩანაწერები
                clean_entries = [
                    entry for entry in results["wagons"][old_row]
                    if not entry.get("is_locomotive", False)
                ]

                if clean_entries:
                    new_wagons[new_row_idx] = clean_entries
                    new_row_idx += 1

            results["wagons"] = new_wagons

            if leading_loco_rows:
                print(f"ამოღებულია {len(leading_loco_rows)} წინა ლოკომოტივის რიგი")
            print(f"ვაგონების რიგები: {len(new_wagons)} (1-დან დაწყებული)")

        # შედეგის შენახვა (ლოკომოტივები უკვე ამოღებულია)
        with open("detection_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print("\n" + "═" * 60)
        print(f"დასრულდა | სულ ფაილი: {processed_count}")
        if processed_count > 0:
            percentage = (success_count / processed_count) * 100
            print(f"წარმატებული: {success_count} ({percentage:.1f}%)")
        print(f"საბოლოო ვაგონების რიგები: {len(results['wagons'])}")
        print("═" * 60)

        # საბოლოო შეჯამება კონსოლში
        for row in sorted(results["wagons"].keys()):
            entries = results["wagons"][row]
            nums = set(e["recognized_number"] for e in entries)
            print(f"რიგი {row:2d}: {len(entries):3d} ჩანაწერი | ნომრ(ებ)ი: {', '.join(nums)}")


if __name__ == "__main__":
    print("სკრიპტის გაშვება...")
    detector = WorkingNumberDetector()
    detector.process_sectors()