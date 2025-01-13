import socket
import time
import logging
import concurrent.futures
from typing import List, Tuple

try:
    import keyboard
except ImportError:
    print("Please install the 'keyboard' package (pip install keyboard).")
    exit(1)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# The IPs of your four WLED controllers
WLED_IPS = [
    "192.168.107.123",  # Index 0 -> Top Left
    "192.168.107.122",  # Index 1 -> Top Right
    "192.168.107.120",  # Index 2 -> Bottom Right
    "192.168.107.121",  # Index 3 -> Bottom Left
]

PORT = 19446             # WLED’s real-time UDP port
LEDS_PER_CONTROLLER = 100
WINDOWS_PER_CONTROLLER = 5
LEDS_PER_WINDOW = LEDS_PER_CONTROLLER // WINDOWS_PER_CONTROLLER  # 20
TOTAL_CONTROLLERS = len(WLED_IPS)
TOTAL_LEDS = LEDS_PER_CONTROLLER * TOTAL_CONTROLLERS  # 400
BYTES_PER_LED = 3       # R, G, B

# Map each keyboard key to (controller_index, window_index)
KEY_TO_WINDOW = {
    # Top Left (index=1)
    'q': (1, 0), 'w': (1, 1), 'e': (1, 2), 'r': (1, 3), 't': (1, 4),

    # Top Right (index=0)
    'y': (0, 0), 'u': (0, 1), 'i': (0, 2), 'o': (0, 3), 'p': (0, 4),

    # Bottom Left (index=3)
    'a': (3, 0), 's': (3, 1), 'd': (3, 2), 'f': (3, 3), 'g': (3, 4),

    # Bottom Right (index=2)
    'h': (2, 0), 'j': (2, 1), 'k': (2, 2), 'l': (2, 3), ';': (2, 4),
}


def build_packet(colors: List[Tuple[int, int, int]]) -> bytes:
    """
    Builds the DRGB packet (no header, just RGB bytes) for the entire LED array.
    """
    colors = colors[::-1]  # Reverse the order of the colors

    packet = bytearray()
    for (r, g, b) in colors:
        packet += bytes([r, g, b])
    return packet


def send_packet(ip: str, port: int, packet: bytes) -> None:
    """
    Send a UDP packet to a specified WLED controller.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(packet, (ip, port))


def get_color_frame_for_key(key: str) -> List[Tuple[int, int, int]]:
    """
    Build a color array of length TOTAL_LEDS (400).
    All LEDs off (black) except the 20 LEDs corresponding to the pressed key.
    """
    # Start all LEDs off
    logging.debug("Clearing all LEDs")
    colors = [(0, 0, 0)] * TOTAL_LEDS

    logging.debug(f"Key pressed: {key}")
    if key not in KEY_TO_WINDOW:
        # Unmapped key => do nothing
        return colors

    controller_idx, window_idx = KEY_TO_WINDOW[key]
    # The LED index range within that controller
    start_led = window_idx * LEDS_PER_WINDOW
    end_led = start_led + LEDS_PER_WINDOW

    # Convert the “local” controller slice to the absolute slice in the 400-LED array
    absolute_start = controller_idx * LEDS_PER_CONTROLLER + start_led
    absolute_end = controller_idx * LEDS_PER_CONTROLLER + end_led

    # Set those 20 LEDs to red
    new_colors = list(colors)
    for i in range(absolute_start, absolute_end):
        logging.debug(f"Setting LED {i} to red")
        new_colors[i] = (255, 0, 0)

    # Count the number of red and black LEDs
    logging.info(f"Red LEDs: {new_colors.count((255, 0, 0))} and Black LEDs: {
                 new_colors.count((0, 0, 0))}")
    return new_colors


def send_frames_in_parallel(colors: List[Tuple[int, int, int]]):
    """
    Slice the 400-LED color array per controller and send in parallel.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=TOTAL_CONTROLLERS) as executor:
        futures = []
        for idx, ip in enumerate(WLED_IPS):
            # Slice out this controller's 100 LEDs
            start_idx = idx * LEDS_PER_CONTROLLER
            end_idx = start_idx + LEDS_PER_CONTROLLER
            controller_slice = colors[start_idx:end_idx]
            logging.debug(f"Sending to {len(controller_slice)} LEDs at {
                          ip}: {controller_slice}")

            # Build and send this subset
            packet = build_packet(controller_slice)
            futures.append(executor.submit(send_packet, ip, PORT, packet))


def main():
    logging.info("Starting piano-like WLED controller.")
    logging.info(
        "Press one of the mapped keys (q w e r t ... ;). Press ESC to quit.")

    def on_key_press(event):
        key_str = event.name  # e.g. 'q', 'w', etc.
        if key_str == 'esc':
            logging.info("ESC pressed. Exiting...")
            keyboard.unhook_all()
            exit(0)

        # Build the color frame for the pressed key
        colors = get_color_frame_for_key(key_str)
        # Send them in parallel
        send_frames_in_parallel(colors)

    # Hook into keyboard events
    keyboard.on_press(on_key_press)

    # Keep the script alive forever (until ESC)
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        logging.info("Interrupted by user. Exiting...")


if __name__ == "__main__":
    main()
