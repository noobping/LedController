from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Tuple
from threading import Thread
import socket
import requests
import time
import numpy as np
import cv2 as cv
import os
import glob
import concurrent.futures
import logging
import uvicorn

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# --------------------------------------------------------------------------------
#                          NEW VIDEO + PIANO LED LOGIC
# --------------------------------------------------------------------------------

# These match your existing WLED controller setup
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
BYTES_PER_LED = 3

stopVideo = False
video_thread = None


def build_packet(colors: List[Tuple[int, int, int]]) -> bytes:
    """
    Builds the DRGB packet (no header, just RGB bytes) for the entire LED array.
    """
    reversed_colors = colors[::-1]
    packet = bytearray()
    for (r, g, b) in reversed_colors:
        packet += bytes([r, g, b])
    return packet


def send_packet(ip: str, port: int, packet: bytes) -> None:
    """Send a UDP packet to a specified WLED controller."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(packet, (ip, port))
        sock.close()
    except Exception as e:
        logging.error(f"Failed to send packet to {ip}:{port}: {e}")


def send_frames(colors: List[Tuple[int, int, int]]) -> None:
    """
    Splits the color array into each controller's slice
    and sends them in parallel to the WLED IPs.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=TOTAL_CONTROLLERS) as executor:
        for idx, ip in enumerate(WLED_IPS):
            start_idx = idx * LEDS_PER_CONTROLLER
            end_idx = start_idx + LEDS_PER_CONTROLLER
            controller_slice = colors[start_idx:end_idx]
            packet = build_packet(controller_slice)
            executor.submit(send_packet, ip, PORT, packet)


def play_video(video_path: str, max_fps: float = None) -> None:
    """
    Continuously loop a video and send each frame to the WLED controllers,
    until stopVideo is set to True.
    """
    global stopVideo

    while not stopVideo:
        cap = cv.VideoCapture(video_path)
        if not cap.isOpened():
            logging.error(f"Failed to open video file: {video_path}")
            return

        fps = cap.get(cv.CAP_PROP_FPS)
        if fps == 0:
            fps = 30  # fallback
        if max_fps and fps > max_fps:
            fps = max_fps
            logging.info(f"FPS capped to {fps}")
        frame_duration = 1.0 / fps

        logging.info(f"Playing video in a loop: {video_path} at {fps} FPS")

        # Per your snippet, 4 rows x 5 columns => 20 windows total
        grid_rows = 4
        grid_cols = 5

        while not stopVideo:
            frame_start_time = time.time()
            ret, frame = cap.read()
            if not ret:
                # End of video => start again
                break
            if stopVideo:
                break

            # Convert to RGB if needed
            if len(frame.shape) == 2:
                # grayscale to RGB
                frame = cv.cvtColor(frame, cv.COLOR_GRAY2RGB)
            elif frame.shape[2] == 4:
                # BGRA to RGB
                frame = cv.cvtColor(frame, cv.COLOR_BGRA2RGB)
            else:
                # BGR to RGB
                frame = cv.cvtColor(frame, cv.COLOR_BGR2RGB)

            # Resize to 5x4
            resized_frame = cv.resize(
                frame, (grid_cols, grid_rows), interpolation=cv.INTER_AREA)

            # Flatten each "window" pixel
            reshaped_frame = resized_frame.reshape(-1, 3)  # shape -> (20, 3)
            # Repeat each color LEDS_PER_WINDOW times -> 20 * 20 = 400
            full_colors = np.repeat(
                reshaped_frame, LEDS_PER_WINDOW, axis=0).tolist()

            # Make sure length is exactly TOTAL_LEDS
            if len(full_colors) < TOTAL_LEDS:
                full_colors += [(0, 0, 0)] * (TOTAL_LEDS - len(full_colors))
            elif len(full_colors) > TOTAL_LEDS:
                full_colors = full_colors[:TOTAL_LEDS]

            # Send to WLED
            send_frames(full_colors)

            # Wait if needed
            elapsed = time.time() - frame_start_time
            wait_time = frame_duration - elapsed
            if wait_time > 0:
                time.sleep(wait_time)

        cap.release()

    # Once stopped, clear the LEDs
    black = [(0, 0, 0)] * TOTAL_LEDS
    send_frames(black)
    logging.info("Video playback stopped or finished.")


