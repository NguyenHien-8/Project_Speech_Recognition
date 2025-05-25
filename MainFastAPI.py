from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import threading
import uvicorn
from Http_Speech_VoskAPI import run_voice_order_system 

app = FastAPI(title="Voice Ordering System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def start_background_voice():
    thread = threading.Thread(target=run_voice_order_system, daemon=True)
    thread.start()
    print("Voice ordering system started in background.")

@app.get("/")
def root():
    return {"message": "Voice ordering system is running!"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)