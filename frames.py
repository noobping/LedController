import random
from typing import List, Tuple
from settings import TOTAL_LEDS


def make_random_frame() -> List[Tuple[int, int, int]]:
    """
    Create an color array with random colors
    to each LED on every frame. This will cause flicker and chaos.

    Returns:
        A list of (R, G, B) tuples with random colors.
    """
    colors = []
    for _ in range(TOTAL_LEDS):
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        colors.append((r, g, b))
    return colors


def make_custom_frame(
    fps_counter: float,
    color1: Tuple[int, int, int] = (255, 0, 0),
    color2: Tuple[int, int, int] = (0, 0, 255),
    cycle_length: float = 5.0
) -> List[Tuple[int, int, int]]:
    """
    Create a custom color pattern for your LEDs.

    In this example, we:
      1. Blend from color1 to color2 across the strip.
      2. Shift the blend over time, so it animates.

    Args:
        :param fps_counter: Current time (seconds) since the animation started.
        :param color1: A tuple (R, G, B) for the first color.
        :param color2: A tuple (R, G, B) for the second color.
        :param cycle_length: How many seconds it takes to “complete” one full shift.

    Returns:
        A list of (R, G, B) tuples with a wave shifting between color1 and color2.
    """
    # Extract color channels for convenience
    r1, g1, b1 = color1
    r2, g2, b2 = color2

    # We’ll use time (fps_counter) to create a shifting ratio between color1 and color2
    # The ratio will oscillate between 0 and 1 using a sine wave.
    # Increase/decrease the speed by adjusting '2 * math.pi / cycle_length'.
    import math
    ratio = (math.sin((2 * math.pi / cycle_length) * fps_counter) + 1) / 2

    colors = []
    for i in range(TOTAL_LEDS):
        # For each LED, let's also adjust the ratio slightly by i’s position,
        # so that color transitions from one end of the strip to the other
        # (You can remove or modify this logic if you want a uniform effect)
        local_ratio = (ratio + i / TOTAL_LEDS) % 1.0

        # Blend each channel independently
        r = int(r1 * (1.0 - local_ratio) + r2 * local_ratio)
        g = int(g1 * (1.0 - local_ratio) + g2 * local_ratio)
        b = int(b1 * (1.0 - local_ratio) + b2 * local_ratio)

        colors.append((r, g, b))

    return colors


if __name__ == "__main__":
    import logging
    from animation import run_animation_frames
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    run_animation_frames(
        frame_factory=make_custom_frame,
        frame_args=(),  # No positional arguments needed
        frame_kwargs={"color1": (255, 0, 0), "color2": (
            0, 0, 255), "cycle_length": 5.0},
        fps_target=5
    )
