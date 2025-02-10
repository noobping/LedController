from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from threading import Thread
from typing import List, Tuple
import asyncio
import concurrent.futures
import cv2 as cv
import glob
import httpx
import json
import logging
import numpy as np
import os
import requests
import socket
import time
import uvicorn

# List to keep track of connected WebSocket clients
connected_websockets: List[WebSocket] = []

# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

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

# --------------------------------------------------------------------------------
#                           LOW-LEVEL LED LOGIC
# --------------------------------------------------------------------------------


def build_packet(colors: List[Tuple[int, int, int]]) -> bytes:
    """
    Builds the DRGB packet (no header, just RGB bytes).
    Reverses color order first, matching your code snippet.

    Args:
        colors (List[Tuple[int, int, int]]): List of (R, G, B) tuples for all LEDs.
    """
    reversed_colors = colors[::-1]
    packet = bytearray()
    for (r, g, b) in reversed_colors:
        packet += bytes([r, g, b])
    return packet


def send_packet(ip: str, port: int, packet: bytes) -> None:
    """
    Sends a UDP packet to a specific WLED controller.

    Args:
        ip (str): IP address of the WLED controller.
        port (int): UDP port of the WLED controller.
        packet (bytes): DRGB packet to send to the controller.
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

    Args:
        colors (List[Tuple[int, int, int]]): List of (R, G, B) tuples for all LEDs.
    """
    logging.debug(f"Sending {len(colors)} colors to {TOTAL_CONTROLLERS} controllers. Collors: {colors}")
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

    Args:
        controller_idx (int): Index of the WLED controller (0-1).
        window_idx (int): Index of the window (0-WINDOWS_PER_CONTROLLER) on the controller.
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


stopVideo = False
video_thread = None


