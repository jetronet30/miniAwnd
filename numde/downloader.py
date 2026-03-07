from transformers import TrOCRProcessor, VisionEncoderDecoderModel
import os

MODEL_NAME = "microsoft/trocr-large-printed"
SAVE_DIR = "./models/trocr-large-printed"

def download_model():
    os.makedirs(SAVE_DIR, exist_ok=True)

    print(f"Downloading {MODEL_NAME} ...")

    processor = TrOCRProcessor.from_pretrained(MODEL_NAME)
    model = VisionEncoderDecoderModel.from_pretrained(MODEL_NAME)

    print("Saving model locally ...")

    processor.save_pretrained(SAVE_DIR)
    model.save_pretrained(SAVE_DIR)

    print(f"✅ Done! Model saved to: {SAVE_DIR}")


if __name__ == "__main__":
    download_model()
