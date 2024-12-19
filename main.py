from fastapi import FastAPI, HTTPException, Body, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Annotated
from typing import Tuple
from threading import Thread
import socket
import uvicorn
import copy
import requests
import random    
import time
import numpy as np
import cv2 as cv
import os
import glob


description = """<br>
This API is used to send UDP commands to WLED controllers to control their LEDs like they're a 2D matrix.<br>
The API requires the user to send a full (for now) virtual state of the matrix' colors in hex strings to one of the API's endpoints, which the server will then use to update the real LED matrix.<br><br>
The API has two endpoints from which it can be accessed:
* **HTTP Post requests** at http://{server_ip}/update, requires the virtual state in JSON as input. (This is however deprecated and should not be used.)
* **Websocket**: at ws://{server_ip}/ws, requires the virtual state in a byte array with the text "update; " in front.

Besides the update function, which updates the entire matrix, there is also a setAllColors function, which goes mostly unused.
<br><br>"""

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

LEDS_PER_WINDOW: int = 20
WINDOWS_PER_WLED: int = 5
LEDS_PER_WLED: int = LEDS_PER_WINDOW * WINDOWS_PER_WLED
WLED_IPS: Tuple[str, ...] = \
    ("192.168.107.123", "192.168.107.122", "192.168.107.120", "192.168.107.121")
LEDS_IN_MATRIX: int = LEDS_PER_WLED * len(WLED_IPS)
MATRIX_SHAPE: Tuple[int, int] = (2, 2)
UDP_PORT: int = 21324
VIDEO_PATH = os.path.join(os.path.dirname(__file__), 'videos')

"""
    Changing this variable causes the state that is sent to the LED matrix
    to be reversed. This is so that the matrix is aligned properly when
    looking from the front of the LED matrix, as opposed to viewing it from
    inside.
"""
REVERSE_VIEW = True;

stopVideo = False
idleCounterLimit = 3


""" This code is used to repeatedly send the current state in the background """
currentState = ["000000"] * LEDS_IN_MATRIX

@app.on_event("startup")
def startup_event():
    Thread(target=send_state, daemon=True).start()

""" 
    This function repeatedly updates the LED matrix with the current state. 
    For more information on the format of the byteString, check out the official WLED page for UDP:
    https://kno.wled.ge/interfaces/udp-realtime/
"""
def send_state():
    idleCounter = 0
    while True:
        # Quick fix for stopping constant updates when idle
        allBlack = all(color == "000000" for color in currentState)
        if allBlack:
            if idleCounter < idleCounterLimit:
                idleCounter += 1
        else:
            idleCounter = 0
        if idleCounter != idleCounterLimit:
            actualState = reverse_state()
            for i in range(len(WLED_IPS)):
                subMatrix = actualState[i*LEDS_PER_WLED:(i+1)*LEDS_PER_WLED]
                byteString = f"02 02 {' '.join(subMatrix)}"
                udpPacket = bytes.fromhex(byteString)
                ip = WLED_IPS[i]
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(udpPacket, (ip, UDP_PORT))
                
        time.sleep(0.05)
        

"""
This function reverses the currentState variable when REVERSE_VIEW is
true, and returns it. When REVERSE_VIEW is false, it will return
currentState without modifying it.
"""
def reverse_state():
    global currentState
    if not REVERSE_VIEW:
        return currentState
        
    tempState = []
    rows = MATRIX_SHAPE[1]
    ledsInRow = LEDS_IN_MATRIX // rows
    for row in range(rows):
        tempState.extend(currentState[row * ledsInRow : (row+1) * ledsInRow][::-1])
    return tempState

