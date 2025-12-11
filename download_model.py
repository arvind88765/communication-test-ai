import os
import zipfile
import urllib.request

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
ZIP_NAME = "vosk-model-small-en-us-0.15.zip"
MODEL_FOLDER = "vosk-model-small-en-us-0.15"

def download_model():
    # Skip if already extracted
    if os.path.isdir(MODEL_FOLDER):
        print("Model folder already exists. Skipping download.")
        return

    # Download ZIP if not present
    if not os.path.isfile(ZIP_NAME):
        print("Downloading Vosk model...")
        urllib.request.urlretrieve(MODEL_URL, ZIP_NAME)
        print("Download complete.")
    else:
        print("ZIP already downloaded. Skipping.")

    # Extract ZIP
    print("Extracting model...")
    with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
        zip_ref.extractall(".")
    print("Extraction complete.")

    # Rename folder (model folders sometimes include version suffix)
    for f in os.listdir("."):
        if f.startswith("vosk-model-small-en-us") and f != MODEL_FOLDER:
            os.rename(f, MODEL_FOLDER)
            break

    print("Model ready:", MODEL_FOLDER)


if __name__ == "__main__":
    download_model()
