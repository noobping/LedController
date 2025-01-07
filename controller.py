import socket
import time
import math
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# 4 WLED controllers, each driving 5 strips of 100 LEDs => 500 LEDs total
controllers = {
    "top_left":     "192.168.107.122",
    "top_right":    "192.168.107.123",
    "bottom_right": "192.168.107.120",
    "bottom_left":  "192.168.107.121"
}

PORT = 19446     # WLED default realtime DRGB port
FPS_TARGET = 60
LEDS_PER_STRIP = 100
NUM_STRIPS = 5
TOTAL_LEDS = LEDS_PER_STRIP * NUM_STRIPS  # 500

def build_rainbow_frame(t):
    """
    Builds a time-based rainbow across all 500 LEDs.
    The color is determined by a sine-wave function that shifts with time 't'.

    You can tweak the 0.06 multiplier, the (sin(...) + 1) * 127 portion, etc.
    """
    colors = []
    for i in range(TOTAL_LEDS):
        r = int((math.sin(t + i * 0.06) + 1) * 127)
        g = int((math.sin(t + i * 0.06 + 2*math.pi/3) + 1) * 127)
        b = int((math.sin(t + i * 0.06 + 4*math.pi/3) + 1) * 127)
        colors.append((r, g, b))
    return colors

def build_packet(color_array):
    """
    Convert an array of (R,G,B) into a DRGB packet (3 bytes per LED, no header).
    """
    packet = bytearray()
    for (r, g, b) in color_array:
        packet += bytes([r, g, b])
    return packet

def main():
    logging.info("Starting 4-controller rainbow animation...")
    logging.info("Press Ctrl+C to stop.")

    # 1) Create one UDP socket per controller (so we don't recreate it each frame)
    sockets = {}
    for position, ip in controllers.items():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sockets[position] = s

    frame_interval = 1.0 / FPS_TARGET
    next_frame_time = time.time()
    t = 0.0

    # For measuring actual FPS
    frames_sent = 0
    start_time = time.time()

    try:
        while True:
            now = time.time()
            if now >= next_frame_time:
                # 2) Build the rainbow colors for all 500 LEDs
                color_array = build_rainbow_frame(t)
                packet = build_packet(color_array)

                # 3) Send to each controller
                for position, ip in controllers.items():
                    sock = sockets[position]
                    try:
                        sock.sendto(packet, (ip, PORT))
                    except Exception as e:
                        logging.error(f"Send error to {ip}: {e}")

                frames_sent += 1

                # 4) Print measured FPS once per second
                elapsed = now - start_time
                if elapsed >= 1.0:
                    fps = frames_sent / elapsed
                    logging.info(f"Measured FPS: {fps:.2f}")
                    frames_sent = 0
                    start_time = now

                # Schedule next frame
                next_frame_time += frame_interval
                t += frame_interval
            else:
                # Sleep exactly until next frame is due
                time.sleep(next_frame_time - now)

    except KeyboardInterrupt:
        logging.info("Stopping animation...")

    finally:
        # Cleanly close sockets
        for s in sockets.values():
            s.close()

if __name__ == "__main__":
    main()
