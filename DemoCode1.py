# ======================================== Nguyen Hien ========================================
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

# ========== GLOBAL STATE ==========
is_speaking = False

# ========== Text-to-Speech ==========
def speak(text):
    global is_speaking
    if not text or text.strip() == "":
        return
    is_speaking = True
    print(f"[TTS]: {text}")
    tts = gTTS(text=text, lang='en')
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
        tts.save(fp.name)
        sound = AudioSegment.from_mp3(fp.name)
        play(sound)
    os.unlink(fp.name)
    time.sleep(0.3)  # Delay để tránh ghi nhận lại sót âm
    is_speaking = False

# ========== Send Order JSON ==========
SERVER_URL = "http://your-server-url-here"
def send_order_to_server(order_data):
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(SERVER_URL, json=order_data, headers=headers)
        print("Server response:", response.status_code, response.text)
    except Exception as e:
        print("Failed to send order to server:", str(e))

# ========== Voice Recognition ==========
model_en = Model("vosk-model-small-en-us-0.15")
q = queue.Queue()

device_info = sd.query_devices(sd.default.device[0], 'input')
samplerate = int(device_info['default_samplerate'])

rec = KaldiRecognizer(model_en, samplerate)
rec.SetWords(True)

def callback(indata, frames, time_, status):
    global is_speaking
    if status:
        print("Audio Error:", status)
    if not is_speaking:
        q.put(bytes(indata))

def normalize_text(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ========== Keywords ==========
keywords = {
    "Drink": {
        "coffee": ["coffee"],
        "milk coffee": ["milk coffee"],
        "milk tea": ["milk tea"],
        "sugar tea": ["sugar tea"]
    },
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

def is_valid_speech(text):
    if not text:
        return False
    words = text.split()
    if len(words) < 1:
        return False
    for category in keywords.values():
        for kw_list in category.values():
            for kw in kw_list:
                if kw in text:
                    return True
    return False

# ================================================ MAIN ===================================================
print(f"Listening... (Sample Rate = {samplerate})")
speak("Hello! What would you like to drink?")
print("Hello! What would you like to drink?")
step = 1
selected_drink = None
selected_size = None
waiting_confirmation = False
pending_value = None
pending_category = None
# === Thêm biến trạng thái ===
customizing = False
current_component_index = 0
component_sizes = {}
components = {
    "coffee": ["coffee", "sugar"],
    "milk coffee": ["milk", "coffee"],
    "milk tea": ["milk", "tea"],
    "sugar tea": ["tea", "sugar"]
}

# === Trong vòng while True ===
with sd.RawInputStream(samplerate=samplerate, blocksize=4000, dtype='int16', channels=1, callback=callback):
    while True:
        data = q.get()
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            text = normalize_text(result.get("text", ""))
            print(f"Detected: {text}")

            if is_speaking or not text or not is_valid_speech(text):
                print("Ignored noise or system playback.")
                continue

            if waiting_confirmation:
                answer = detect_best_match(text, "YesNo")
                if answer == "Yes":
                    if pending_category == "Drink":
                        selected_drink = pending_value
                        speak(f"You chose drink: {selected_drink}. Would you like to customize your drink ingredients?")
                        print(f"You chose drink: {selected_drink}. Would you like to customize your drink ingredients?")
                        pending_category = "Customize"
                        waiting_confirmation = True
                    elif pending_category == "Customize":
                        if selected_drink in components:
                            customizing = True
                            current_component_index = 0
                            component_sizes.clear()
                            speak(f"What size for {components[selected_drink][current_component_index]}?")
                            print(f"What size for {components[selected_drink][current_component_index]}?")
                            step = 3
                        else:
                            speak("This drink cannot be customized. Please choose size.")
                            print("This drink cannot be customized. Please choose size.")
                            step = 2
                        waiting_confirmation = False
                    elif pending_category == "Size":
                        selected_size = pending_value
                        speak(f"You chose size: {selected_size}. Order successful!")
                        speak(f"Confirm: {selected_drink} - size {selected_size}")
                        print(f"Confirm: {selected_drink} - size {selected_size}")
                        order_data = {
                            "selected_drink": selected_drink,
                            "selected_size": selected_size
                        }
                        send_order_to_server(order_data)
                        break
                    elif pending_category == "ComponentSize":
                        comp = components[selected_drink][current_component_index]
                        component_sizes[comp] = pending_value
                        current_component_index += 1
                        if current_component_index < len(components[selected_drink]):
                            next_comp = components[selected_drink][current_component_index]
                            speak(f"What size for {next_comp}?")
                            print(f"What size for {next_comp}?")
                        else:
                            # Đã chọn xong tất cả thành phần
                            final_text = f"Confirm: {selected_drink} with " + \
                                         ", ".join([f"{k} size {v}" for k, v in component_sizes.items()])
                            speak(final_text)
                            speak("Order successful!")
                            print(final_text)
                            order_data = {
                                "selected_drink": selected_drink,
                                "customized_sizes": component_sizes
                            }
                            send_order_to_server(order_data)
                            break
                        waiting_confirmation = False
                elif answer == "No":
                    if pending_category == "Drink":
                        speak("Please say again. What would you like to drink?")
                        print("Please say again. What would you like to drink?")
                        step = 1
                    elif pending_category == "Customize":
                        customizing = False
                        speak("What size do you want?")
                        print("What size do you want?")
                        step = 2
                        waiting_confirmation = False
                    elif pending_category == "Size":
                        speak("Please say size again.")
                        print("Please say size again.")
                        step = 2
                        waiting_confirmation = False
                    elif pending_category == "ComponentSize":
                        comp = components[selected_drink][current_component_index]
                        speak(f"Please say size again for {comp}.")
                        print(f"Please say size again for {comp}.")
                        waiting_confirmation = False
                else:
                    speak("Please say yes or no.")
                    print("Please say yes or no.")
                continue

            if step == 1:
                drink = detect_best_match(text, "Drink")
                if drink:
                    speak(f"Did you mean drink {drink}? Please say yes or no.")
                    print(f"Did you mean drink {drink}? Please say yes or no.")
                    pending_value = drink
                    pending_category = "Drink"
                    waiting_confirmation = True
                else:
                    speak("Sorry I did not recognize the drink. Please try again.")
                    print("Sorry I did not recognize the drink. Please try again.")

            elif step == 2:
                size = detect_best_match(text, "Size")
                if size:
                    speak(f"Did you mean size {size}? Please say yes or no.")
                    print(f"Did you mean size {size}? Please say yes or no.")
                    pending_value = size
                    pending_category = "Size"
                    waiting_confirmation = True
                else:
                    speak("Sorry I did not recognize the size. Please try again.")
                    print("Sorry I did not recognize the size. Please try again.")

            elif step == 3:  # Component customization
                size = detect_best_match(text, "Size")
                if size:
                    comp = components[selected_drink][current_component_index]
                    speak(f"Did you mean size {size} for {comp}? Please say yes or no.")
                    print(f"Did you mean size {size} for {comp}? Please say yes or no.")
                    pending_value = size
                    pending_category = "ComponentSize"
                    waiting_confirmation = True
                else:
                    speak("Sorry I did not recognize the size. Please try again.")
                    print("Sorry I did not recognize the size. Please try again.")