from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from typing import List, Tuple
import asyncio
import concurrent.futures
import cv2 as cv
import glob
import logging
import numpy as np
import os
import queue
import requests
import socket
import time
import httpx
import uvicorn
from threading import Thread

# --------------------------------------------------------------------------------
#                           LOGGING CONFIGURATION
# --------------------------------------------------------------------------------

# List to keep track of connected WebSocket clients
connected_websockets: List[WebSocket] = []

# Asynchronous queue to hold log messages for broadcasting
log_queue = asyncio.Queue()

# Synchronous queue to buffer log messages before the event loop starts
sync_log_queue = queue.Queue()


class WebSocketLogHandler(logging.Handler):
    """
    Custom logging handler that sends log records to a synchronous queue.
    """

    def __init__(self, level=logging.NOTSET):
        super().__init__(level=level)

    def emit(self, record: logging.LogRecord) -> None:
        """Send the log record's message into a synchronous queue."""
        msg = self.format(record)
        try:
            sync_log_queue.put_nowait(msg)
        except queue.Full:
            # Handle full queue scenario if needed
            logging.warning("Log queue is full. Dropping log message.")
            pass


# Configure the root logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Remove existing handlers to prevent duplicate logs
logger.handlers = []

# Create and add console handler
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Create and add WebSocket log handler
ws_handler = WebSocketLogHandler()
ws_handler.setFormatter(console_formatter)
logger.addHandler(ws_handler)

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

# For old “reverse_view” logic:
REVERSE_VIEW = True

# A global to store the "legacy" color state (400 hex strings)
# so the old commands remain compatible. Default black: "000000"
legacy_current_state = ["000000"] * TOTAL_LEDS

# Convert a 6-digit hex string (e.g. "ff8040") to (R, G, B)


def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

# Optionally replicate row-based reversing from the old code,
# but here's a simpler total reverse if needed:


def reverse_legacy_state():
    if not REVERSE_VIEW:
        return legacy_current_state
    return legacy_current_state[::-1]


stopVideo = False
video_thread = None

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
        video_thread.join()

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

    # Clear on stop
    black = [(0, 0, 0)] * TOTAL_LEDS
    send_frames(black)
    logging.info("Christmas animation stopped and LEDs cleared.")


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


def stop_animation():
    """
    Stops any ongoing animations, including video playback and Christmas animation.
    """
    global stopVideo, video_thread, stopChristmas, christmas_thread
    logging.info("Stopping all ongoing animations.")

    # Stop video
    if video_thread and video_thread.is_alive():
        logging.info("Stopping video playback.")
        stopVideo = True
        video_thread.join()
        video_thread = None

    # Stop Christmas
    if christmas_thread and christmas_thread.is_alive():
        logging.info("Stopping Christmas animation.")
        stopChristmas = True
        christmas_thread.join()
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


async def lifespan(app: FastAPI):
    """
    Lifespan event handler for startup/shutdown tasks.

    Args:
        app (FastAPI): The FastAPI application instance.
    """
    logging.info("Application startup: Initializing background tasks.")
    asyncio.create_task(transfer_sync_to_async())
    asyncio.create_task(broadcast_logs())

    yield  # hand over to the application

    logging.info("Application shutdown: Cleaning up background tasks.")
    stop_animation()

app = FastAPI(
    title="LedControllerAPI",
    summary="API server for controlling WLED lights like a matrix.",
    description=description,
    version="0.5.0",
    contact={
        "name": "Lucrasoft",
        "url": "https://www.lucrasoft.nl/",
        "email": "info@lucrasoft.nl"
    },
    lifespan=lifespan
)