def start_video(videoName: str):
    """
    Starts a background thread that loops the given video indefinitely,
    replacing any currently-running video.
    """
    global video_thread, stopVideo

    # If a video is already playing, stop it
    if video_thread and video_thread.is_alive():
        stopVideo = True
        video_thread.join()

    # Reset the stop flag
    stopVideo = False
    # Construct path to /videos/videoName.mp4 (or other extension)
    video_path = os.path.join(os.path.dirname(__file__), 'videos', videoName)

    video_thread = Thread(target=play_video, args=(video_path,), daemon=True)
    video_thread.start()


def stop_video():
    """
    Stops any currently-looping video immediately.
    """
    global stopVideo, video_thread
    stopVideo = True
    if video_thread and video_thread.is_alive():
        video_thread.join()
    video_thread = None

# --------------------------------------------------------------------------------
#                         PIANO-LIKE LOGIC VIA WEBSOCKET
# --------------------------------------------------------------------------------


def handle_piano(controller_idx: int, window_idx: int):
    """
    Reproduce the "piano key" logic:
      - Turn all LEDs off except the 20 LEDs for (controller_idx, window_idx),
        which we set to white (255,255,255).
    """
    if not (0 <= controller_idx < TOTAL_CONTROLLERS):
        logging.error(f"Invalid controller index: {controller_idx}")
        return
    if not (0 <= window_idx < WINDOWS_PER_CONTROLLER):
        logging.error(f"Invalid window index: {window_idx}")
        return

    # Start all LEDs off
    colors = [(0, 0, 0)] * TOTAL_LEDS

    # Calculate the absolute LED indices for that window
    start_led = window_idx * LEDS_PER_WINDOW
    end_led = start_led + LEDS_PER_WINDOW
    absolute_start = controller_idx * LEDS_PER_CONTROLLER + start_led
    absolute_end = controller_idx * LEDS_PER_CONTROLLER + end_led

    # Make those 20 LEDs white
    for i in range(absolute_start, absolute_end):
        colors[i] = (255, 255, 255)

    # Send to the WLED controllers
    send_frames(colors)

# --------------------------------------------------------------------------------
#                          FASTAPI APP + ENDPOINTS
# --------------------------------------------------------------------------------


description = """
This API is used to send UDP commands to WLED controllers to control their LEDs like they're a 2D matrix.<br>
The API requires the user to send a full (for now) virtual state of the matrix' colors in hex strings to one of the API's endpoints, which the server will then use to update the real LED matrix.<br><br>
The API has two endpoints from which it can be accessed:<br>
* **HTTP Post requests** at http://{server_ip}/update, requires the virtual state in JSON as input. (This is however deprecated and should not be used.)<br>
* **Websocket**: at ws://{server_ip}/ws, requires the virtual state in a byte array with the text "update; " in front.<br>
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

# For the old "matrix" logic, we keep a global frame
currentFrame = ["000000"] * TOTAL_LEDS


class ColorMatrix(BaseModel):
    State: List[str]  # Each "RRGGBB"


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket commands:
      - "setall; RRGGBB"
      - "update; RRGGBB, RRGGBB, ..."
      - "difference; (index), (RRGGBB), (index), (RRGGBB), ..."
      - "videolist;"
      - "video; videoFileName"
      - "stop;"
      - "brightness; intValue"
      - "piano; controller_idx,window_idx"
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()
            parts = data.split(b"; ")
            command = parts[0]

            if command == b"setall":
                setAllColors(parts[1].decode())

            elif command == b"update":
                matrix = ColorMatrix(State=parts[1].split(b", "))
                matrix.State = [m.decode() for m in matrix.State]
                update_matrix(matrix)

            elif command == b"difference":
                diffs = parts[1].split(b", ")
                differences = [d.strip(b"()").decode() for d in diffs]
                differences = [differences[i:i+2]
                               for i in range(0, len(differences), 2)]
                update_differences(differences)

            elif command == b"videolist":
                await websocket.send_text("videos: " + ", ".join(get_video_list()))

            elif command == b"video":
                start_video(parts[1].decode())

            elif command == b"stop":
                stop_video()

            elif command == b"brightness":
                set_brightness(int(parts[1]))

            elif command == b"piano":
                coords = parts[1].decode().split(",")
                if len(coords) == 2:
                    c_i = int(coords[0].strip())
                    w_i = int(coords[1].strip())
                    handle_piano(c_i, w_i)
                else:
                    logging.error(
                        "Invalid piano command format. Expected: 'piano; X,Y'")
            else:
                logging.warning(
                    "Unknown websocket command: " + command.decode())

            await websocket.send_text("OK.")
    except WebSocketDisconnect:
        pass


@app.get("/videolist")
def get_video_list():
    """Returns the names of all .mp4 files in the /videos folder."""
    video_path = os.path.join(os.path.dirname(__file__), 'videos')
    video_list = [
        os.path.splitext(os.path.basename(v))[0]
        for v in glob.glob(os.path.join(video_path, "*.mp4"))
    ]
    return video_list


@app.get("/status")
def get_status():
    """Returns the current state (in hex) of the matrix as we've last set it."""
    return {"status": currentFrame}


