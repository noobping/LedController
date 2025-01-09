import random
import socket
import time
import concurrent.futures
import logging
from typing import List, Tuple

# Configure logging
logging.basicConfig(level=logging.DEBUG,
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
FRAME_INTERVAL = 5  # 5 seconds per frame
FPS_TARGET = 5  # Frames per second
PORT = 19446  # WLED’s real-time port


def make_christmas_frame(start_with_red: bool = True) -> List[Tuple[int, int, int]]:
    """
    Create a fixed red-green pattern with blocks of 20 LEDs each, starting with red or green.

    Args:
        start_with_red (bool): If True, start with red blocks; otherwise, start with green.

    Returns:
        List[Tuple[int, int, int]]: A list of (R, G, B) tuples with red and green colors.
    """
    logging.debug(f"Creating Christmas frame that starts with {
                  'red' if start_with_red else 'green'}")

    colors = []
    for i in range(TOTAL_LEDS):
        block = i // LEDS_PER_WINDOW  # Determine the block index
        if start_with_red:
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


def make_random_frame() -> List[Tuple[int, int, int]]:
    """
    Create an color array with random colors
    to each LED on every frame. This will cause flicker and chaos.

    :param t: Current time in seconds (unused, but included for consistency).
    :return: A list of (R, G, B) tuples with random colors.
    """
    colors = []
    for _ in range(TOTAL_LEDS):
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        colors.append((r, g, b))
    return colors


def make_custom_frame(
    t: float,
    color1: Tuple[int, int, int] = (255, 0, 0),
    color2: Tuple[int, int, int] = (0, 0, 255),
    cycle_length: float = 5.0
) -> List[Tuple[int, int, int]]:
    """
    Create a custom color pattern for your LEDs.

    In this example, we:
      1. Blend from color1 to color2 across the strip.
      2. Shift the blend over time, so it animates.

    :param t: Current time (seconds) since the animation started.
    :param color1: A tuple (R, G, B) for the first color.
    :param color2: A tuple (R, G, B) for the second color.
    :param cycle_length: How many seconds it takes to “complete” one full shift.
    :return: A list of (R, G, B) tuples.
    """
    # Extract color channels for convenience
    r1, g1, b1 = color1
    r2, g2, b2 = color2

    # We’ll use time (t) to create a shifting ratio between color1 and color2
    # The ratio will oscillate between 0 and 1 using a sine wave.
    # Increase/decrease the speed by adjusting '2 * math.pi / cycle_length'.
    import math
    ratio = (math.sin((2 * math.pi / cycle_length) * t) + 1) / 2

    colors = []
    for i in range(TOTAL_LEDS):
        # For each LED, let's also adjust the ratio slightly by i’s position,
        # so that color transitions from one end of the strip to the other
        # (You can remove or modify this logic if you want a uniform effect)
        local_ratio = (ratio + i / TOTAL_LEDS) % 1.0

        # Blend each channel independently
        r = int(r1 * (1.0 - local_ratio) + r2 * local_ratio)
        g = int(g1 * (1.0 - local_ratio) + g2 * local_ratio)
        b = int(b1 * (1.0 - local_ratio) + b2 * local_ratio)

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
            # logging.debug(f"Sent packet of {len(packet)} bytes to {ip}:{port}")
        except Exception as e:
            logging.error(f"Failed to send packet to {ip}:{port} - {e}")


def main():
    logging.info("Starting WLED parallel sender...")
    logging.info(f"Targeting IPs: {WLED_IPS}, Port: {PORT}")
    logging.info(
        f"LEDs per controller: {
            LEDS_PER_CONTROLLER}, Total LEDs: {TOTAL_LEDS}"
    )

    t: bool = False

    # Use a ThreadPoolExecutor to send packets “in parallel”
    while True:
        # 1) Choose color array (t will flip between red→green)
        colors_for_all = make_christmas_frame(t)

        # 2) Build the packets for each controller
        packets = []
        for idx, ip in enumerate(WLED_IPS):
            start_idx = idx * LEDS_PER_CONTROLLER
            end_idx = start_idx + LEDS_PER_CONTROLLER
            controller_colors = colors_for_all[start_idx:end_idx]
            packet = build_packet(controller_colors)
            packets.append((ip, packet))

        # 3) Send the same color repeatedly for the whole 5 seconds
        start_time = time.time()
        while time.time() - start_time < FRAME_INTERVAL:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(WLED_IPS)) as executor:
                futures = [executor.submit(
                    send_packet, ip, PORT, packet) for ip, packet in packets]
                concurrent.futures.wait(futures)

            # Sleep just enough to keep from flooding the network,
            # but ensure we don't exceed WLED’s timeout
            time.sleep(1.0 / FPS_TARGET)

        # Finally toggle t for next color
        t = not t


if __name__ == "__main__":
    main()
