import logging

try:
    import video
except ImportError:
    print("Missing 'video.py' file. Please make sure it is in the same directory.")
    exit(1)

try:
    import keyboard
except ImportError:
    print("Please install the 'keyboard' package (pip install keyboard).")
    exit(1)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")


def keyboard_listener(loop: bool = False, max_fps: float = None):
    """
    Listens for keyboard inputs to control video playback.
    Press 'v' to play a video (you will be prompted for the path) and 'q' to quit.
    """
    logging.info("Press 'v' to play a video, 'q' to quit.")
    while True:
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            if event.name == 'v':
                video_path = input("Enter the path to the video file: ")
                logging.info(f"Starting video playback: {video_path}")
                video.play_video(video_path, loop=loop, max_fps=max_fps)
            elif event.name == 'q':
                logging.info("Quitting...")
                break


if __name__ == "__main__":
    keyboard_listener()
