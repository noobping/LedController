from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import List, Annotated
from collections import deque
from typing import Tuple
import socket
import uvicorn
import copy
import requests
import random	


app = FastAPI()

LEDS_PER_WINDOW: int = 20
WINDOWS_PER_WLED: int = 5
LEDS_PER_WLED: int = LEDS_PER_WINDOW * WINDOWS_PER_WLED
WLEDS_GRID: Tuple[int, int] = (2, 2)
WINDOWS_GRID: Tuple[int, int] = (WLEDS_GRID[0] * WINDOWS_PER_WLED, WLEDS_GRID[1])
WLED_IPS: Tuple[str, ...] = \
	("192.168.107.123", "192.168.107.122", "192.168.107.120", "192.168.107.121")
UDP_PORT: int = 21324

# Random color functions
r = lambda: random.randint(64, 255)
rh = lambda: '%02X%02X%02X' % (r(),r(),r())

""" Used to subtract hexadecimal color values from eachother. """
def subtractColors(hex1: str, hex2: str) -> str:
	resulthex = ""
	for i in range(0,6,2):
		resulthex += f"{(max(int(hex1[i:i+2], 16) - int(hex2[i:i+2], 16), 0)):02x}"
	return resulthex

def responseTimeMsString(response):
	return str((response.elapsed.microseconds + response.elapsed.seconds * 1000000) // 1000) + "ms"
	


@app.get("/setall/{color}")
def setAllColors(color: str):
	"""This function sets all windows to the same color."""
	if len(color) != 6:
		raise HTTPException(status_code=400, detail=f"Invalid string length")
	try:
		byteString = f"02 02 {(color + ' ') * LEDS_PER_WLED}".strip()
		udpPacket = bytes.fromhex(byteString)
	except ValueError:
		raise HTTPException(status_code=400, detail=f"Invalid hex character in string")

	print(udpPacket)
	sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	for ip in WLED_IPS:
		sock.sendto(udpPacket, (ip, UDP_PORT))
	
	return byteString
	
# @app.get("/spin")
# def rainbow_spin():
	# """ (incomplete) This function is a test that makes a light "spin" all around the light matrix while leaving a small trail """
	# preset2Json = {
		# "ps": 2
	# }
	# #response = requests.post("http://192.168.107.120/json", json=preset2Json)
	
	# ledColors = deque(["000000"]*6)
	# ledStrip = ["000000"] * 200
	# for i in range(41, 100):
		# ledColors = deque([subtractColors(x, '333333') for x in ledColors])
		# ledColors.rotate(-1)
		# ledColors[-1] = rh()
		# ledStrip[i-5:i+1] = ledColors
		# LEDJson = {
			# "seg": {
				# "id": 0,
				# "on": True,
				# "i": ledStrip
			# }
		# }
		# response1 = requests.post("http://192.168.107.120/json", json=LEDJson)
		
		
	# preset1Json = {
		# "ps": 1
	# }
	# #response = requests.post("http://192.168.107.120/json", json=preset1Json)
	# raise HTTPException(status_code=418)
	
class ColorMatrix(BaseModel):
	""" A list of 20 (10x2) color values in hex to represent the light matrix """
	State: List[str]
	
@app.post("/update")
def update_matrix(colorMatrix: ColorMatrix):
	""" This function sets the light matrix to the colors specified in the given ColorMatrix array """
	matrix = colorMatrix.State
	print([(color, matrix.index(color)) for color in matrix if color != '000000'])
	for i in range(len(WLED_IPS)):
		subMatrix = matrix[i*LEDS_PER_WLED:i*LEDS_PER_WLED+LEDS_PER_WLED]
		byteString = f"02 02 {' '.join(subMatrix)}"
		udpPacket = bytes.fromhex(byteString)
		ip = WLED_IPS[i]
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.sendto(udpPacket, (ip, UDP_PORT))
		
		
		

# @app.get("/reset")
# def reset_matrix():
	# """ This function "resets" the matrix by setting the WLED preset """
	# wLedJson = {
		# "ps": 1 
		# }
	# response = requests.post("http://192.168.107.120/json", json=wLedJson)
	# print(response.json())
	# raise HTTPException(status_code=418)