@app.get("/")
async def index():
    """
    Default web page.
    """
    # Determine the path to the index.html file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, "index.html")
    
    # Check if the file exists
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="index.html not found")
    
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket commands supported (new style):
        - "videolist"
        - "video <videoName>"
        - "stop"
        - "brightness <intValue>"
        - "piano <controller_idx>,<window_idx>"
        - "christmas"

    Also handles old-style commands:
        - "setall; <hexColor>"
        - "update; <hexColor_1>, <hexColor_2>, ..."
        - "difference; (index, color), (index, color), ...
        - "videolist;"
        - "video; <videoName>"
        - "stop;"
        - "brightness; <intValue>"
    """
    await websocket.accept()
    connected_websockets.append(websocket)
    logging.info(f"WebSocket connected. Current count: {len(connected_websockets)}")

    try:
        while True:
            data = await websocket.receive_bytes()
            # We'll handle both new-style (space-separated) and old-style (split on "; ")
            # So let's see if there's a semicolon approach:
            if b"; " in data:
                # old-style approach
                parts = data.split(b"; ")
                # e.g. "setall" or "update"
                command = parts[0].decode("utf-8").lower()
                arg = parts[1] if len(parts) > 1 else b""
                # Dispatch old commands
                if command == "setall":
                    # Arg is a 6-char hex color
                    hexcolor = arg.decode("utf-8").strip()
                    if len(hexcolor) == 6:
                        for i in range(TOTAL_LEDS):
                            legacy_current_state[i] = hexcolor
                        # Convert & send
                        apply_legacy_state()
                        await websocket.send_text("OK.")
                    else:
                        await websocket.send_text("Error: Invalid hex color.")
                elif command == "update":
                    # Arg is a list of 400 hex strings separated by ", "
                    color_list = arg.split(b", ")
                    if len(color_list) == TOTAL_LEDS:
                        for i, c in enumerate(color_list):
                            legacy_current_state[i] = c.decode("utf-8")
                        apply_legacy_state()
                        await websocket.send_text("OK.")
                    else:
                        await websocket.send_text(f"Error: Expected {TOTAL_LEDS} hex colors.")
                elif command == "difference":
                    # Arg is e.g. "(index, color), (index, color), ..."
                    # let's parse them
                    # Example chunk: b"(10, ff00ff), (392, 00ff00)"
                    # Strategy: split by ", " => each pair of items forms (index, color)
                    diffs = arg.split(b", ")
                    # diffs might be ["(10", "ff00ff)", "(392", "00ff00)"] etc.
                    # We'll pair them up:
                    if len(diffs) % 2 != 0:
                        await websocket.send_text("Error: difference data malformed.")
                    else:
                        for i in range(0, len(diffs), 2):
                            idx_str = diffs[i].replace(
                                b"(", b"").replace(b")", b"")
                            col_str = diffs[i +
                                            1].replace(b"(", b"").replace(b")", b"")
                            try:
                                idx = int(idx_str)
                                col = col_str.decode("utf-8")
                                legacy_current_state[idx] = col
                            except:
                                pass
                        apply_legacy_state()
                        await websocket.send_text("OK.")
                elif command == "videolist":
                    videos = get_video_list()
                    await websocket.send_text("videos: " + ", ".join(videos))
                elif command == "video":
                    video_name = arg.decode("utf-8").strip()
                    if video_name:
                        start_video(video_name + ".mp4")
                        await websocket.send_text("OK.")
                    else:
                        await websocket.send_text("Error: missing video name.")
                elif command == "stop":
                    stop_animation()
                    await websocket.send_text("OK.")
                elif command == "brightness":
                    try:
                        value = int(arg)
                        set_brightness(value)
                        await websocket.send_text("OK.")
                    except:
                        await websocket.send_text("Error: brightness value must be integer.")
                else:
                    logging.warning(
                        f"Unknown old-style WebSocket command: {command}")
                    await websocket.send_text("Error: Unknown old-style command.")
            else:
                # Possibly new-style approach, space-separated
                parts = data.split(b" ", 1)
                command = parts[0].decode("utf-8").lower()

                if command == "videolist":
                    videos = get_video_list()
                    await websocket.send_text("videos: " + ", ".join(videos))

                elif command == "video":
                    if len(parts) < 2:
                        await websocket.send_text("Error: Missing video name.")
                        continue
                    video_name = parts[1].decode("utf-8").strip()
                    start_video(video_name + ".mp4")
                    await websocket.send_text("Video playback started.")

                elif command == "stop":
                    stop_animation()
                    await websocket.send_text("All animations stopped.")

                elif command == "brightness":
                    if len(parts) < 2:
                        await websocket.send_text("Error: Missing brightness value.")
                        continue
                    try:
                        value = int(parts[1])
                        set_brightness(value)
                        await websocket.send_text(f"Brightness set to {value}.")
                    except ValueError:
                        await websocket.send_text("Error: Brightness value must be an integer.")

                elif command == "piano":
                    # "piano 0,2"
                    if len(parts) < 2:
                        await websocket.send_text("Error: Missing piano coords.")
                        continue
                    coords = parts[1].split(b",")
                    if len(coords) == 2:
                        try:
                            controller_idx = int(coords[0])
                            window_idx = int(coords[1])
                            handle_piano(controller_idx, window_idx)
                            await websocket.send_text(f"Piano window {window_idx} on controller {controller_idx} activated.")
                        except ValueError:
                            await websocket.send_text("Error: Piano coords must be integers.")
                    else:
                        await websocket.send_text("Error: Invalid piano command format. Use 'piano X,Y'")

                elif command == "christmas":
                    start_christmas()
                    await websocket.send_text("Christmas animation started.")
                else:
                    logging.warning(
                        f"Unknown new-style WebSocket command: {command}")
                    await websocket.send_text("Error: Unknown command.")
    except WebSocketDisconnect:
        logging.info("WebSocket disconnected")
    finally:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)
        logging.info(f"WebSocket disconnected. Current count: {len(connected_websockets)}")


def apply_legacy_state():
    """
    Convert the global 'legacy_current_state' (400 hex strings)
    into a list of (R, G, B), apply reversing if needed,
    then call send_frames().
    """
    # Possibly do row-based reversing if you want to replicate
    # the old code exactly. For now, a full reverse:
    reversed_hex = reverse_legacy_state()

    colors = [hex_to_rgb(h) for h in reversed_hex]
    send_frames(colors)


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


async def transfer_sync_to_async():
    """
    Asynchronous task: move log messages from sync_log_queue => log_queue
    once the event loop is running.
    """
    while True:
        try:
            msg = sync_log_queue.get(timeout=0.1)
            await log_queue.put(msg)
        except queue.Empty:
            await asyncio.sleep(0.1)


async def broadcast_logs():
    """
    Reads from log_queue and sends log messages to all connected websockets.
    """
    while True:
        msg = await log_queue.get()
        if not connected_websockets:
            await asyncio.sleep(0.1)
            continue
        dead_websockets = []
        for ws in connected_websockets:
            try:
                await ws.send_text(msg)
            except:
                dead_websockets.append(ws)
        for ws in dead_websockets:
            if ws in connected_websockets:
                connected_websockets.remove(ws)
                logging.info("Removed dead WebSocket.")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=False)
