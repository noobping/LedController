import socket
import time
import math
import concurrent.futures
import logging
import random
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


def make_colored_frame(color: Tuple[int, int, int] = (255, 255, 255)) -> List[Tuple[int, int, int]]:
    """
    Return a list of the same (R, G, B) color for all LEDs.

    :param color: A tuple (R, G, B) specifying the static color.
    :return: A list of (R, G, B) tuples, all the same.
    """
    return [color] * TOTAL_LEDS


def make_multistrip_frame(
    color_list: List[Tuple[int, int, int]],
) -> List[Tuple[int, int, int]]:
    """
    Assign a static color to each strip in a multi-strip setup.

    Args:
        color_list (List[Tuple[int, int, int]]): List of colors for each strip.

    Raises:
        ValueError: If the length of color_list doesn't match NUM_WLED_CONTROLLERS.

    Returns:
        List[Tuple[int, int, int]]: Combined list of (R, G, B) tuples for all strips.
    """
    if len(color_list) != WLED_CONTROLLERS:
        raise ValueError(
            f"Expected {WLED_CONTROLLERS} colors, got {len(color_list)}"
        )

    colors_for_all = []
    for strip_color in color_list:
        colors_for_all.extend([strip_color] * LEDS_PER_CONTROLLER)

    return colors_for_all


def make_manual_frame(
    color_config: List[List[Tuple[int, int, int]]]
) -> List[Tuple[int, int, int]]:
    """
    Manually assign colors to each LED on each controller.

    Args:
        color_config (List[List[Tuple[int, int, int]]]): 
            2D list where color_config[controller_idx][window_idx] is (R, G, B).

    Returns:
        List[Tuple[int, int, int]]: Combined list of (R, G, B) tuples for all controllers.
    """
    colors_for_all = []
    for controller_idx, controller_windows in enumerate(color_config):
        for window_idx, window_color in enumerate(controller_windows):
            colors_for_all.extend([window_color] * LEDS_PER_WINDOW)
    return colors_for_all


def build_packet(colors):
    """
    Builds the DRGB packet (no header, just RGB bytes).
    """
    packet = bytearray()
    for r, g, b in colors:
        packet += bytes([r, g, b])
    return packet


def build_packets(colors_for_all: List[Tuple[int, int, int]]) -> List[Tuple[str, bytes]]:
    """
    Construct DNRGB packets for each WLED controller from the combined colors list.
    DNRGB format:
      Byte 0 = 4  (DNRGB protocol)
      Bytes 1-2 = Start index (big endian)
      Bytes 3+ = [R, G, B] x LED_count

    Args:
        colors_for_all (List[Tuple[int, int, int]]): Combined list of colors for all controllers.

    Returns:
        List[Tuple[str, bytes]]: List of tuples containing IP and packet bytes for each controller.
    """
    # Ensure each controller has exactly LEDS_PER_CONTROLLER
    expected_len = LEDS_PER_CONTROLLER * WLED_CONTROLLERS
    if len(colors_for_all) != expected_len:
        raise ValueError(
            f"colors_for_all length {len(colors_for_all)} does not match expected {
                expected_len} LEDs."
        )

    packets = []
    for idx, ip in enumerate(WLED_IPS):
        start_idx = 0
        while start_idx < LEDS_PER_CONTROLLER:
            # Define maximum LEDs per DNRGB packet (use 490 to be safe)
            max_leds_per_packet = 490
            remaining_leds = LEDS_PER_CONTROLLER - start_idx
            leds_in_this_packet = min(max_leds_per_packet, remaining_leds)

            # Calculate the absolute start index for this packet
            absolute_start_idx = idx * LEDS_PER_CONTROLLER + start_idx

            # Extract the subset of colors for this packet
            end_idx = start_idx + leds_in_this_packet
            controller_colors = colors_for_all[idx * LEDS_PER_CONTROLLER +
                                               start_idx: idx * LEDS_PER_CONTROLLER + end_idx]

            # Create the packet
            packet = bytearray()
            packet.append(4)  # Byte 0 = 4 -> DNRGB protocol
            packet += (absolute_start_idx).to_bytes(2,
                                                    byteorder='big')  # Bytes 1-2 = Start index

            # Append RGB data
            for (r, g, b) in controller_colors:
                packet += bytes([r, g, b])

            packets.append((ip, bytes(packet)))

            # Increment the start index
            start_idx += leds_in_this_packet

    return packets


def test_packet():
    """
    Test sending DNRGB packets to all controllers with all LEDs set to red.
    """
    test_color = (255, 0, 0)  # Red
    colors_for_all = make_colored_frame(test_color)

    try:
        packets = build_packets(colors_for_all)
    except ValueError as ve:
        logging.error(f"Error building packets: {ve}")
        return

    for ip, packet in packets:
        send_packet(ip, PORT, packet)
        logging.info(f"Test packet sent to {ip}:{PORT}")


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

    # Define the colors for each strip
    color_per_strip = [
        (0, 51, 102),     # Kantoor Lucas - Navy Blue
        (255, 165, 0),    # DutchGrit - Orange
        (112, 128, 144),  # 3D Printer - Slate Gray
        (0, 0, 255)     # Finance - Blue
    ]

    # Define the colors for each window on each controller
    # color_per_window_per_controller[controller_index][window_index] -> (R, G, B)
    color_per_window_per_controller = [
        # Top right (Kantoor Lucas)
        [
            (0, 51, 102),    # Window 0
            (0, 51, 102),    # Window 1
            (0, 51, 102),    # Window 2
            (0, 51, 102),    # Window 3
            (0, 51, 102),    # Window 4
        ],
        # Top left (DutchGrit)
        [
            (255, 165, 0),   # Window 0
            (255, 165, 0),   # Window 1
            (255, 165, 0),   # Window 2
            (255, 165, 0),   # Window 3
            (255, 165, 0),   # Window 4
        ],
        # Bottom right (3D Printer)
        [
            (112, 128, 144),  # Window 0
            (112, 128, 144),  # Window 1
            (112, 128, 144),  # Window 2
            (112, 128, 144),  # Window 3
            (112, 128, 144),  # Window 4
        ],
        # Bottom left (Finance)
        [
            (0, 0, 255),   # Window 0
            (0, 0, 255),   # Window 1
            (0, 0, 255),   # Window 2
            (0, 0, 255),   # Window 3
            (0, 0, 255),   # Window 4
        ],
    ]

    # Use a ThreadPoolExecutor to send packets “in parallel”
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(WLED_IPS)) as executor:
        while True:
            # Calculate elapsed time
            current_time = time.time()
            elapsed_time = current_time - start_time

            # 1) Create one large color array for the ENTIRE 400-LED strip
            colors_for_all = make_rainbow_frame(t)

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
