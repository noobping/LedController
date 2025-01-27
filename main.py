from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from threading import Thread
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
import uvicorn

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
FRAME_INTERVAL = 5  # seconds

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


# --------------------------------------------------------------------------------
#                           CHRISTMAS ANIMATION LOGIC
# --------------------------------------------------------------------------------


# Global variables for Christmas animation
stopChristmas = False
christmas_thread = None


def make_christmas_frame(enabled: bool = True) -> List[Tuple[int, int, int]]:
    """
    Create a fixed red-green pattern with blocks of LEDs each, starting with red or green.

    Args:
        enabled (bool): If True, start with red blocks; otherwise, start with green.

    Returns:
        List[Tuple[int, int, int]]: A list of (R, G, B) tuples with red and green colors.
    """
    logging.debug(f"Creating Christmas frame that starts with {
                  'red' if enabled else 'green'}")
    colors = []
    for i in range(TOTAL_LEDS):
        block = i // LEDS_PER_WINDOW  # Determine the block index
        if enabled:
            if block % 2 == 0:
                colors.append((255, 0, 0))  # Red
            else:
                colors.append((0, 255, 0))  # Green
        else:
            if block % 2 == 0:
                colors.append((0, 255, 0))  # Green
            else:
                colors.append((255, 0, 0))  # Red
    return colors


def run_christmas_animation():
    """
    Runs the Christmas animation by alternating between two frames every 5 counts.
    Each frame is held for FRAME_INTERVAL seconds before switching.
    """
    global stopChristmas
    logging.info(
        "Starting Christmas animation with alternating frames every 5 counts.")

    counter = 0  # Initialize the counter
    enabled = False  # Determines which frame to send

    while not stopChristmas:
        # Generate the current frame based on the 'enabled' flag
        colors = make_christmas_frame(enabled)
        send_frames(colors)
        logging.debug(f"Sent frame {'Enabled' if enabled else 'Disabled'}. Counter: {
                      counter + 1}/{FRAME_INTERVAL}")

        time.sleep(0.3) # Sleep for 0.3 seconds
        counter += 1  # Increment the counter

        if counter >= FRAME_INTERVAL:
            # Switch frames after 5 counts
            enabled = not enabled
            counter = 0  # Reset the counter
            logging.info(f"Switched to {
                         'Enabled' if enabled else 'Disabled'} frame.")

    # Clear the LEDs when stopping
    black = [(0, 0, 0)] * TOTAL_LEDS
    send_frames(black)
    logging.info("Christmas animation stopped and LEDs cleared.")


def start_christmas():
    """
    Starts the Christmas animation. Stops any ongoing video playback or other animations.
    """
    global christmas_thread, stopChristmas, video_thread, stopVideo

    # Reset the stop flag
    stopChristmas = False

    # Start the Christmas animation in a new thread
    christmas_thread = Thread(target=run_christmas_animation, daemon=True)
    christmas_thread.start()
    logging.info("Christmas animation thread started.")


def stop_animation():
    """
    Stops any ongoing animations, including video playback and Christmas animation.
    """
    global stopVideo, video_thread, stopChristmas, christmas_thread
    logging.info("Stopping all ongoing animations.")

    # Stop video playback
    if video_thread and video_thread.is_alive():
        logging.info("Stopping video playback.")
        stopVideo = True
        video_thread.join()
        video_thread = None

    # Stop Christmas animation
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
#                           FASTAPI APPLICATION
# --------------------------------------------------------------------------------


