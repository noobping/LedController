import socket
import time
import math
import concurrent.futures
import logging

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

WLED_IPS = [
    "192.168.107.123",  # Top left
    "192.168.107.122",  # Top right
    "192.168.107.120",  # Bottom right
    "192.168.107.121",  # Bottom left
]

# Each controller has 100 LEDs in DRGB
NUM_LEDS_PER_CONTROLLER = 100
BYTES_PER_LED = 3  # R, G, B
FPS_TARGET = 60
PORT = 19446  # WLED’s real-time DRGB port


def make_rainbow_frame(t, total_num_leds):
    """
    Returns a list of (R, G, B) tuples for total_num_leds.
    This will allow a continuous rainbow across multiple controllers.
    """
    colors = []
    for i in range(total_num_leds):
        # Adjust the 0.06 “speed” factor as desired
        r = int((math.sin(t + i * 0.06) + 1) * 127)
        g = int((math.sin(t + i * 0.06 + 2 * math.pi / 3) + 1) * 127)
        b = int((math.sin(t + i * 0.06 + 4 * math.pi / 3) + 1) * 127)
        colors.append((r, g, b))
    return colors


def make_christmas_frame(t, total_num_leds):
    """
    Returns a list of (R, G, B) tuples for total_num_leds,
    creating an animated red-green pattern.

    :param t: The time in seconds since the animation started.
    :param total_num_leds: The total number of LEDs to color.
    :return: A list of (R, G, B) tuples.
    """

    # This "offset" shifts every second (or so) to animate the pattern
    # Increase or decrease the multiplier (2) for a faster/slower shift
    offset = int(t * 2)
    colors = []

    for i in range(total_num_leds):
        # Decide whether this LED is red or green by looking at (i + offset)
        if (i + offset) % 2 == 0:
            # Red
            colors.append((255, 0, 0))
        else:
            # Green
            colors.append((0, 255, 0))

    return colors


def build_packet(colors):
    """
    Builds the DRGB packet (no header, just RGB bytes).
    """
    packet = bytearray()
    for r, g, b in colors:
        packet += bytes([r, g, b])
    return packet


def send_packet(ip, port, packet):
    """Sends a UDP packet to one WLED IP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, (ip, port))
        logging.debug(f"Sent packet of length {
                      len(packet)} bytes to {ip}:{port}")
    except Exception as e:
        logging.error(f"Failed to send packet to {ip}:{port} - {e}")
    finally:
        sock.close()


def main():
    frame_interval = 1.0 / FPS_TARGET

    # Variables for FPS measurement
    frames_sent = 0
    start_time = time.time()

    t = 0.0

    # Calculate total number of LEDs across all controllers
    total_leds = len(WLED_IPS) * NUM_LEDS_PER_CONTROLLER

    logging.info("Starting WLED parallel sender...")
    logging.info(f"Targeting IPs: {WLED_IPS}, Port: {PORT}, FPS: {FPS_TARGET}")
    logging.info(
        f"LEDs per controller: {
            NUM_LEDS_PER_CONTROLLER}, Total LEDs: {total_leds}"
    )

    # Use a ThreadPoolExecutor to send packets “in parallel”
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(WLED_IPS)) as executor:
        while True:
            # 1) Create one large color array for the ENTIRE 400-LED strip
            colors_for_all = make_christmas_frame(t, total_leds)

            # 2) Build and send a separate packet for each controller's slice
            futures = []
            for idx, ip in enumerate(WLED_IPS):
                # Slice out this controller's 100 LEDs
                start_idx = idx * NUM_LEDS_PER_CONTROLLER
                end_idx = start_idx + NUM_LEDS_PER_CONTROLLER
                controller_colors = colors_for_all[start_idx:end_idx]

                # Build the packet for this subset and send
                packet = build_packet(controller_colors)
                futures.append(executor.submit(send_packet, ip, PORT, packet))

            frames_sent += 1

            # 3) Calculate and print FPS every second
            now = time.time()
            elapsed = now - start_time
            if elapsed >= 1.0:
                fps = frames_sent / elapsed
                logging.info(f"Measured FPS: {fps:.2f}")
                # Reset counters
                frames_sent = 0
                start_time = now

            # 4) Sleep to maintain target FPS and increment time
            time.sleep(frame_interval)
            t += frame_interval


if __name__ == "__main__":
    main()
