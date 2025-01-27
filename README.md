# LedController

The docker-based LedController for LS HQ.

## Video player

Run the following command to start the video light show:

```bash
python ./video.py --video <video> --loop
```

For example:

```bash
python ./video.py --video ./video/windows_21_dec.mp4 --loop
```

## Web API

Start the web API:

```bash
python ./main.py
```

Endpoints:

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | / | Returns information about the API and its capabilities. |
| GET | /health | Health check endpoint to verify if the WLED controllers are reachable. |
| POST | /christmas | Starts the Christmas animation. |
| DELETE | /christmas | Stops any ongoing video playback. |
| POST | /piano/{controller_idx}/{window_idx} | Lights up exactly one window (20 LEDs) in white for a given controller+window. All other LEDs are off (black). |
| DELETE | /piano | Stops any ongoing video playback. |
| GET | /video | Returns the names (without extension) of all .mp4 files in the /videos folder. |
| POST | /video/{video_name} | Starts looping the given video file. |
| DELETE | /video | Stops any ongoing video playback. |
| DELETE | /video/{video_name} | Stops any ongoing video playback. |
| GET | /brightness | Returns the current brightness value. |
| POST | /brightness/{value} | Sets brightness (0-255) on all WLED controllers. |