description = """
This API controls WLED-based LED matrices via UDP.  
It provides:
- **Video playback** (looping)  
- **Brightness** control  
- **Piano-like** single-window highlighting  
- **Christmas** themed animation

All commands are sent via either:
- HTTP GET/POST endpoints for brightness, video list, etc.
- WebSocket commands (piano, video, stop, brightness, christmas, etc.).
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
    },
    lifespan=None
)


async def lifespan(app: FastAPI):
    """
    Lifespan event handler for FastAPI application.
    Manages startup and shutdown tasks.
    """
    # Startup tasks
    logging.info("Application startup: Initializing background tasks.")
    asyncio.create_task(transfer_sync_to_async())
    asyncio.create_task(broadcast_logs())

    # Yield control to the application
    yield

    # Shutdown tasks
    logging.info("Application shutdown: Cleaning up background tasks.")
    # If you have any cleanup tasks, they can be added here
    # For example, stopping animations or closing resources
    stop_animation()


# Re-initialize the FastAPI app with the lifespan handler
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
      - "christmas"
    """
    await websocket.accept()

    # Register this websocket
    connected_websockets.append(websocket)
    logging.info(f"WebSocket connected. Current count: {
                 len(connected_websockets)}")

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
                if len(parts) < 2:
                    await websocket.send_text("Error: Missing video name.")
                    continue
                video_name = parts[1].decode()
                start_video(video_name + ".mp4")
                await websocket.send_text("Video playback started.")

            elif command == b"stop":
                # Stop any ongoing animation
                stop_animation()
                await websocket.send_text("All animations stopped.")

            elif command == b"brightness":
                # Set brightness
                if len(parts) < 2:
                    await websocket.send_text("Error: Missing brightness value.")
                    continue
                try:
                    value = int(parts[1])
                    set_brightness(value)
                    await websocket.send_text(f"Brightness set to {value}.")
                except ValueError:
                    await websocket.send_text("Error: Brightness value must be an integer.")
                    continue

            elif command == b"piano":
                # Example: "piano 0,2"
                if len(parts) < 2:
                    await websocket.send_text("Error: Missing piano coordinates.")
                    continue
                coords = parts[1].decode().split(",")
                if len(coords) == 2:
                    try:
                        controller_idx = int(coords[0])
                        window_idx = int(coords[1])
                        handle_piano(controller_idx, window_idx)
                        await websocket.send_text(f"Piano window {window_idx} on controller {controller_idx} activated.")
                    except ValueError:
                        await websocket.send_text("Error: Controller and window indices must be integers.")
                        continue
                else:
                    logging.error(
                        "Invalid piano command format. Expected: 'piano X,Y'")
                    await websocket.send_text("Error: Invalid piano command format. Expected: 'piano X,Y'")

            elif command == b"christmas":
                # Start Christmas animation
                start_christmas()
                await websocket.send_text("Christmas animation started.")

            else:
                logging.warning(f"Unknown WebSocket command: {
                                command.decode()}")
                await websocket.send_text("Error: Unknown command.")

            # Confirm
            await websocket.send_text("OK.")
    except WebSocketDisconnect:
        logging.info("WebSocket disconnected")
    finally:
        # Unregister this websocket
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)
            logging.info(f"WebSocket disconnected. Current count: {
                         len(connected_websockets)}")


def set_brightness(value: int):
    """
    Sets brightness (0-255) on all WLED controllers via /json endpoint.
    """
    payload = {"on": True, "bri": value, "seg": [{"col": [0, 0, 0]}]}
    for ip in WLED_IPS:
        try:
            requests.post(f"http://{ip}/json", json=payload)
            logging.info(f"Set brightness to {value} on {ip}")
        except Exception as e:
            logging.error(f"Failed to set brightness on {ip}: {e}")


async def transfer_sync_to_async():
    """
    Asynchronous task to transfer log messages from the synchronous queue
    to the asynchronous log_queue once the event loop is running.
    """
    loop = asyncio.get_event_loop()
    while True:
        try:
            # Retrieve a message from the synchronous queue without blocking indefinitely
            msg = sync_log_queue.get(timeout=0.1)
            await log_queue.put(msg)
        except queue.Empty:
            await asyncio.sleep(0.1)  # Sleep briefly to prevent tight loop


async def broadcast_logs():
    """
    Background task: continually read from log_queue and send to all connected websockets.
    """
    while True:
        msg = await log_queue.get()   # Wait until a log message is available
        if not connected_websockets:
            await asyncio.sleep(0.1)  # No clients connected, sleep briefly
            continue
        dead_websockets = []
        for ws in connected_websockets:
            try:
                await ws.send_text(msg)
            except Exception:
                # Mark this websocket as dead/disconnected
                dead_websockets.append(ws)

        # Remove the dead websockets
        for ws in dead_websockets:
            if ws in connected_websockets:
                connected_websockets.remove(ws)
                logging.info(f"Removed dead WebSocket. Current count: {
                             len(connected_websockets)}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=False)
