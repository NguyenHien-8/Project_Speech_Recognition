# ============================================= Nguyen Hien ==============================================
import sounddevice as sd
import queue
import json
import requests
import re
import os
import tempfile
from vosk import Model, KaldiRecognizer
from rapidfuzz import fuzz

# ========== Text-to-Speech using Coqui TTS ==========


# ========== Send JSON to server ==========
SERVER_URL = " " 
def send_order_to_server(order_data):
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(SERVER_URL, json=order_data, headers=headers)
        print("Server response:", response.status_code, response.text)
    except Exception as e:
        print("Failed to send order to server:", str(e))

# ========== Voice Recognition Setup ==========
model_en = Model("vosk-model-small-en-us-0.15")
keywords = {
    "Drink": {
        "coffee": ["coffee"],
        "milk coffee": ["milk coffee"],
        "milk tea": ["milk tea"],
        "sweet tea": ["sweet tea"]
    },
    "Size": {
        "S": ["size s"],
        "M": ["size m"],
        "L": ["size l"]
    },
    "YesNo": {
        "Yes": ["yes", "yeah", "correct"],
        "No": ["no", "nope", "not"]
    }
}     
q = queue.Queue()
device_info = sd.query_devices(sd.default.device[0], 'input')
samplerate = int(device_info['default_samplerate'])
# Initialize recognizers for both languages
rec = KaldiRecognizer(model_en, samplerate)
rec.SetWords(True)
# CallBack to receive audio data
def callback(indata, frames, time, status):
    if status:
        print("Audio Error:", status)
    q.put(bytes(indata))

def normalize_text(text):   # Text normalization
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)  # remove punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text

def detect_best_match(text, category, threshold=80):
    best_match = {"score": 0, "label": None, "length": 0}
    for label, kw_list in keywords[category].items():
        for kw in kw_list:
            score = fuzz.partial_ratio(text, kw)
            if score > best_match["score"] or (
                score == best_match["score"] and len(kw.split()) > best_match["length"]
            ):
                best_match.update({"score": score, "label": label, "length": len(kw.split())})
    if best_match["score"] >= threshold:
        return best_match["label"]
    return None
# ================================================ Run ==================================================
print(f"Listening... (Sample Rate = {samplerate})")

print("Hello! What would you like to drink?")

step = 1
selected_drink = None
selected_size = None
waiting_confirmation = False
pending_value = None
pending_category = None

with sd.RawInputStream(samplerate=samplerate, blocksize=8000, dtype='int16',
                       channels=1, callback=callback):
    while True:
        data = q.get()
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            text = normalize_text(result.get("text", ""))
            if not text:
                continue
            print("You said:", text)

            if waiting_confirmation:
                answer = detect_best_match(text, "YesNo")
                if answer == "Yes":
                    if pending_category == "Drink":
                        selected_drink = pending_value
          
                        print(f"You chose drink: {selected_drink}. What size do you want?")
                        step = 2
                    elif pending_category == "Size":
                        selected_size = pending_value
                     
                        print(f"You chose size: {selected_size}. Order successful!")
                        print(f"Confirm: {selected_drink} - size {selected_size}")
                        # =================== JSON ===================
                        order_data = {
                            "selected_drink": selected_drink,
                            "selected_size": selected_size
                        }
                        print("Order JSON:", json.dumps(order_data))
                        send_order_to_server(order_data)
                        break
                    waiting_confirmation = False
                    pending_value = None
                    pending_category = None
                elif answer == "No":
    
                    print("Sorry.Please try again")
                    if pending_category == "Drink":
                  
                        print("What would you like to drink?")
                        step = 1
                    elif pending_category == "Size":
               
                        print("What size do you want?")
                        step = 2
                    waiting_confirmation = False
                    pending_value = None
                    pending_category = None
                else:
               
                    print("Please say yes or no.")
                continue

            
            if step == 1:
                drink = detect_best_match(text, "Drink")
                if drink:
            
                    print(f"Did you mean drink {drink}? (yes/no)")
                    pending_value = drink
                    pending_category = "Drink"
                    waiting_confirmation = True
                else:
            
                    print("Drink not recognized. Please try again.")

            
            elif step == 2:
                size = detect_best_match(text, "Size")
                if size:
          
                    print(f"Did you mean size {size}? (yes/no)")
                    pending_value = size
                    pending_category = "Size"
                    waiting_confirmation = True
                else:
                 
                    print("Size not recognized. Please try again.")


