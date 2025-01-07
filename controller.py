import socket
import time
import math
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Four WLED controllers
WLED_IPS = [
    "192.168.107.123",
    "192.168.107.122",
    "192.168.107.120",
    "192.168.107.121"
]

# Per-controller LED configuration
NUM_LEDS = 100
FPS_TARGET = 60
PORT = 19446  # WLED Realtime UDP (DRGB) port

def make_rainbow_frame(t):
    """
    Returns a list of (R, G, B) tuples for NUM_LEDS
    Example: a simple sine-wave rainbow.
    """
    colors = []
    for i in range(NUM_LEDS):
        # This is just an example pattern:
        r = int((math.sin(t + i*0.06) + 1) * 127)
        g = int((math.sin(t + i*0.06 + 2*math.pi/3) + 1) * 127)
        b = int((math.sin(t + i*0.06 + 4*math.pi/3) + 1) * 127)
        colors.append((r, g, b))
    return colors

def build_packet(colors):
    """
    Builds the DRGB packet (no header, just RGB bytes).
    """
    packet = bytearray()
    for (r, g, b) in colors:
        packet += bytes([r, g, b])
    return packet

def send_packet(sockets, ip, port, packet):
    """
    Sends a UDP packet to one WLED IP using a pre-opened socket.
    :param sockets: dict of { ip: socket.socket }
    :param ip: the IP address (string)
    :param port: the UDP port (int)
    :param packet: the raw bytes to send
    """
    try:
        sockets[ip].sendto(packet, (ip, port))
    except Exception as e:
        logging.error(f"Failed to send packet to {ip}:{port} - {e}")

def main():
    logging.info("Starting WLED parallel sender (one socket per IP).")
    logging.info(f"Targeting IPs: {WLED_IPS}, Port: {PORT}, FPS: {FPS_TARGET}, LEDs: {NUM_LEDS}")

    # 1) Create one UDP socket per IP (and store in a dictionary).
    sockets = {}
    for ip in WLED_IPS:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sockets[ip] = s

    # 2) Timing variables
    frame_interval = 1.0 / FPS_TARGET
    t = 0.0
    next_frame_time = time.time()

    # For measuring the actual achieved FPS
    frames_sent = 0
    start_time = time.time()

    try:
        while True:
            now = time.time()

            # If it's time (or past time) for the next frame...
            if now >= next_frame_time:
                # Build the color data
                colors = make_rainbow_frame(t)
                packet = build_packet(colors)

                # Send to each WLED IP sequentially (fast enough for 4 IPs)
                for ip in WLED_IPS:
                    send_packet(sockets, ip, PORT, packet)

                # Increment our FPS counter
                frames_sent += 1

                # Calculate and log FPS every second
                elapsed = now - start_time
                if elapsed >= 1.0:
                    fps = frames_sent / elapsed
                    logging.info(f"Measured FPS: {fps:.2f}")
                    frames_sent = 0
                    start_time = now

                # Schedule the next frame time
                next_frame_time += frame_interval
                t += frame_interval

            else:
                # Sleep only until the next frame is due
                time.sleep(next_frame_time - now)

    finally:
        # 3) Cleanly close all sockets if we exit the loop (Ctrl+C, etc.)
        for s in sockets.values():
            s.close()
        logging.info("Sockets closed, exiting.")

if __name__ == "__main__":
    main()