""" 
    This is the websocket endpoint for the application.
    The protocol works as such:
    Messages are received as UTF-8 formatted bytestrings.
    The first word of the message determines the function to be called,
    and is followed up by a semicolon and a space.
    Which is then followed by the relevant data (color, matrix/list of colors, etc.).
"""
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()


            data = data.split(b"; ")
            match data[0]:
                case b"setall":
                    setAllColors(data[1])
                case b"update":
                    matrix = ColorMatrix(State=data[1].split(b", "))
                    update_matrix(matrix)
                case b"difference":
                    differences = [str(diff.strip(b"()"), encoding='utf-8') for diff in data[1].split(b", ")]
                    differences = [differences[i:i+2] for i in range(0, len(differences), 2)]
                    update_differences(differences)
                case b"videolist":
                    await websocket.send_text(("videos: ", ", ".join(get_video_list())))
                case b"video":
                    start_video(data[1].decode())
                case b"stop":
                    print("stopping")
                    global stopVideo
                    stopVideo = True
                case b"brightness":
                    set_brightness(int(data[1]))
                case _:
                    print("Unknown websocket command: " + data[0].decode())
            
            await websocket.send_text("OK.")

    except WebSocketDisconnect:
        pass



def setAllColors(color: str):
    """This function sets all windows to the same color."""
    if len(color) != 6:
        raise HTTPException(status_code=400, detail=f"Invalid string length")
    global currentState
    currentState = [color] * LEDS_IN_MATRIX
    

"""
    A class to represent the colors of the LED matrix.
    The State variable holds all the data, and the list must be the same
    size as the configured LED matrix.
"""
class ColorMatrix(BaseModel):
    State: List[str]

"""
    This function sets the light matrix to the colors specified in
    the State list from the given ColorMatrix object.
"""
def update_matrix(colorMatrix: ColorMatrix):

    global currentState
    if len(colorMatrix.State) == LEDS_IN_MATRIX:
        currentState = colorMatrix.State
    else:
        raise HTTPException(status_code=400, detail=f"Invalid matrix length")

def update_differences(differences: List[List[str]]):
    for difference in differences:
        currentState[int(difference[0])] = difference[1]



def start_video(videoName: str):
    Thread(target=video_playback, args=(videoName,)).start()

"""
    This function uses openCV to take the frames of a video file and
    display them on the LED matrix.
    It can be stopped by receiving the relevant command.
"""
def video_playback(videoName: str):
    global currentState
    global stopVideo
    stopVideo = False
    frameCount = 0
    try:
        videofile = glob.glob(os.path.join(VIDEO_PATH, videoName + ".*"))[0]
    except IndexError:
        print("File not found: " + videoName)
        return
    cap = cv.VideoCapture(videofile)
    while True:
        if stopVideo:
            setAllColors("000000")
            print("stopped")
            break
            
        ret, frame = cap.read()
        if not ret:
            setAllColors("000000")
            print("done")
            break
        
        frameState = [''.join([f"{rgb:02x}" for rgb in pixel]) for pixel in frame.reshape(-1, frame.shape[-1])]
        frameCount += 1
        currentState = frameState
        time.sleep(0.05)

"""
    Returns the names of all files in the /videos folder.
"""
@app.get("/videolist")
def get_video_list():
    print(VIDEO_PATH)
    videoList = [video.split("/")[-1] for video in glob.glob(os.path.join(VIDEO_PATH, "*.mp4"))]
    return videoList

"""
    Returns the current state of the LED matrix.
    Each LED's color is represented in "RRGGBB" hex format.
"""
@app.get("/status")
def get_status():
    global currentState
    return {"status": currentState}

"""
    Fetches the current brightness levels from all WLED controllers.
    Returns a dictionary with the IP addresses and their corresponding brightness levels.
"""
@app.get("/brightness")
def get_brightness():
    brightness_levels = {}
    for ip in WLED_IPS:
        try:
            response = requests.get(f"http://{ip}/json")
            if response.status_code == 200:
                data = response.json()
                brightness_levels[ip] = data.get("state", {}).get("bri", "Unknown")
            else:
                brightness_levels[ip] = "Error fetching brightness"
        except Exception as e:
            brightness_levels[ip] = f"Error: {e}"
    return {"brightness": brightness_levels}

"""
    Sets brightness of the WLED controllers and corrects any other
    possible mistakes in the configuration.
"""
def set_brightness(value: int):
    json = {
        "on": True,
        "bri": value,
        "seg": [{
            "col": [0,0,0]
            }]
    }
    for ip in WLED_IPS:
        try:
            response = requests.post(f"http://{ip}/json", json=json)
        except:
            continue
        
