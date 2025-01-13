import math
import logging
from typing import List, Tuple

from settings import TOTAL_LEDS


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
    from animation import run_animation
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    run_animation(
        frame_factory=make_rainbow_frame,
        frame_args=(),   # No positional arguments needed
        frame_kwargs={},  # No keyword arguments needed
        fps_target=120
    )
