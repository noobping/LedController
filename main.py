from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
import logging
import socket
import requests
import uvicorn
import time
import os
import glob
import cv2 as cv
import numpy as np
import concurrent.futures
from threading import Thread
from typing import List, Tuple


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# --------------------------------------------------------------------------------
#                         WLED & VIDEO CONFIGURATION
# --------------------------------------------------------------------------------

# Controller details
WLED_IPS = [
    "192.168.107.123",  # Top Left
    "192.168.107.122",  # Top Right
    "192.168.107.120",  # Bottom Right
    "192.168.107.121",  # Bottom Left
]
PORT = 19446

LEDS_PER_CONTROLLER = 100
WINDOWS_PER_CONTROLLER = 5
LEDS_PER_WINDOW = LEDS_PER_CONTROLLER // WINDOWS_PER_CONTROLLER  # 20
TOTAL_CONTROLLERS = len(WLED_IPS)
TOTAL_LEDS = LEDS_PER_CONTROLLER * TOTAL_CONTROLLERS  # 400

stopVideo = False
video_thread = None


# --------------------------------------------------------------------------------
#                           LOW-LEVEL LED LOGIC
# --------------------------------------------------------------------------------

def build_packet(colors: List[Tuple[int, int, int]]) -> bytes:
    """
    Builds the DRGB packet (no header, just RGB bytes).
    Reverses color order first, matching your code snippet.
    """
    reversed_colors = colors[::-1]
    packet = bytearray()
    for (r, g, b) in reversed_colors:
        packet += bytes([r, g, b])
    return packet


def send_packet(ip: str, port: int, packet: bytes) -> None:
    """
    Sends a UDP packet to a specific WLED controller.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(packet, (ip, port))
        sock.close()
    except Exception as e:
        logging.error(f"Failed to send packet to {ip}:{port} => {e}")


def send_frames(colors: List[Tuple[int, int, int]]) -> None:
    """
    Slices the color array for each controller and sends in parallel.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=TOTAL_CONTROLLERS) as executor:
        for idx, ip in enumerate(WLED_IPS):
            start_idx = idx * LEDS_PER_CONTROLLER
            end_idx = start_idx + LEDS_PER_CONTROLLER
            controller_slice = colors[start_idx:end_idx]
            packet = build_packet(controller_slice)
            executor.submit(send_packet, ip, PORT, packet)


# --------------------------------------------------------------------------------
#                         PIANO LOGIC (VIA WEBSOCKET)
# --------------------------------------------------------------------------------

def handle_piano(controller_idx: int, window_idx: int):
    """
    Lights up exactly one window (20 LEDs) in white for a given controller+window.
    All other LEDs are off (black).
    """
    if not (0 <= controller_idx < TOTAL_CONTROLLERS):
        logging.error(f"Invalid controller index: {controller_idx}")
        return
    if not (0 <= window_idx < WINDOWS_PER_CONTROLLER):
        logging.error(f"Invalid window index: {window_idx}")
        return

    # Start with all LEDs off
    colors = [(0, 0, 0)] * TOTAL_LEDS

    # Calculate the slice of LEDs corresponding to this window
    start_led = window_idx * LEDS_PER_WINDOW
    end_led = start_led + LEDS_PER_WINDOW

    absolute_start = controller_idx * LEDS_PER_CONTROLLER + start_led
    absolute_end = controller_idx * LEDS_PER_CONTROLLER + end_led

    # Make those 20 LEDs white
    for i in range(absolute_start, absolute_end):
        colors[i] = (255, 255, 255)

    send_frames(colors)


# --------------------------------------------------------------------------------
#                         VIDEO PLAYBACK LOGIC
# --------------------------------------------------------------------------------

def play_video(video_path: str, max_fps: float = None):
    """
    Loops the given video until 'stopVideo' is True.  
    Each frame is resized to 5x4 (grid_cols x grid_rows),  
    then expanded to 400 LEDs and sent to the WLED controllers.
    """
    global stopVideo

    while not stopVideo:
        cap = cv.VideoCapture(video_path)
        if not cap.isOpened():
            logging.error(f"Failed to open video file: {video_path}")
            return

        fps = cap.get(cv.CAP_PROP_FPS)
        if fps == 0:
            fps = 30
        if max_fps and fps > max_fps:
            fps = max_fps
            logging.info(f"FPS capped to {fps}")
        frame_duration = 1.0 / fps

        logging.info(f"Playing video in a loop: {video_path} at {fps:.2f} FPS")

        # 4 rows x 5 columns => 20 windows
        grid_rows = 4
        grid_cols = 5

        while not stopVideo:
            frame_start = time.time()
            ret, frame = cap.read()
            if not ret:
                # End of video => break to restart loop
                break
            if stopVideo:
                logging.info("stopping video playback...")
                break

            # Convert to RGB if needed
            if len(frame.shape) == 2:
                frame = cv.cvtColor(frame, cv.COLOR_GRAY2RGB)
            elif frame.shape[2] == 4:
                frame = cv.cvtColor(frame, cv.COLOR_BGRA2RGB)
            else:
                frame = cv.cvtColor(frame, cv.COLOR_BGR2RGB)

            # Resize to 5x4
            resized_frame = cv.resize(
                frame, (grid_cols, grid_rows), interpolation=cv.INTER_AREA)
            # Flatten and repeat for LEDS_PER_WINDOW
            reshaped_frame = resized_frame.reshape(-1, 3)  # shape => (20, 3)
            full_colors = np.repeat(
                reshaped_frame, LEDS_PER_WINDOW, axis=0).tolist()

            # Ensure exactly 400
            if len(full_colors) < TOTAL_LEDS:
                full_colors += [(0, 0, 0)] * (TOTAL_LEDS - len(full_colors))
            elif len(full_colors) > TOTAL_LEDS:
                full_colors = full_colors[:TOTAL_LEDS]

            send_frames(full_colors)

            # Honor FPS
            elapsed = time.time() - frame_start
            wait_time = frame_duration - elapsed
            if wait_time > 0:
                time.sleep(wait_time)

        cap.release()

    # Clear once stopped
    black = [(0, 0, 0)] * TOTAL_LEDS
    send_frames(black)
    logging.info("Video playback stopped or finished.")


