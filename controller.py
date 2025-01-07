import socket
import time
import math
import concurrent.futures
import logging
import random

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


def make_rainbow_wave(t, total_num_leds):
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


def make_christmas_wave(t, total_num_leds):
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


def make_random_wave(t, total_num_leds):
    """
    Create an color array with random colors
    to each LED on every frame. This will cause flicker and chaos.

    :param t: Current time in seconds (unused, but included for consistency).
    :param total_num_leds: Total number of LEDs to color.
    :return: A list of (R, G, B) tuples with random colors.
    """
    colors = []
    for _ in range(total_num_leds):
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        colors.append((r, g, b))
    return colors


def make_custom_wave(t, total_num_leds, color1=(255, 0, 0), color2=(0, 0, 255), cycle_length=5.0):
    """
    Create a custom color pattern for your LEDs.

    In this example, we:
      1. Blend from color1 to color2 across the strip.
      2. Shift the blend over time, so it animates.

    :param t: Current time (seconds) since the animation started.
    :param total_num_leds: Total number of LEDs to color.
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
    for i in range(total_num_leds):
        # For each LED, let's also adjust the ratio slightly by i’s position,
        # so that color transitions from one end of the strip to the other
        # (You can remove or modify this logic if you want a uniform effect)
        local_ratio = (ratio + i / total_num_leds) % 1.0

        # Blend each channel independently
        r = int(r1 * (1.0 - local_ratio) + r2 * local_ratio)
        g = int(g1 * (1.0 - local_ratio) + g2 * local_ratio)
        b = int(b1 * (1.0 - local_ratio) + b2 * local_ratio)

        colors.append((r, g, b))

    return colors


def make_static_color(t, total_num_leds, color=(255, 255, 255)):
    """
    Return a list of the same (R, G, B) color for all LEDs.

    :param t: Current time (seconds) since animation start (unused here).
    :param total_num_leds: The total number of LEDs to color.
    :param color: A tuple (R, G, B) specifying the static color.
    :return: A list of (R, G, B) tuples, all the same.
    """
    return [color] * total_num_leds


def make_multistrip_static_colors(
    total_strips,
    leds_per_strip,
    color_list
):
    """
    Returns a color array for a multi-strip setup, 
    where each strip is assigned a single static color
    from 'color_list'.

    :param total_strips: Number of strips (controllers).
    :param leds_per_strip: Number of LEDs in each strip.
    :param color_list: A list of (R, G, B) tuples. 
                       Must have exactly 'total_strips' items.

    :return: A list of (R, G, B) tuples whose length is 
             total_strips * leds_per_strip.
    """
    if len(color_list) != total_strips:
        raise ValueError(
            f"Expected {total_strips} colors, got {len(color_list)}"
        )

    colors_for_all = []
    for i in range(total_strips):
        # The static color for strip i
        strip_color = color_list[i]
        # Fill this strip's portion with that color
        for _ in range(leds_per_strip):
            colors_for_all.append(strip_color)

    return colors_for_all


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
    total_strips = len(WLED_IPS)
    leds_per_strip = NUM_LEDS_PER_CONTROLLER
    total_leds = total_strips * leds_per_strip

    logging.info("Starting WLED parallel sender...")
    logging.info(f"Targeting IPs: {WLED_IPS}, Port: {PORT}, FPS: {FPS_TARGET}")
    logging.info(
        f"LEDs per controller: {
            NUM_LEDS_PER_CONTROLLER}, Total LEDs: {total_leds}"
    )

    color_per_strip = [
        (255, 0, 0),     # Strip 0: Red
        (0, 255, 0),     # Strip 1: Green
        (0, 0, 255),     # Strip 2: Blue
        (255, 255, 0)    # Strip 3: Yellow
    ]

    # Use a ThreadPoolExecutor to send packets “in parallel”
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(WLED_IPS)) as executor:
        while True:
            # 1) Create one large color array for the ENTIRE 400-LED strip
            # colors_for_all = make_custom_wave(
            #     t,
            #     total_leds,
            #     color1=(128, 64, 64),  # soft red tone
            #     color2=(64, 128, 64),  # soft green tone
            #     cycle_length=20.0      # gentle wave
            # )
            colors_for_all = make_multistrip_static_colors(
                total_strips,
                leds_per_strip,
                color_per_strip
            )

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
