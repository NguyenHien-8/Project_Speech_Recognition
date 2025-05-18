# drink_order_voice.py
import sounddevice as sd
import queue
import json
import requests
import re
import os
import tempfile
import threading
from vosk import Model, KaldiRecognizer
from rapidfuzz import fuzz
from gtts import gTTS
from pydub import AudioSegment
from pydub.playback import play
import time
from Installsubabase import supabase

# ========================== CẤU HÌNH ==========================
SERVER_URL = "http://your-server-url-here"  # cập nhật lại URL thực tế

# ========================== GLOBAL STATE ==========================
q = queue.Queue()
is_speaking = False
keywords = {
    "Drink": {},
    "Size": {
        "S": ["size s", "s"],
        "M": ["size m", "m"],
        "L": ["size l", "l"]
    },
    "YesNo": {
        "Yes": ["yes", "yeah", "correct", "sure", "right"],
        "No": ["no", "nope", "not", "incorrect", "wrong"]
    }
}
components = {
    "coffee": ["coffee", "sugar"],
    "milk coffee": ["coffee", "milk"],
    "milk tea": ["tea", "milk"],
    "sugar tea": ["tea", "sugar"]
}

# ========================== SUPABASE DRINKS ==========================
def fetch_drinks_from_supabase():
    try:
        response = supabase.table("drinkdata").select("drink_name").execute()
        return [item['drink_name'].lower() for item in response.data if 'drink_name' in item]
    except Exception as e:
        print("Error fetching drinks:", str(e))
        return []

def update_drink_keywords(drink_list):
    keywords["Drink"] = {}
    for drink in drink_list:
        clean = normalize_text(drink)
        keywords["Drink"][clean] = [clean]

# ========================== TEXT-TO-SPEECH ==========================
def speak(text):
    global is_speaking
    if not text.strip(): return
    is_speaking = True
    print(f"[TTS]: {text}")
    tts = gTTS(text=text, lang='en')
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        tts.save(f.name)
        sound = AudioSegment.from_mp3(f.name)
        play(sound)
    os.unlink(f.name)
    time.sleep(0.3)
    is_speaking = False

# ========================== AUDIO CALLBACK ==========================
def callback(indata, frames, time_, status):
    if status: print("Audio error:", status)
    if not is_speaking:
        q.put(bytes(indata))

# ========================== UTILITY FUNCTIONS ==========================
def normalize_text(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()

def detect_best_match(text, category, threshold=80):
    best = {"score": 0, "label": None, "length": 0}
    for label, kw_list in keywords[category].items():
        for kw in kw_list:
            score = fuzz.partial_ratio(text, kw)
            if score > best["score"] or (score == best["score"] and len(kw.split()) > best["length"]):
                best.update({"score": score, "label": label, "length": len(kw.split())})
    return best["label"] if best["score"] >= threshold else None

def is_valid_speech(text):
    if not text: return False
    for cat in keywords.values():
        for kws in cat.values():
            for kw in kws:
                if kw in text:
                    return True
    return False

def send_order_to_server(order_data):
    try:
        headers = {"Content-Type": "application/json"}
        res = requests.post(SERVER_URL, json=order_data, headers=headers)
        print("Order sent:", res.status_code, res.text)
    except Exception as e:
        print("Send failed:", str(e))

# ========================== MAIN VOICE ORDER LOGIC ==========================
def run_voice_order_loop():
    print("Initializing voice order system...")

    model_en = Model("vosk-model-small-en-us-0.15")
    rec = KaldiRecognizer(model_en, 16000)
    rec.SetWords(True)

    sd.default.device = sd.query_devices(kind='input')['name']
    device_info = sd.query_devices(sd.default.device, 'input')
    samplerate = int(device_info['default_samplerate'])

    drinks = fetch_drinks_from_supabase()
    update_drink_keywords(drinks)

    speak("Hello! What would you like to drink?")
    step = 1
    selected_drink = None
    selected_size = None
    waiting_confirmation = False
    pending_value = None
    pending_category = None
    customizing = False
    current_component_index = 0
    component_sizes = {}

    with sd.RawInputStream(samplerate=samplerate, blocksize=4000, dtype='int16', channels=1, callback=callback):
        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                text = normalize_text(json.loads(rec.Result()).get("text", ""))
                print("Heard:", text)

                if is_speaking or not text or not is_valid_speech(text):
                    print("Ignored.")
                    continue

                if waiting_confirmation:
                    answer = detect_best_match(text, "YesNo")
                    if answer == "Yes":
                        if pending_category == "Drink":
                            selected_drink = pending_value
                            if selected_drink in components:
                                speak(f"You chose {selected_drink}. Customize?")
                                pending_category = "Customize"
                            else:
                                speak("This drink cannot be customized. Choose size.")
                                step = 2
                            waiting_confirmation = True
                        elif pending_category == "Customize":
                            customizing = True
                            current_component_index = 0
                            component_sizes.clear()
                            speak(f"What size for {components[selected_drink][0]}?")
                            step = 3
                            waiting_confirmation = False
                        elif pending_category == "Size":
                            selected_size = pending_value
                            speak(f"Confirmed {selected_drink} - size {selected_size}. Thank you!")
                            send_order_to_server({
                                "selected_drink": selected_drink,
                                "selected_size": selected_size
                            })
                            break
                        elif pending_category == "ComponentSize":
                            comp = components[selected_drink][current_component_index]
                            component_sizes[comp] = pending_value
                            current_component_index += 1
                            if current_component_index < len(components[selected_drink]):
                                next_comp = components[selected_drink][current_component_index]
                                speak(f"What size for {next_comp}?")
                            else:
                                speak("Confirmed custom order. Thank you!")
                                send_order_to_server({
                                    "selected_drink": selected_drink,
                                    "customized_sizes": component_sizes
                                })
                                break
                            waiting_confirmation = False
                    elif answer == "No":
                        speak("Please repeat.")
                        waiting_confirmation = False
                    else:
                        speak("Please say yes or no.")
                    continue

                if step == 1:
                    drink = detect_best_match(text, "Drink")
                    if drink:
                        speak(f"Did you mean {drink}?")
                        pending_value = drink
                        pending_category = "Drink"
                        waiting_confirmation = True
                    else:
                        speak("Sorry, I didn't recognize the drink.")

                elif step == 2:
                    size = detect_best_match(text, "Size")
                    if size:
                        speak(f"Did you mean size {size}?")
                        pending_value = size
                        pending_category = "Size"
                        waiting_confirmation = True
                    else:
                        speak("Sorry, I didn't recognize the size.")

                elif step == 3:
                    size = detect_best_match(text, "Size")
                    if size:
                        comp = components[selected_drink][current_component_index]
                        speak(f"Did you mean size {size} for {comp}?")
                        pending_value = size
                        pending_category = "ComponentSize"
                        waiting_confirmation = True
                    else:
                        speak("Sorry, I didn't recognize the size.")
