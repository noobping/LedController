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
PORT = 19446  # WLED’s real-time port


def make_christmas_frame(start_with_red: bool = True) -> List[Tuple[int, int, int]]:
    """
    Create a fixed red-green pattern with blocks of 20 LEDs each, starting with red or green.

    Args:
        start_with_red (bool): If True, start with red blocks; otherwise, start with green.

    Returns:
        List[Tuple[int, int, int]]: A list of (R, G, B) tuples with red and green colors.
    """
    logging.debug(f"Creating Christmas frame that starts with {'red' if start_with_red else 'green'}")

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


def build_packet(colors):
    """
    Builds the DRGB packet (no header, just RGB bytes).
    """
    packet = bytearray()
    for r, g, b in colors:
        packet += bytes([r, g, b])
    return packet
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
    frame_interval = 5  # 5 seconds per frame

    # Use a ThreadPoolExecutor to send packets “in parallel”
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(WLED_IPS)) as executor:
        while True:
            # 1) Create one large color array for the ENTIRE 400-LED strip
            colors_for_all = make_christmas_frame(t)

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

            # 3) Wait for all packets to be sent
            concurrent.futures.wait(futures)

            # 4) Sleep to maintain target FPS and increment time
            time.sleep(frame_interval)
            t = not t


if __name__ == "__main__":
    main()