def play_video(video_path: str, max_fps: float = None):
    """
    Loops the given video until 'stopVideo' is True.
    Each frame is resized to 5x4 (grid_cols x grid_rows),
    then expanded to 400 LEDs and sent to the WLED controllers.

    Args:
        video_path (str): Path to the video file.
        max_fps (float): Maximum FPS to cap the video playback.
    """
    global stopVideo

    while not stopVideo:
        cap = cv.VideoCapture(video_path)
        if not cap.isOpened():
            logging.error(f"Failed to open video file: {video_path}")
            return

        fps = cap.get(cv.CAP_PROP_FPS) or 30
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
            reshaped_frame = resized_frame.reshape(-1, 3)
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

    Args:
        video_name (str): Name of the video file (without extension).
    """
    global video_thread, stopVideo

    # If a video is already playing, stop it
    if video_thread and video_thread.is_alive():
        stopVideo = True
        video_thread.join(timeout=5)

    stopVideo = False
    video_path = os.path.join(os.path.dirname(__file__), "videos", video_name)
    video_thread = Thread(target=play_video, args=(video_path,), daemon=True)
    video_thread.start()

# --------------------------------------------------------------------------------
#                           CHRISTMAS ANIMATION LOGIC
# --------------------------------------------------------------------------------


stopChristmas = False
christmas_thread = None


def make_christmas_frame(enabled: bool = True) -> List[Tuple[int, int, int]]:
    """
    Create a fixed red-green pattern with blocks of 20 LEDs each.

    Args:
        enabled (bool): If True, start with red blocks; otherwise, start with green.

    Returns:
        List[Tuple[int, int, int]]: A list of (R, G, B) tuples with red and green colors.
    """
    colors = []
    for i in range(TOTAL_LEDS):
        block = i // LEDS_PER_WINDOW
        if enabled:
            # Even block => Red, Odd => Green
            if block % 2 == 0:
                colors.append((255, 0, 0))
            else:
                colors.append((0, 255, 0))
        else:
            # Even => Green, Odd => Red
            if block % 2 == 0:
                colors.append((0, 255, 0))
            else:
                colors.append((255, 0, 0))
    return colors


def run_christmas_animation():
    """
    Toggles every 5 seconds between two frames (red/green swapped).
    """
    global stopChristmas
    logging.info(
        "Starting Christmas animation with 0.1s sends, switching frames every 5s.")
    enabled = True

    while not stopChristmas:
        block_start = time.monotonic()
        while (time.monotonic() - block_start < 5) and not stopChristmas:
            colors = make_christmas_frame(enabled)
            send_frames(colors)
            time.sleep(0.1)
        if not stopChristmas:
            enabled = not enabled
            logging.info(f"Switched to {'Red' if enabled else 'Green'} frame.")


def start_christmas():
    """
    Starts the Christmas animation in a new thread.
    """
    global christmas_thread, stopChristmas
    stop_animation()

    stopChristmas = False
    christmas_thread = Thread(target=run_christmas_animation, daemon=True)
    christmas_thread.start()
    logging.info("Christmas animation thread started.")


# --------------------------------------------------------------------------------
#                      LEGACY FUNCTIONS & GLOBALS
# --------------------------------------------------------------------------------

# Convert a 6-digit hex string (e.g. "ff8040") to (R, G, B)
def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


# Global variable holding the current legacy frame (default black)
current_legacy_frame: List[Tuple[int, int, int]] = [(0, 0, 0)] * TOTAL_LEDS

# Globals for the legacy sender thread and its stop flag
stopLegacy = False
legacy_thread = None


def run_legacy_animation():
    """
    Continuously sends the current legacy frame every 0.25 seconds until stopLegacy is True.
    """
    global stopLegacy
    while not stopLegacy:
        send_frames(current_legacy_frame)
        logging.debug(f"Update legacy frame")
        time.sleep(0.25)


def start_legacy_sender():
    """
    Starts the legacy sender thread if it is not already running.
    """
    global video_thread, stopVideo, christmas_thread, stopChristmas
    if video_thread and video_thread.is_alive():
        logging.info("Stopping video playback.")
        stopVideo = True
        video_thread.join(timeout=5)
        video_thread = None

    if christmas_thread and christmas_thread.is_alive():
        logging.info("Stopping Christmas animation.")
        stopChristmas = True
        christmas_thread.join(timeout=5)
        christmas_thread = None

    global legacy_thread, stopLegacy
    if legacy_thread is None or not legacy_thread.is_alive():
        stopLegacy = False
        legacy_thread = Thread(target=run_legacy_animation, daemon=True)
        legacy_thread.start()
        logging.info("Legacy sender thread started.")


def make_setall_frame(color: str) -> List[Tuple[int, int, int]]:
    """
    Creates a legacy frame where every LED is set to the same color.

    Args:
        color (str): A 6-digit hex string (e.g. "ff8040").

    Returns:
        List[Tuple[int, int, int]]: A list of TOTAL_LEDS copies of the RGB tuple.
    """
    rgb = hex_to_rgb(color)
    return [rgb] * TOTAL_LEDS


def setAllColors(color: str) -> None:
    """
    Legacy command to set all LEDs to the given color.
    This function stops any current animations and updates the global legacy frame.

    Args:
        color (str): A 6-digit hex string (e.g. "ff8040").
    """
    global current_legacy_frame
    # Create a frame where every LED is the same color.
    frame = make_setall_frame(color)
    current_legacy_frame = frame
    logging.info(f"Legacy: Set all colors to #{color}")


def update_matrix_legacy(colors: List[str]) -> None:
    """
    Legacy command to update the entire LED matrix.

    Args:
        colors (List[str]): A list of 6-digit hex strings, one per LED.

    Raises:
        ValueError: if the list length does not match TOTAL_LEDS.
    """
    if len(colors) != TOTAL_LEDS:
        raise ValueError(f"Expected {TOTAL_LEDS} colors but got {len(colors)}")
    global current_legacy_frame
    # Convert each hex string to an RGB tuple.
    current_legacy_frame = [hex_to_rgb(c) for c in colors]
    logging.info("Legacy: Full matrix update performed.")


def update_differences(diff_list: List[List[str]]) -> None:
    """
    Legacy command to update individual LED colors by index.

    Args:
        diff_list (List[List[str]]): A list of [index, hex_color] pairs. 
          For example: [["23", "ff8040"], ["45", "00ff00"]]

    This function updates the global legacy frame in-place.
    """
    global current_legacy_frame
    for diff in diff_list:
        try:
            idx = int(diff[0])
            if not (0 <= idx < TOTAL_LEDS):
                logging.error(f"Legacy: Index {idx} out of bounds.")
                continue
            new_color = hex_to_rgb(diff[1])
            current_legacy_frame[idx] = new_color
            logging.debug(f"Legacy: Updated LED {idx} to #{diff[1]}")
        except Exception as e:
            logging.error(f"Legacy: Error updating difference {diff}: {e}")


# --------------------------------------------------------------------------------
#                           STOP ANIMATION LOGIC
# --------------------------------------------------------------------------------


def stop_animation():
    """
    Stops any ongoing animations, including video playback and Christmas animation.
    """
    global stopVideo, video_thread, stopChristmas, christmas_thread, stopLegacy, legacy_thread
    logging.info("Stopping all ongoing animations.")

    # Stop legacy sender
    if legacy_thread and legacy_thread.is_alive():
        logging.info("Stopping legacy sender.")
        stopLegacy = True
        legacy_thread.join(timeout=5)
        legacy_thread = None

    # Stop video
    if video_thread and video_thread.is_alive():
        logging.info("Stopping video playback.")
        stopVideo = True
        video_thread.join(timeout=5)
        video_thread = None

    # Stop Christmas
    if christmas_thread and christmas_thread.is_alive():
        logging.info("Stopping Christmas animation.")
        stopChristmas = True
        christmas_thread.join(timeout=5)
        christmas_thread = None

    # Clear LEDs after stopping
    black = [(0, 0, 0)] * TOTAL_LEDS
    send_frames(black)
    logging.info("All animations have been stopped and LEDs cleared.")

# --------------------------------------------------------------------------------
#                          FASTAPI APPLICATION
# --------------------------------------------------------------------------------


description = """
This API controls WLED-based LED matrices via UDP.  
It provides:
- **Video playback**  
- **Brightness** control  
- **Piano** single-window highlights  
- **Christmas** animation  
- **(Legacy) 'setall', 'update', 'difference'** WebSocket commands for backward compatibility.
"""

app = FastAPI(
    title="LedControllerAPI",
    summary="API server for controlling WLED lights like a matrix.",
    description=description,
    version="0.5.0",
    contact={
        "name": "Lucrasoft",
        "url": "https://www.lucrasoft.nl/",
        "email": "info@lucrasoft.nl"
    }
)


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    """
    Return index.html for the root path.
    """
    file_path = os.path.join("static", "index.html")
    return FileResponse(file_path)


@app.get("/health")
async def health_check():
    """
    Health check endpoint to verify if the WLED controllers are reachable.
    """
    health_status = {}
    async with httpx.AsyncClient() as client:
        tasks = [client.get(f"http://{ip}/json") for ip in WLED_IPS]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for ip, resp in zip(WLED_IPS, responses):
            if isinstance(resp, Exception):
                health_status[ip] = f"Error: {resp}"
            elif resp.status_code == 200:
                health_status[ip] = "OK"
            else:
                health_status[ip] = "Error"
    return health_status


@app.get("/info")
async def about():
    """
    Returns information about the API and its capabilities.
    """
    current_health = await health_check()
    return {
        "about": "This API controls WLED-based LED matrices via UDP.",
        "animation": {
            "video": bool(video_thread and video_thread.is_alive()),
            "christmas": bool(christmas_thread and christmas_thread.is_alive())
        },
        "connected_websockets": len(connected_websockets),
        "info": {
            "controllers": {
                "total": TOTAL_CONTROLLERS,
                "ips": current_health,
                "port": PORT,
                "windows_per_controller": WINDOWS_PER_CONTROLLER
            },
            "leds": {
                "total": TOTAL_LEDS,
                "per_controller": LEDS_PER_CONTROLLER,
                "per_window": LEDS_PER_WINDOW
            }
        }
    }


@app.post("/christmas")
def christmas_endpoint():
    """ Starts Christmas animation. """
    start_christmas()
    return {"message": "Christmas animation started."}


@app.post("/piano/{controller_idx}/{window_idx}")
def piano_endpoint(controller_idx: int, window_idx: int):
    """
    Lights up exactly one window (20 LEDs) in white for a given controller+window.
    All other LEDs are off (black).

    Args:
        controller_idx (int): Index of the WLED controller (0-1).
        window_idx (int): Index of the window (0-WINDOWS_PER_CONTROLLER) on the controller.
    """
    if not (0 <= controller_idx < TOTAL_CONTROLLERS):
        raise HTTPException(
            status_code=400, detail="Invalid controller index."
        )
    if not (0 <= window_idx < WINDOWS_PER_CONTROLLER):
        raise HTTPException(
            status_code=400, detail="Invalid window index."
        )

    handle_piano(controller_idx, window_idx)
    return {"message": f"Piano window {window_idx} on controller {controller_idx} activated."}


@app.get("/video")
def get_video_list():
    """
    Returns names (without extension) of all .mp4 files in the /videos folder.
    """
    video_dir = os.path.join(os.path.dirname(__file__), "videos")
    files = glob.glob(os.path.join(video_dir, "*.mp4"))
    return [os.path.splitext(os.path.basename(v))[0] for v in files]


@app.post("/video/{video_name}")
def start_video_endpoint(video_name: str):
    """
    Starts looping the given video file (by name, no extension needed).

    Args:
        video_name (str): Name of the video file (without extension).
    """
    if not video_name:
        raise HTTPException(status_code=400, detail="Missing video name.")

    stop_animation()
    start_video(video_name + ".mp4")
    return {"message": "Video playback started."}


@app.delete("/christmas")
@app.delete("/piano")
@app.delete("/video")
@app.delete("/video/{video_name}")
def stop_video_endpoint(video_name: str = None):
    """
    Stops any ongoing animation (video or Christmas).
    """
    stop_animation()
    return {"message": "Animations stopped."}


@app.post("/brightness/{value}")
def set_brightness_endpoint(value: int):
    """
    Sets brightness (0-255) on all WLED controllers.

    Args:
        value (int): Brightness value between 0 and 255.
    """
    if not (0 <= value <= 255):
        raise HTTPException(
            status_code=400, detail="Brightness must be 0..255.")
    set_brightness(value)
    return {"message": f"Brightness set to {value}."}


@app.get("/brightness")
async def get_brightness():
    """
    Fetches brightness levels from all WLED controllers.
    """
    brightness_levels = {}
    async with httpx.AsyncClient() as client:
        tasks = [client.get(f"http://{ip}/json") for ip in WLED_IPS]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for ip, resp in zip(WLED_IPS, responses):
            if isinstance(resp, Exception):
                brightness_levels[ip] = f"Error: {resp}"
            elif resp.status_code == 200:
                data = resp.json()
                brightness_levels[ip] = data.get("state", {}).get("bri", "Unknown")
            else:
                brightness_levels[ip] = "Error fetching brightness"
    return {"brightness": brightness_levels}

# =============================================================================
#  Legacy API handler (byte-based commands)
# =============================================================================


async def ws_legacy_api(websocket: WebSocket, data: bytes) -> None:
    """
    Process legacy API commands sent as bytes.
    Expected format (example): b"update; <data>" or b"setall; <data>"
    """
    try:
        # Split the incoming data on the first occurrence of b"; "
        parts = data.split(b"; ", 1)
        if len(parts) != 2:
            await websocket.send_text("Error: Invalid command format (missing separator).")
            return

        command = parts[0].strip()
        payload = parts[1].strip()

        if command == b"setall":
            # Expect payload: a 6-character hex string (e.g. "ff8040")
            color_str = payload.decode()
            if len(color_str) != 6:
                await websocket.send_text("Error: Color must be a 6-digit hex string.")
                return
            setAllColors(color_str)
            start_legacy_sender()

        elif command == b"update":
            # Expect payload: a comma‐separated list of hex strings
            colors = payload.split(b", ")
            if len(colors) != TOTAL_LEDS:
                await websocket.send_text(f"Error: Expected {TOTAL_LEDS} colors but got {len(colors)}.")
                return
            # Convert each byte string to a regular string (hex color)
            color_list = [c.decode() for c in colors]
            update_matrix_legacy(color_list)
            start_legacy_sender()

        elif command == b"difference":
            # Expect payload: comma–separated pairs; for example:
            # b"(23, ff8040), (45, 00ff00), ..."
            # For simplicity, we assume that the payload is formatted as:
            # b"23, ff8040, 45, 00ff00" (i.e. pairs separated by comma and space)
            parts = payload.split(b", ")
            if len(parts) % 2 != 0:
                await websocket.send_text("Error: Difference command data malformed (odd number of items).")
                return
            diff_list = []
            for i in range(0, len(parts), 2):
                index = parts[i].decode().strip("()")
                color = parts[i+1].decode().strip("()")
                diff_list.append([index, color])
            update_differences(diff_list)
            start_legacy_sender()

        elif command == b"videolist":
            videos = get_video_list()
            await websocket.send_text("videos: " + ", ".join(videos))
            return

        elif command == b"video":
            video_name = payload.decode().strip()
            if not video_name:
                await websocket.send_text("Error: Missing video name.")
                return
            # In your legacy implementation you might need to add the extension.
            start_video(video_name)

        elif command == b"stop":
            stop_animation()

        elif command == b"brightness":
            try:
                brightness_value = int(payload.decode())
            except ValueError:
                await websocket.send_text("Error: Brightness must be an integer.")
                return
            set_brightness(brightness_value)

        else:
            logging.warning("Unknown legacy command: " + command.decode())
            await websocket.send_text("Unknown legacy command.")
            return

        # Acknowledge command processing.
        await websocket.send_text("OK.")

    except Exception as e:
        logging.error(f"Error processing legacy command: {e}")
        await websocket.send_text("Error processing legacy command.")

# =============================================================================
#  JSON API handler
# =============================================================================


async def ws_json_api(websocket: WebSocket, data: str) -> None:
    """
    Process JSON API commands sent as text.
    Expected JSON format: {"command": "setall", "data": ...}
    """
    try:
        msg = json.loads(data)
    except json.JSONDecodeError:
        await websocket.send_text(json.dumps({"error": "Invalid JSON"}))
        return

    command = msg.get("command", "").lower()
    data_field = msg.get("data")

    if command == "videolist":
        videos = get_video_list()
        await websocket.send_text(json.dumps({"videos": videos}))

    elif command == "video":
        if data_field is None or str(data_field).strip() == "":
            await websocket.send_text(json.dumps({"error": "Missing video name"}))
        else:
            video_name = str(data_field).strip()
            stop_animation()
            start_video(video_name)
            await websocket.send_text(json.dumps({"status": "Video playback started"}))

    elif command == "stop":
        stop_animation()
        await websocket.send_text(json.dumps({"status": "All animations stopped"}))

    elif command == "brightness":
        try:
            brightness_value = int(data_field)
            set_brightness(brightness_value)
            await websocket.send_text(json.dumps({"status": f"Brightness set to {brightness_value}"}))
        except (ValueError, TypeError):
            await websocket.send_text(json.dumps({"error": "Brightness value must be an integer"}))

    elif command == "piano":
        if not (isinstance(data_field, dict) and "controller" in data_field and "window" in data_field):
            await websocket.send_text(json.dumps({
                "error": "Invalid piano command format. Use: {\"controller\": x, \"window\": y}"
            }))
        else:
            try:
                controller_idx = int(data_field["controller"])
                window_idx = int(data_field["window"])
                handle_piano(controller_idx, window_idx)
                await websocket.send_text(json.dumps({
                    "status": f"Piano window {window_idx} on controller {controller_idx} activated"
                }))
            except ValueError:
                await websocket.send_text(json.dumps({"error": "Piano coordinates must be integers"}))

    elif command == "christmas":
        start_christmas()
        await websocket.send_text(json.dumps({"status": "Christmas animation started"}))

    else:
        logging.warning(f"Unknown JSON command: {command}")
        await websocket.send_text(json.dumps({"error": "Unknown command"}))

# =============================================================================
#  Main WebSocket endpoint: supports both legacy (bytes) and JSON (text) messages
# =============================================================================

@app.websocket("/ws")
async def ws_main(websocket: WebSocket):
    """
    The unified WebSocket endpoint that accepts both legacy byte messages and
    JSON messages.

    If a received message contains bytes then it is dispatched to the legacy API handler.
    If a text message is received, it is assumed to be JSON and is dispatched accordingly.
    """
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive()
            # Check if we got a bytes message (legacy) or text (JSON)
            if "bytes" in message and message["bytes"] is not None:
                await ws_legacy_api(websocket, message["bytes"])
            elif "text" in message and message["text"] is not None:
                await ws_json_api(websocket, message["text"])
            else:
                await websocket.send_text("Error: Invalid message format.")
    except WebSocketDisconnect:
        logging.info("WebSocket disconnected in ws_main.")

# =============================================================================
#  Separate endpoints for legacy and JSON clients
# =============================================================================


@app.websocket("/ws/v1")
async def ws_legacy_endpoint(websocket: WebSocket):
    """
    A dedicated endpoint for legacy clients that send raw bytes.
    """
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"] is not None:
                await ws_legacy_api(websocket, message["bytes"])
            else:
                await websocket.send_text("Error: This endpoint accepts only byte messages.")
    except WebSocketDisconnect:
        logging.info("WebSocket legacy endpoint disconnected.")


@app.websocket("/ws/v2")
async def ws_json_endpoint(websocket: WebSocket):
    """
    A dedicated endpoint for JSON clients.
    """
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await ws_json_api(websocket, message)
    except WebSocketDisconnect:
        logging.info("WebSocket JSON endpoint disconnected.")


def set_brightness(value: int):
    """
    Sets brightness on all WLED controllers via /json endpoint.
    """
    payload = {"state": {"on": True, "bri": value}}
    for ip in WLED_IPS:
        try:
            requests.post(f"http://{ip}/json", json=payload)
            logging.info(f"Set brightness to {value} on {ip}")
        except Exception as e:
            logging.error(f"Failed to set brightness on {ip}: {e}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8901, reload=False)
