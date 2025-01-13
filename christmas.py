import logging
from typing import List, Tuple

from settings import LEDS_PER_WINDOW, TOTAL_LEDS


def make_christmas_frame(enabled: bool = True, **state) -> List[Tuple[int, int, int]]:
    """
    Create a fixed red-green pattern with blocks of LEDs each, starting with red or green.

    Args:
        enabled (bool): If True, start with red blocks; otherwise, start with green.
        **state: Additional state variables.

    Returns:
        List[Tuple[int, int, int]]: A list of (R, G, B) tuples with red and green colors.
    """
    logging.debug(f"Creating Christmas frame that starts with {
                  'red' if enabled else 'green'}")

    colors = []
    for i in range(TOTAL_LEDS):
        block = i // LEDS_PER_WINDOW  # Determine the block index
        if enabled:
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


if __name__ == "__main__":
    from animation import run_animation_interval
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)s %(message)s")

    run_animation_interval(
        frame_factory=make_christmas_frame,
        frame_args=(),             # No positional arguments needed
        frame_kwargs={},           # No keyword arguments needed
        state={"enabled": False},   # Initial state
        frame_interval=5,
        fps_target=5
    )
