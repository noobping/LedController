import socket
import time
import math
import concurrent.futures
import logging
from typing import List, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# Constants
WLED_IPS = [
    "192.168.107.122",  # Index 0 -> Top right (Kantoor Lucas)
    "192.168.107.123",  # Index 1 -> Top left (DutchGrit)
    "192.168.107.120",  # Index 2 -> Bottom right (3D Printer)
    "192.168.107.121",  # Index 3 -> Bottom left (Finance)
]

WINDOWS_PER_CONTROLLER = 5
LEDS_PER_CONTROLLER = 100
# 20 LEDs per window
LEDS_PER_WINDOW = LEDS_PER_CONTROLLER // WINDOWS_PER_CONTROLLER  # 20 LEDs per window
WLED_CONTROLLERS = len(WLED_IPS)  # 4 controllers
TOTAL_LEDS = LEDS_PER_CONTROLLER * WLED_CONTROLLERS  # 400 LEDs
BYTES_PER_LED = 3  # R, G, B
FPS_TARGET = 120  # Target frames per second
PORT = 19446  # WLED’s real-time port


def make_rainbow_frame(t: float) -> List[Tuple[int, int, int]]:
    """
    Returns a list of (R, G, B) tuples for TOTAL_LEDS.
    This will allow a continuous rainbow across multiple controllers.
    """
    colors = []
    for i in range(TOTAL_LEDS):
        # Adjust the 0.06 “speed” factor as desired
        r = int((math.sin(t + i * 0.06) + 1) * 127)
        g = int((math.sin(t + i * 0.06 + 2 * math.pi / 3) + 1) * 127)
        b = int((math.sin(t + i * 0.06 + 4 * math.pi / 3) + 1) * 127)
        colors.append((r, g, b))
    return colors


def build_packet(colors):
    """
    Builds the DRGB packet (no header, just RGB bytes).
    """
    packet = bytearray()
    for r, g, b in colors:
        packet += bytes([r, g, b])
    return packet


def send_packet(ip: str, port: int, packet: bytes) -> None:
    """
    Send a UDP packet to a specified WLED controller.

    Args:
        ip (str): IP address of the WLED controller.
        port (int): Port number to send the packet to.
        packet (bytes): The packet to send.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.sendto(packet, (ip, port))
            logging.debug(f"Sent packet of {len(packet)} bytes to {ip}:{port}")
        except Exception as e:
            logging.error(f"Failed to send packet to {ip}:{port} - {e}")


def main():
    frame_interval = 1.0 / FPS_TARGET # Time between frames in seconds
    frames_sent = 0 # Number of frames sent in the last second
    start_time = time.time() # Time in seconds
    t = 0.0 # Time in seconds

    logging.info("Starting WLED parallel sender...")
    logging.info(f"Targeting IPs: {WLED_IPS}, Port: {PORT}, FPS: {FPS_TARGET}")
    logging.info(
        f"LEDs per controller: {
            LEDS_PER_CONTROLLER}, Total LEDs: {TOTAL_LEDS}"
    )

    # Use a ThreadPoolExecutor to send packets “in parallel”
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(WLED_IPS)) as executor:
        while True:
            # Calculate elapsed time
            current_time = time.time()
            elapsed_time = current_time - start_time

            # 1) Create one large color array for the ENTIRE 400-LED strip
            colors_for_all = make_rainbow_frame(t)
            # colors_for_all = [
            #     (255, 0, 0),  # Red
            #     (0, 255, 0),  # Green
            #     (0, 0, 255),  # Blue
            #     (255, 255, 0),  # Yellow
            #     (255, 0, 255),  # Magenta
            #     (0, 255, 255),  # Cyan
            #     (255, 255, 255),  # White
            # ]

            # 2) Build and send a separate packet for each controller's slice
            futures = []
            for idx, ip in enumerate(WLED_IPS):
                # Slice out this controller's 100 LEDs
                start_idx = idx * LEDS_PER_CONTROLLER
                end_idx = start_idx + LEDS_PER_CONTROLLER
                controller_colors = colors_for_all[start_idx:end_idx]

                # Build the packet for this subset and send
                packet = build_packet(controller_colors)
                futures.append(executor.submit(send_packet, ip, PORT, packet))

            frames_sent += 1

            # 3) Calculate and print FPS every second
            if elapsed_time >= 1.0:
                fps = frames_sent / elapsed_time
                logging.info(f"Measured FPS: {fps:.2f}")
                # Reset counters
                frames_sent = 0
                start_time = current_time

            # 4) Sleep to maintain target FPS and increment time
            time.sleep(frame_interval)
            t += frame_interval


if __name__ == "__main__":
    main()