def start_video(video_name: str):
    """
    Kills any existing video thread, starts a new one looping the given video.
    """
    global video_thread, stopVideo

    # If a video is already playing, stop it
    if video_thread and video_thread.is_alive():
        stopVideo = True
        video_thread.join()

    stopVideo = False
    video_path = os.path.join(os.path.dirname(__file__), "videos", video_name)
    video_thread = Thread(target=play_video, args=(video_path,), daemon=True)
    video_thread.start()


def stop_video():
    """Stops the currently-playing video."""
    global stopVideo, video_thread
    stopVideo = True
    if video_thread and video_thread.is_alive():
        video_thread.join()
    video_thread = None


# --------------------------------------------------------------------------------
#                           FASTAPI APPLICATION
# --------------------------------------------------------------------------------

description = """
This API controls WLED-based LED matrices via UDP.  
It provides:
- **Video playback** (looping)  
- **Brightness** control  
- **Piano-like** single-window highlighting  

All commands are sent via either:
- HTTP GET endpoints for brightness, video list, etc.
- WebSocket commands (piano, video, stop, brightness, etc.).
"""

app = FastAPI(
    title="LedControllerAPI",
    summary="API server for controlling WLED lights like a matrix.",
    description=description,
    version="0.4.0",
    contact={
        "name": "Lucrasoft",
        "url": "https://www.lucrasoft.nl/",
        "email": "info@lucrasoft.nl"
    }
)


@app.get("/videolist")
def get_video_list():
    """
    Returns the names (without extension) of all .mp4 files in the /videos folder.
    """
    video_dir = os.path.join(os.path.dirname(__file__), "videos")
    files = glob.glob(os.path.join(video_dir, "*.mp4"))
    return [os.path.splitext(os.path.basename(v))[0] for v in files]


@app.get("/brightness")
def get_brightness():
    """
    Fetches brightness levels from all WLED controllers (by calling their /json endpoint).
    """
    brightness_levels = {}
    for ip in WLED_IPS:
        try:
            resp = requests.get(f"http://{ip}/json")
            if resp.status_code == 200:
                data = resp.json()
                brightness_levels[ip] = data.get(
                    "state", {}).get("bri", "Unknown")
            else:
                brightness_levels[ip] = "Error fetching brightness"
        except Exception as e:
            brightness_levels[ip] = f"Error: {e}"
    return {"brightness": brightness_levels}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket API supports commands:
      - "videolist"
      - "video <videoName>"
      - "stop"
      - "brightness <intValue>"
      - "piano <controller_idx>,<window_idx>"
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()
            parts = data.split(b" ")
            command = parts[0]

            if command == b"videolist":
                # Return list of available mp4 files
                videos = get_video_list()
                await websocket.send_text("videos: " + ", ".join(videos))

            elif command == b"video":
                # Start a looping video
                video_name = parts[1].decode()
                start_video(video_name + ".mp4")

            elif command == b"stop":
                # Stop looping video
                stop_video()

            elif command == b"brightness":
                # Set brightness
                value = int(parts[1])
                set_brightness(value)

            elif command == b"piano":
                # Example: "piano; 0,2"
                coords = parts[1].decode().split(",")
                if len(coords) == 2:
                    controller_idx = int(coords[0])
                    window_idx = int(coords[1])
                    handle_piano(controller_idx, window_idx)
                else:
                    logging.error(
                        "Invalid piano command format. Expected: 'piano; X,Y'")

            else:
                logging.warning(f"Unknown WebSocket command: {
                                command.decode()}")

            # Confirm
            await websocket.send_text("OK.")
    except WebSocketDisconnect:
        pass


def set_brightness(value: int):
    """
    Sets brightness (0-255) on all WLED controllers via /json endpoint.
    """
    payload = {"on": True, "bri": value, "seg": [{"col": [0, 0, 0]}]}
    for ip in WLED_IPS:
        try:
            requests.post(f"http://{ip}/json", json=payload)
        except Exception as e:
            logging.error(f"Failed to set brightness on {ip}: {e}")


# --------------------------------------------------------------------------------
#                          MAIN ENTRY POINT
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=False)
