import asyncio
import websockets
import random

SERVER_IP = "192.168.102.105"
SERVER_PORT = 8901
WS_URL = f"ws://{SERVER_IP}:{SERVER_PORT}/ws"

async def send_update(websocket, color_list):
    """
    Sends an 'update' command to the LED matrix using a list of hex color values.
    The server expects data in the format: b"update; " followed by the matrix data as a comma-separated byte array.
    """
    # The server expects a bytes message:
    # Format: b"update; RRGGBB, RRGGBB, RRGGBB, ... "
    #
    # Here, color_list is a Python list of hex strings like ["ff0000", "00ff00", "0000ff", ...]
    # We'll join them by ", " (comma+space) and prefix with "update; ".
    payload_str = "update; " + ", ".join(color_list)
    await websocket.send(payload_str.encode('utf-8'))
    response = await websocket.recv()
    # The server should return "OK." after handling the command
    # You can print the response if you'd like:
    print(response)

async def run_light_show():
    # Connect to the websocket endpoint
    async with websockets.connect(WS_URL) as websocket:
        # Example: let’s assume the matrix size is known from the server config
        # In the given API code, it sets:
        # LEDS_PER_WLED = 20 * 5 = 100
        # WLED_IPS = 4 controllers
        # LEDS_IN_MATRIX = 100 * 4 = 400 LEDs total
        #
        # Adjust this number if your setup differs.
        total_leds = 400
        
        # Simple pattern: We'll loop through a few animations.
        # For example, a color wipe effect or random twinkling.
        
        # 1. Clear the matrix to black
        black = "000000"
        await send_update(websocket, [black] * total_leds)
        await asyncio.sleep(1)

        # 2. Color wipe: red, left to right
        red = "ff0000"
        for i in range(total_leds):
            state = [black] * total_leds
            state[i] = red
            await send_update(websocket, state)
            await asyncio.sleep(0.02)

        # 3. Fill with green
        green = "00ff00"
        await send_update(websocket, [green] * total_leds)
        await asyncio.sleep(1)

        # 4. Random twinkle: randomly choose LEDs and assign random colors
        for _ in range(50):  # 50 frames of random twinkles
            state = []
            for __ in range(total_leds):
                # Random color
                r = random.randint(0,255)
                g = random.randint(0,255)
                b = random.randint(0,255)
                state.append(f"{r:02x}{g:02x}{b:02x}")
            await send_update(websocket, state)
            await asyncio.sleep(0.1)
        
        # 5. End by clearing to black
        await send_update(websocket, [black] * total_leds)
        await asyncio.sleep(1)

        print("Light show completed.")

if __name__ == "__main__":
    asyncio.run(run_light_show())
