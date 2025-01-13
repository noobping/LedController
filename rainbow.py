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


def make_rainbow_frame(fps_counter: float) -> List[Tuple[int, int, int]]:
    """
    Make a rainbow frame.

    Args:
        fps_counter (float): Current time (seconds) since the animation started.

    Returns:
        List[Tuple[int, int, int]]: A list of (R, G, B) tuples for all LEDs
    """
    colors = []
    for i in range(TOTAL_LEDS):
        # The 0.06 is the “speed” factor
        r = int((math.sin(fps_counter + i * 0.06) + 1) * 127)
        g = int((math.sin(fps_counter + i * 0.06 + 2 * math.pi / 3) + 1) * 127)
        b = int((math.sin(fps_counter + i * 0.06 + 4 * math.pi / 3) + 1) * 127)
        colors.append((r, g, b))
    return colors


if __name__ == "__main__":
    from animation import run_animation_frames

    run_animation_frames(
        frame_factory=make_rainbow_frame,
        frame_args=(),   # No positional arguments needed
        frame_kwargs={},  # No keyword arguments needed
        fps_target=120
    )
