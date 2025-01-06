import socket
import time
import math
import concurrent.futures

WLED_IPS = [
    "192.168.107.123",
    "192.168.107.122",
    "192.168.107.120",
    "192.168.107.121"
]

# Suppose each controller has 100 LEDs in DRGB
NUM_LEDS = 100
BYTES_PER_LED = 3  # R, G, B
FPS = 60
PORT = 19446       # WLED’s default real-time DRGB port (check yours)

def make_frame(t):
    """
    Returns a list of (R, G, B) tuples for NUM_LEDS
    Example: a simple sine-wave rainbow.
    """
    colors = []
    for i in range(NUM_LEDS):
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

def send_packet(ip, port, packet):
    """Sends a UDP packet to one WLED IP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(packet, (ip, port))
    sock.close()

def main():
    frame_interval = 1.0 / FPS
    t = 0.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(WLED_IPS)) as executor:
        while True:
            # Build the DRGB packet
            colors = make_frame(t)
            packet = build_packet(colors)
            
            # Launch a thread for each IP
            futures = []
            for ip in WLED_IPS:
                futures.append(executor.submit(send_packet, ip, PORT, packet))
            
            # Optionally wait for all threads to finish
            concurrent.futures.wait(futures)
            
            time.sleep(frame_interval)
            t += frame_interval

if __name__ == "__main__":
    main()
