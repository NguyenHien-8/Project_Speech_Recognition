# ============================================ Nguyen Hien ============================================ 
# Developer: Trần Nguyên Hiền
# Faculty: Electronics and Communication Engineering
# =====================================================================================================
import sounddevice as sd
import queue
import json
import requests
import re
import os
import tempfile
from vosk import Model, KaldiRecognizer
from rapidfuzz import fuzz
from gtts import gTTS
from pydub import AudioSegment
from pydub.playback import play
import time

from Installsubabase import supabase

is_speaking = False

# ========================== Supabase ==========================
def fetch_drinks_from_supabase():
    try:
        response = supabase.table("drinkdata").select("drink_name").execute()
        return [item['drink_name'].lower() for item in response.data if 'drink_name' in item]
    except Exception as e:
        print("Error fetching drinks:", e)
        return []

def fetch_components_from_supabase():
    try:
        response = supabase.table("drinkdata").select("drink_name,ingredients").execute()
        comp_dict = {}
        for item in response.data:
            name = item.get("drink_name", "").lower()
            ing = item.get("ingredients", [])
            if name and isinstance(ing, list):
                comp_dict[name] = [i.lower() for i in ing]
        return comp_dict
    except Exception as e:
        print("Error fetching ingredients:", e)
        return {}

def update_drink_keywords(drink_list):
    keywords["Drink"] = {normalize_text(drink): [normalize_text(drink)] for drink in drink_list}

# ========================== TTS ==========================
def speak(text):
    global is_speaking
    if not text.strip(): return
    is_speaking = True
    tts = gTTS(text=text, lang='en')
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
        tts.save(fp.name)
        play(AudioSegment.from_mp3(fp.name))
    os.unlink(fp.name)
    time.sleep(0.3)
    is_speaking = False

# ========================== JSON POST ==========================
SERVER_URL = "http://your-server-url-here"
def send_order_to_server(order_data):
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(SERVER_URL, json=order_data, headers=headers)
        print("Server response:", response.status_code, response.text)
    except Exception as e:
        print("Failed to send order:", e)

# ========================== Vosk Setup ==========================
model_en = Model("vosk-model-small-en-us-0.15")
q = queue.Queue()
device_info = sd.query_devices(sd.default.device[0], 'input')
samplerate = int(device_info['default_samplerate'])
rec = KaldiRecognizer(model_en, samplerate)
rec.SetWords(True)

def callback(indata, frames, time_, status):
    if status:
        print("Audio status:", status)
    if not is_speaking:
        q.put(bytes(indata))

def normalize_text(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()

# ========================== Keywords ==========================
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

def detect_best_match(text, category, threshold=80):
    best = {"score": 0, "label": None}
    for label, kws in keywords[category].items():
        for kw in kws:
            score = fuzz.partial_ratio(text, kw)
            if score > best["score"]:
                best.update({"score": score, "label": label})
    return best["label"] if best["score"] >= threshold else None

def reset_state():
    global selected_drink, selected_size, component_sizes
    global customizing, current_component_index
    global step, waiting_confirmation, pending_value, pending_category
    selected_drink = None
    selected_size = None
    component_sizes.clear()
    customizing = False
    current_component_index = 0
    step = 1
    waiting_confirmation = False
    pending_value = None
    pending_category = None

def contains_trigger_word(text):
    return "continue" in text.lower() or "autobarista" in text.lower()

# ========================== MAIN ==========================
drink_names = fetch_drinks_from_supabase()
update_drink_keywords(drink_names)
components = fetch_components_from_supabase()

selected_drink = None
selected_size = None
customizing = False
component_sizes = {}
current_component_index = 0

step = 1
waiting_confirmation = False
pending_value = None
pending_category = None
listening_for_trigger = True

print(f"Listening... Sample Rate: {samplerate}")

with sd.RawInputStream(samplerate=samplerate, blocksize=4000, dtype='int16', channels=1, callback=callback):
    while True:
        data = q.get()
        if rec.AcceptWaveform(data):
            text = normalize_text(json.loads(rec.Result()).get("text", ""))
            print(f"Recognized: {text}")
            if is_speaking or not text:
                continue

            if listening_for_trigger:
                if contains_trigger_word(text):
                    speak("Yes, I'm here. What would you like to drink?")
                    listening_for_trigger = False
                    step = 1
                else:
                    continue
                continue

            if waiting_confirmation:
                answer = detect_best_match(text, "YesNo")
                if answer == "Yes":
                    if pending_category == "Drink":
                        selected_drink = pending_value
                        speak(f"You chose {selected_drink}. Do you want to customize ingredients?")
                        waiting_confirmation = True
                        pending_category = "Customize"
                    elif pending_category == "Customize":
                        if selected_drink in components:
                            customizing = True
                            component_sizes = {}
                            current_component_index = 0
                            speak(f"What size for {components[selected_drink][current_component_index]}?")
                            step = 3
                        else:
                            speak("This drink cannot be customized. What size do you want?")
                            step = 2
                        waiting_confirmation = False
                    elif pending_category == "Size":
                        selected_size = pending_value
                        speak(f"You chose size {selected_size}.")
                        send_order_to_server({
                            "selected_drink": selected_drink,
                            "selected_size": selected_size
                        })
                        speak("Order successful!")
                        reset_state()
                        listening_for_trigger = True
                        speak("Say Autobarista to order again.")
                    elif pending_category == "ComponentSize":
                        comp = components[selected_drink][current_component_index]
                        component_sizes[comp] = pending_value
                        current_component_index += 1
                        if current_component_index < len(components[selected_drink]):
                            speak(f"What size for {components[selected_drink][current_component_index]}?")
                        else:
                            summary = ", ".join([f"{k}: size {v}" for k, v in component_sizes.items()])
                            speak(f"Order: {selected_drink} with {summary}")
                            send_order_to_server({
                                "selected_drink": selected_drink,
                                "customized_sizes": component_sizes
                            })
                            speak("Order successful!")
                            reset_state()
                            listening_for_trigger = True
                            speak("Say Autobarista to order again.")
                        waiting_confirmation = False
                elif answer == "No":
                    speak("Okay, please say it again.")
                    step = 1 if pending_category == "Drink" else step
                    waiting_confirmation = False
                else:
                    speak("Please say yes or no.")
                continue

            if step == 1:
                drink = detect_best_match(text, "Drink")
                if drink:
                    speak(f"Did you mean {drink}? Please say yes or no.")
                    pending_value = drink
                    pending_category = "Drink"
                    waiting_confirmation = True
                else:
                    speak("Sorry, I didn’t catch the drink name.")

            elif step == 2:
                size = detect_best_match(text, "Size")
                if size:
                    speak(f"Did you mean size {size}? Please say yes or no.")
                    pending_value = size
                    pending_category = "Size"
                    waiting_confirmation = True
                else:
                    speak("Sorry, I didn’t catch the size.")

            elif step == 3:
                size = detect_best_match(text, "Size")
                if size:
                    comp = components[selected_drink][current_component_index]
                    speak(f"Did you mean size {size} for {comp}? Please say yes or no.")
                    pending_value = size
                    pending_category = "ComponentSize"
                    waiting_confirmation = True
                else:
                    speak("Sorry, please say size again.")