@app.get("/brightness")
def get_brightness():
    """
    Returns the brightness levels from all WLED controllers
    by calling their /json endpoint.
    """
    brightness_levels = {}
    for ip in WLED_IPS:
        try:
            response = requests.get(f"http://{ip}/json")
            if response.status_code == 200:
                data = response.json()
                brightness_levels[ip] = data.get(
                    "state", {}).get("bri", "Unknown")
            else:
                brightness_levels[ip] = "Error fetching brightness"
        except Exception as e:
            brightness_levels[ip] = f"Error: {e}"
    return {"brightness": brightness_levels}


def setAllColors(color: str):
    """
    Sets all LEDs to the same hex color. 
    We immediately send a single frame update via the new snippet logic.
    """
    if len(color) != 6:
        raise HTTPException(
            status_code=400, detail="Color must be 6 hex chars")
    global currentFrame
    currentFrame = [color] * TOTAL_LEDS
    send_hex_colors(currentFrame)


def update_matrix(colorMatrix: ColorMatrix):
    """
    Expects exactly TOTAL_LEDS hex colors. We store them globally
    and send them to the WLED controllers once.
    """
    global currentFrame
    if len(colorMatrix.State) != TOTAL_LEDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid matrix length. Expected {TOTAL_LEDS} hex colors."
        )
    currentFrame = colorMatrix.State
    send_hex_colors(currentFrame)


def update_differences(differences: List[List[str]]):
    """
    Receives pairs of [index, hexColor], updates them in currentFrame,
    then sends the updated frame once.
    """
    global currentFrame
    for diff in differences:
        idx = int(diff[0])
        col = diff[1]
        if len(col) == 6 and 0 <= idx < TOTAL_LEDS:
            currentFrame[idx] = col
    send_hex_colors(currentFrame)


def send_hex_colors(hex_array: List[str]):
    """
    Converts our array of "RRGGBB" strings into a list of (R,G,B) tuples,
    then calls send_frames from your new snippet logic.
    """
    if len(hex_array) < TOTAL_LEDS:
        hex_array += ["000000"] * (TOTAL_LEDS - len(hex_array))
    colors = []
    for hexcol in hex_array:
        r = int(hexcol[0:2], 16)
        g = int(hexcol[2:4], 16)
        b = int(hexcol[4:6], 16)
        colors.append((r, g, b))
    if len(colors) > TOTAL_LEDS:
        colors = colors[:TOTAL_LEDS]
    send_frames(colors)


def set_brightness(value: int):
    """
    Sets brightness of all WLED controllers via their HTTP JSON interface.
    """
    payload = {"on": True, "bri": value, "seg": [{"col": [0, 0, 0]}]}
    for ip in WLED_IPS:
        try:
            requests.post(f"http://{ip}/json", json=payload)
        except Exception:
            continue


# --------------------------------------------------------------------------------
#                            MAIN ENTRY POINT
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=80,
        reload=False
    )
