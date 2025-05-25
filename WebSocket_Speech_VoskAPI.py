# ============================================ Nguyen Hien ============================================ 
# Developer: Trần Nguyên Hiền
# Faculty: Electronics and Communication Engineering
# =====================================================================================================
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import threading
import uvicorn
from typing import List
import asyncio

import sounddevice as sd
import queue
import json
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

app = FastAPI(title="Voice Ordering System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
active_websockets: List[WebSocket] = []
is_speaking = False
latest_order = None
drink_prices = {}
# ============= From Supabase Import Drink and Ingredient =============
def fetch_drinks_from_supabase():
    try:
        response = supabase.table("drinkdata").select("drink_name,price").execute()
        drink_list = []
        for item in response.data:
            name = item.get('drink_name', '').lower()
            price = item.get('price', 0)
            if name:
                drink_list.append({"name": name, "price": price})
        return drink_list
    except Exception as e:
        print("Error fetching drinks from Supabase:", str(e))
        return []

def fetch_components_from_supabase():
    try:
        response = supabase.table("drinkdata").select("drink_name,ingredients").execute()
        comp_dict = {}
        for item in response.data:
            name = item.get("drink_name", "").lower()
            ing = item.get("ingredients", "")
            if name and isinstance(ing, str):
                ing = ing.strip("{}") 
                comp_dict[name] = [i.strip().lower() for i in ing.split(",") if i.strip()]
        return comp_dict
    except Exception as e:
        print("Error fetching ingredients from Supabase:", str(e))
        return {}

def update_drink_keywords(drink_data):
    keywords["Drink"] = {}
    for item in drink_data:
        name = item["name"]
        price = item["price"]
        clean_name = normalize_text(name)
        keywords["Drink"][clean_name] = [clean_name]
        drink_prices[clean_name] = price

# ========================== Text-To-Speech ===========================
def speak(text):
    global is_speaking
    if not text.strip():
        return
    is_speaking = True
    print(f"[TTS]: {text}")
    tts = gTTS(text=text, lang='en')
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
        tts.save(fp.name)
        sound = AudioSegment.from_mp3(fp.name)
        play(sound)
    os.unlink(fp.name)
    time.sleep(0.3)
    is_speaking = False

# ========================= Voice Recognition =========================
q = queue.Queue()
model_en = Model("vosk-model-small-en-us-0.15")
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

# ============================= Keywords =============================
keywords = {
    "Drink": {},
    "Size": {
        "S": ["size s", "size small", "small"],
        "M": ["size m", "size medium", "medium"],
        "L": ["size l", "size large", "large"]
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
    if "continue" in text:
        return True
    for category in keywords.values():
        for kw_list in category.values():
            for kw in kw_list:
                if kw in text:
                    return True
    return False

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

# ============ Initialize Keywords And Data ============
drink_data = fetch_drinks_from_supabase()
update_drink_keywords(drink_data)
components = fetch_components_from_supabase()

print("Updated drink keywords:", keywords["Drink"])
print("Updated components from Supabase:", components)

# ============= MAIN VOICE ORDER FUNCTION ==============
def Voice_Ordering_System():
    global step, selected_drink, selected_size
    global waiting_confirmation, pending_value, pending_category
    global customizing, current_component_index, component_sizes
    global listening_for_trigger, latest_order

    trigger_keywords = ["continue", "go on", "carry on", "can you", "ok", "start", "autobarista"]
    print(f"Listening... (Sample Rate = {samplerate})")

    step = 1
    selected_drink = None
    selected_size = None
    waiting_confirmation = False
    pending_value = None
    pending_category = None
    customizing = False
    current_component_index = 0
    component_sizes = {}
    listening_for_trigger = True
    latest_order = None

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

                if listening_for_trigger:
                    if text.startswith("autobarista") or any(kw in text for kw in trigger_keywords):
                        asyncio.run(broadcast_to_clients({"type": "start"}))
                        speak("Yes, I'm here. What would you like to drink?")
                        print("Yes, I'm here. What would you like to drink?")
                        listening_for_trigger = False
                        step = 1
                    else:
                        print("Waiting for trigger word...")
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
                                comp = components[selected_drink][current_component_index]
                                speak(f"What size for {comp}?")
                                print(f"What size for {comp}?")
                                step = 3
                            else:
                                speak("This drink cannot be customized. Please choose size.")
                                print("This drink cannot be customized. Please choose size.")
                                step = 2
                            waiting_confirmation = False
                        elif pending_category == "Size":
                            selected_size = pending_value
                            price = drink_prices.get(selected_drink, "unknown")
                            speak(f"You chose size: {selected_size}. The price is {price} vnd. Order successful!")
                            speak(f"Confirm: {selected_drink} - size {selected_size}")
                            latest_order = {
                                "price": price,
                                "drink": selected_drink,
                                "size": selected_size
                            }
                            asyncio.run(broadcast_to_clients({
                               "type": "voiceOrderResult",
                               "data": latest_order
                            }))
                            reset_state()
                            listening_for_trigger = True
                            speak("If you want to order again, just say Autobarista.")
                            print("If you want to order again, just say Autobarista.")
                        elif pending_category == "ComponentSize":
                            comp = components[selected_drink][current_component_index]
                            component_sizes[comp] = pending_value
                            current_component_index += 1
                            if current_component_index < len(components[selected_drink]):
                                next_comp = components[selected_drink][current_component_index]
                                speak(f"What size for {next_comp}?")
                                print(f"What size for {next_comp}?")
                            else:
                                price = drink_prices.get(selected_drink, "unknown")
                                final_text = f"Confirm: {selected_drink} with " + \
                                             ", ".join([f"{k} size {v}" for k, v in component_sizes.items()])
                                speak(final_text)
                                speak(f"The price is {price} vnd. Order successful!")
                                latest_order = {
                                    "drink": selected_drink,
                                    "details": {
                                        "price": price,
                                        **component_sizes.copy(),
                                    }
                                }
                                asyncio.run(broadcast_to_clients({
                                    "type": "voiceOrderResult",
                                    "data": latest_order
                                }))
                                reset_state()
                                listening_for_trigger = True
                                speak("If you want to order again, just say Autobarista.")
                                print("If you want to order again, just say Autobarista.")
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

                elif step == 3:
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

# ======================== WEBSOCKET ========================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()  
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
        print("Client disconnected")

async def broadcast_to_clients(message: dict):
    for ws in active_websockets:
        try:
            await ws.send_json(message)
        except Exception as e:
            print("WebSocket Send Error:", e)

@app.on_event("startup")
def start_background_thread():
    thread = threading.Thread(target=Voice_Ordering_System, daemon=True)
    thread.start()
    print("Voice System Started In Background.")

if __name__ == "__main__":
    uvicorn.run("WebSocket_Speech_VoskAPI:app", host="0.0.0.0", port=8086, reload=False)

